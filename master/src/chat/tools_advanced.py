"""
CycleKernel Advanced Tool Calling Protocol v2
==============================================
Builds on tools.py (v1) with:

  • Parallel tool execution (asyncio.gather)
  • ToolChoice strategies: auto | required | none | {force tool}
  • Per-tool policy: timeout, retries, max concurrency, rate limit
  • JSON Schema argument validation
  • Approval gates (human-in-the-loop / policy deny)
  • Middleware hooks: before_call / after_call / on_error
  • Trace IDs + structured span events
  • Result truncation & redaction
  • Circuit breaker per tool
  • Compositional plans (tool DAG / depends_on)

Wire format remains OpenAI-compatible so custom LLMs keep working.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Union

from tools import (
    REGISTRY,
    ToolCall,
    ToolResult,
    ToolRegistry,
    ToolSpec,
    parse_tool_calls_from_message,
    tool_results_to_messages,
)

from circuit_breaker import BREAKERS, CircuitBreakerRegistry, CircuitConfig, CircuitState
from bulkhead import BULKHEADS, BulkheadRegistry

logger = logging.getLogger("ck.tools.advanced")


# ---------------------------------------------------------------------------
# Enums / policy
# ---------------------------------------------------------------------------

class ToolChoiceMode(str, Enum):
    AUTO = "auto"
    REQUIRED = "required"
    NONE = "none"
    # force a specific tool via ToolChoice(mode=AUTO is not used; use force_tool=)


@dataclass
class ToolChoice:
    mode: ToolChoiceMode = ToolChoiceMode.AUTO
    force_tool: Optional[str] = None  # when set, only this tool may run

    def to_openai(self) -> Union[str, Dict[str, Any]]:
        if self.force_tool:
            return {"type": "function", "function": {"name": self.force_tool}}
        return self.mode.value


@dataclass
class ToolPolicy:
    timeout_sec: float = 30.0
    max_retries: int = 1
    retry_backoff_sec: float = 0.6
    max_concurrency: int = 4
    rate_limit_per_min: int = 30
    requires_approval: bool = False
    max_result_chars: int = 12000
    circuit_fail_threshold: int = 5
    circuit_cooldown_sec: float = 60.0
    allowed_roles: List[str] = field(default_factory=lambda: ["assistant", "system", "user"])


DEFAULT_POLICIES: Dict[str, ToolPolicy] = {
    "research": ToolPolicy(timeout_sec=45, max_retries=2, rate_limit_per_min=20),
    "scrape": ToolPolicy(timeout_sec=40, max_retries=2, rate_limit_per_min=15),
    "planning": ToolPolicy(timeout_sec=10, max_retries=0),
    "coding": ToolPolicy(timeout_sec=90, max_retries=1, rate_limit_per_min=10),
    "pipeline": ToolPolicy(timeout_sec=120, max_retries=0, rate_limit_per_min=8),
    "get_mood": ToolPolicy(timeout_sec=5, max_retries=1, rate_limit_per_min=60),
    "terminal_execute": ToolPolicy(
        timeout_sec=30,
        max_retries=0,
        requires_approval=True,  # sandbox writes — gate by default
        rate_limit_per_min=10,
    ),
}


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------

@dataclass
class SpanEvent:
    ts: float
    kind: str
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolTrace:
    trace_id: str
    spans: List[SpanEvent] = field(default_factory=list)

    def event(self, kind: str, **detail: Any) -> None:
        self.spans.append(SpanEvent(ts=time.time(), kind=kind, detail=detail))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "spans": [
                {"ts": s.ts, "kind": s.kind, **s.detail} for s in self.spans
            ],
        }


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

BeforeHook = Callable[[ToolCall, ToolTrace], Awaitable[Optional[str]]]
# return None to proceed, or a denial reason string

AfterHook = Callable[[ToolCall, ToolResult, ToolTrace], Awaitable[ToolResult]]
ErrorHook = Callable[[ToolCall, Exception, ToolTrace], Awaitable[None]]


@dataclass
class Middleware:
    before: List[BeforeHook] = field(default_factory=list)
    after: List[AfterHook] = field(default_factory=list)
    on_error: List[ErrorHook] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Circuit breaker + rate limiter
# ---------------------------------------------------------------------------

# CircuitBreaker moved to circuit_breaker.py (CLOSED / OPEN / HALF_OPEN)
# Use BREAKERS registry from circuit_breaker import.


class RateLimiter:
    def __init__(self):
        self.hits: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, name: str, policy: ToolPolicy) -> bool:
        now = time.time()
        window = self.hits[name]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= policy.rate_limit_per_min:
            return False
        window.append(now)
        return True


# ---------------------------------------------------------------------------
# Schema validation (lightweight)
# ---------------------------------------------------------------------------

def validate_args(schema: Dict[str, Any], args: Dict[str, Any]) -> Optional[str]:
    """Return error string if invalid, else None. Minimal JSON Schema subset."""
    if not isinstance(args, dict):
        return "arguments must be an object"
    if not schema:
        return None
    if schema.get("type") and schema["type"] != "object":
        return None
    props = schema.get("properties") or {}
    required = schema.get("required") or []
    for key in required:
        if key not in args:
            return f"missing required property: {key}"
    for key, val in args.items():
        if key not in props:
            continue  # allow additional by default
        expected = props[key].get("type")
        if not expected:
            continue
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        py = type_map.get(expected)
        # bool is a subclass of int in Python, but it is not a JSON number.
        if expected in ("integer", "number") and isinstance(val, bool):
            return f"{key} must be {expected}"
        if py and not isinstance(val, py):
            # coerce number from int
            if expected == "number" and isinstance(val, (int, float)):
                continue
            if expected == "integer" and isinstance(val, bool):
                return f"{key} must be integer"
            if expected == "integer" and isinstance(val, int):
                continue
            return f"{key} must be {expected}"
        if expected == "array" and "items" in props[key]:
            item_type = props[key]["items"].get("type")
            if item_type == "string":
                for i, item in enumerate(val):
                    if not isinstance(item, str):
                        return f"{key}[{i}] must be string"
        if "enum" in props[key] and val not in props[key]["enum"]:
            return f"{key} must be one of {props[key]['enum']}"
    return None


def truncate_result(content: Dict[str, Any], max_chars: int) -> Dict[str, Any]:
    raw = json.dumps(content, default=str)
    if len(raw) <= max_chars:
        return content
    return {
        "_truncated": True,
        "_original_chars": len(raw),
        "preview": raw[: max_chars - 80],
    }


# ---------------------------------------------------------------------------
# Approval gate
# ---------------------------------------------------------------------------

# In-memory pending approvals (replace with Redis in production)
PENDING_APPROVALS: Dict[str, Dict[str, Any]] = {}
AUTO_APPROVE = False  # set True to skip gates (dev)


APPROVAL_TTL_SECONDS = 600
MAX_PENDING_APPROVALS = 1024


def _approval_signature(call: ToolCall) -> str:
    payload = json.dumps([call.name, call.arguments], sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def request_approval(call: ToolCall, trace: ToolTrace) -> bool:
    """Bind approvals to one exact tool/arguments pair; consume only once."""
    if AUTO_APPROVE:
        return True  # Testing-only bypass; never enable in production.

    now = time.time()
    signature = _approval_signature(call)
    entry = PENDING_APPROVALS.get(call.id)
    if entry and now - entry.get("created_at", 0) > APPROVAL_TTL_SECONDS:
        PENDING_APPROVALS.pop(call.id, None)
        entry = None
    if entry:
        if entry.get("signature") != signature:
            trace.event("approval_mismatch", tool=call.name, call_id=call.id)
            return False
        if entry.get("status") == "approved":
            PENDING_APPROVALS.pop(call.id, None)
            trace.event("approval_consumed", tool=call.name, call_id=call.id)
            return True
        return False

    # Eviction fails closed instead of growing a global unbounded queue.
    if len(PENDING_APPROVALS) >= MAX_PENDING_APPROVALS:
        oldest = min(PENDING_APPROVALS, key=lambda k: PENDING_APPROVALS[k].get("created_at", 0))
        PENDING_APPROVALS.pop(oldest, None)
    PENDING_APPROVALS[call.id] = {
        "status": "pending",
        "tool": call.name,
        "arguments": call.arguments,
        "signature": signature,
        "trace_id": trace.trace_id,
        "created_at": now,
    }
    trace.event("approval_requested", tool=call.name, call_id=call.id)
    return False

# ---------------------------------------------------------------------------
# Advanced executor
# ---------------------------------------------------------------------------

class AdvancedToolRuntime:
    def __init__(
        self,
        registry: ToolRegistry = None,
        policies: Dict[str, ToolPolicy] = None,
        middleware: Middleware = None,
    ):
        self.registry = registry or REGISTRY
        self.policies = policies or dict(DEFAULT_POLICIES)
        self.middleware = middleware or Middleware()
        self.circuits = BREAKERS
        # Apply ToolPolicy circuit thresholds into breaker registry
        for tname, pol in self.policies.items():
            self.circuits.configure(
                tname,
                failure_threshold=pol.circuit_fail_threshold,
                cooldown_sec=pol.circuit_cooldown_sec,
                window_sec=60.0,
                success_threshold=2,
                half_open_max_probes=2,
            )
        self.rates = RateLimiter()
        self.bulkheads = BULKHEADS
        self._semaphores: Dict[str, asyncio.Semaphore] = {}

    def policy_for(self, name: str) -> ToolPolicy:
        return self.policies.get(name, ToolPolicy())

    def _sem(self, name: str, policy: ToolPolicy) -> asyncio.Semaphore:
        if name not in self._semaphores:
            self._semaphores[name] = asyncio.Semaphore(policy.max_concurrency)
        return self._semaphores[name]

    async def execute_one(self, call: ToolCall, trace: ToolTrace) -> ToolResult:
        trace.event("tool_start", tool=call.name, call_id=call.id)
        # Unknown names must be rejected before creating per-name circuit,
        # bulkhead, semaphore or rate-limit state.
        spec = self.registry._tools.get(call.name)
        if not spec:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content={},
                success=False,
                error=f"unknown tool: {call.name}",
            )
        policy = self.policy_for(call.name)

        # Circuit
        if not await self.circuits.allow(call.name):
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content={},
                success=False,
                error=f"circuit open for {call.name}",
            )

        # Bulkhead capacity
        bh = self.bulkheads.get(call.name)
        got_slot = await bh.acquire()
        if not got_slot:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content={},
                success=False,
                error=f"bulkhead full for {call.name}",
            )

        # Acquire succeeded: all paths (including denial, timeout, cancellation)
        # must release this exact bulkhead slot.
        try:
            # Rate limit
            if not self.rates.allow(call.name, policy):
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content={},
                    success=False,
                    error=f"rate limit exceeded for {call.name}",
                )

            # Schema validation
            verr = validate_args(spec.parameters or {}, call.arguments)
            if verr:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content={},
                    success=False,
                    error=f"schema validation: {verr}",
                )

            # Before hooks
            for hook in self.middleware.before:
                denial = await hook(call, trace)
                if denial:
                    return ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        content={},
                        success=False,
                        error=f"denied by middleware: {denial}",
                    )

            # Approval gate
            if policy.requires_approval:
                approved = await request_approval(call, trace)
                if not approved:
                    return ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        content={
                            "status": "pending_approval",
                            "call_id": call.id,
                            "hint": "POST /v1/tools/approve {\"call_id\": \"...\", \"approve\": true}",
                        },
                        success=False,
                        error="pending_approval",
                    )

            # Execute with retries + timeout + concurrency limit
            last_err: Optional[Exception] = None
            async with self._sem(call.name, policy):
                for attempt in range(policy.max_retries + 1):
                    try:
                        result_content = await asyncio.wait_for(
                            spec.handler(call.arguments),
                            timeout=policy.timeout_sec,
                        )
                        result = ToolResult(
                            tool_call_id=call.id,
                            name=call.name,
                            content=truncate_result(
                                result_content if isinstance(result_content, dict) else {"result": result_content},
                                policy.max_result_chars,
                            ),
                            success=True,
                        )
                        await self.circuits.record_success(call.name)
                        for hook in self.middleware.after:
                            result = await hook(call, result, trace)
                        trace.event(
                            "tool_ok",
                            tool=call.name,
                            call_id=call.id,
                            attempt=attempt,
                        )
                        return result
                    except Exception as e:
                        last_err = e
                        await self.circuits.record_failure(call.name)
                        for hook in self.middleware.on_error:
                            await hook(call, e, trace)
                        trace.event(
                            "tool_error",
                            tool=call.name,
                            call_id=call.id,
                            attempt=attempt,
                            error=str(e),
                        )
                        if attempt < policy.max_retries:
                            await asyncio.sleep(policy.retry_backoff_sec * (attempt + 1))

            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content={},
                success=False,
                error=str(last_err) if last_err else "unknown error",
            )
        finally:
            await bh.release()

    async def execute_parallel(
        self,
        calls: List[ToolCall],
        trace: Optional[ToolTrace] = None,
        tool_choice: Optional[ToolChoice] = None,
    ) -> List[ToolResult]:
        """
        Execute many tool calls concurrently (respecting per-tool semaphores).
        Applies ToolChoice filters first.
        """
        trace = trace or ToolTrace(trace_id=new_trace_id())
        tool_choice = tool_choice or ToolChoice()

        if tool_choice.mode == ToolChoiceMode.NONE:
            trace.event("tool_choice_none")
            return []

        filtered = calls
        if tool_choice.force_tool:
            filtered = [c for c in calls if c.name == tool_choice.force_tool]
            if not filtered and tool_choice.mode == ToolChoiceMode.REQUIRED:
                return [ToolResult(
                    tool_call_id="forced",
                    name=tool_choice.force_tool,
                    content={},
                    success=False,
                    error="forced tool not present in tool_calls",
                )]
        if tool_choice.mode == ToolChoiceMode.REQUIRED and not filtered:
            return [ToolResult(
                tool_call_id="required",
                name="*",
                content={},
                success=False,
                error="tool_choice=required but no tool_calls provided",
            )]

        trace.event("parallel_batch", count=len(filtered), tools=[c.name for c in filtered])
        results = await asyncio.gather(
            *[self.execute_one(c, trace) for c in filtered],
            return_exceptions=False,
        )
        return list(results)

    async def execute_dag(
        self,
        plan: List[Dict[str, Any]],
        trace: Optional[ToolTrace] = None,
    ) -> List[ToolResult]:
        """
        Execute a compositional tool plan with depends_on.

        plan item:
          {
            "id": "1",
            "tool": "research",
            "arguments": {...},
            "depends_on": []          # list of plan ids
          }
        """
        trace = trace or ToolTrace(trace_id=new_trace_id())
        done: Dict[str, ToolResult] = {}
        remaining = {p["id"]: p for p in plan}
        results: List[ToolResult] = []

        while remaining:
            ready = [
                p for p in remaining.values()
                if all(dep in done for dep in p.get("depends_on") or [])
            ]
            if not ready:
                # cyclic / broken deps
                for p in remaining.values():
                    results.append(ToolResult(
                        tool_call_id=p["id"],
                        name=p.get("tool", "?"),
                        content={},
                        success=False,
                        error="unresolved depends_on (cycle or missing)",
                    ))
                break

            # Never run dependents after a failed prerequisite. Independent
            # ready nodes still run; blocked nodes propagate failure downstream.
            runnable = []
            for p in ready:
                failed_deps = [
                    dep for dep in p.get("depends_on") or []
                    if not done[dep].success
                ]
                if failed_deps:
                    res = ToolResult(
                        tool_call_id=p["id"],
                        name=p["tool"],
                        content={},
                        success=False,
                        error="dependency failed: " + ", ".join(failed_deps),
                    )
                    done[p["id"]] = res
                    results.append(res)
                    del remaining[p["id"]]
                else:
                    runnable.append(p)

            if runnable:
                calls = [
                    ToolCall(
                        id=p["id"],
                        name=p["tool"],
                        arguments=p.get("arguments") or {},
                    )
                    for p in runnable
                ]
                batch = await self.execute_parallel(calls, trace=trace)
                for p, res in zip(runnable, batch):
                    done[p["id"]] = res
                    results.append(res)
                    del remaining[p["id"]]

        return results


# Default advanced runtime
ADVANCED = AdvancedToolRuntime()


# ---------------------------------------------------------------------------
# Advanced multi-round loop (protocol v2)
# ---------------------------------------------------------------------------

async def run_advanced_tool_loop(
    user_message: str,
    history: List[Dict[str, Any]] = None,
    mood: str = "",
    max_rounds: int = 5,
    tool_choice: Optional[ToolChoice] = None,
    runtime: Optional[AdvancedToolRuntime] = None,
) -> Dict[str, Any]:
    """
    Same outer loop as v1, but every tool batch runs through AdvancedToolRuntime
    (parallel, validated, rate-limited, traced, optionally approval-gated).
    """
    from reasoner import call_llm_with_tools, local_reason

    runtime = runtime or ADVANCED
    tool_choice = tool_choice or ToolChoice()
    history = history or []
    trace = ToolTrace(trace_id=new_trace_id())
    trace.event("loop_start", message=user_message[:200], mood=mood)

    messages: List[Dict[str, Any]] = []
    for h in history[-12:]:
        msg = {"role": h.get("role", "user"), "content": h.get("content")}
        if h.get("tool_calls"):
            msg["tool_calls"] = h["tool_calls"]
        if h.get("tool_call_id"):
            msg["tool_call_id"] = h["tool_call_id"]
            msg["name"] = h.get("name")
        messages.append(msg)
    messages.append({"role": "user", "content": user_message})

    tool_trace: List[Dict[str, Any]] = []
    source = "local_reasoner"
    final_content = ""
    round_i = 0

    for round_i in range(max_rounds):
        assistant_msg = await call_llm_with_tools(messages, mood_override=mood, use_tools=True)
        if assistant_msg:
            source = "custom_llm"
        else:
            if round_i == 0:
                assistant_msg = local_reason(user_message, history)
                source = assistant_msg.pop("source", "local_reasoner")
            else:
                final_content = "Advanced tool protocol complete.\n" + "\n".join(
                    f"- {t['name']} [{'ok' if t['success'] else 'fail'}]: {t.get('preview', '')[:200]}"
                    for t in tool_trace
                )
                break

        calls = parse_tool_calls_from_message(assistant_msg)
        if not calls:
            final_content = assistant_msg.get("content") or ""
            messages.append({"role": "assistant", "content": final_content})
            break

        messages.append({
            "role": "assistant",
            "content": assistant_msg.get("content"),
            "tool_calls": [c.to_openai() for c in calls],
        })

        results = await runtime.execute_parallel(calls, trace=trace, tool_choice=tool_choice)
        for call, result in zip(calls, results):
            preview = (
                json.dumps(result.content, default=str)[:240]
                if result.success
                else (result.error or "error")
            )
            tool_trace.append({
                "name": call.name,
                "args": call.arguments,
                "success": result.success,
                "preview": preview,
                "call_id": call.id,
            })
        messages.extend(tool_results_to_messages(results))
    else:
        final_content = final_content or "Reached max advanced tool rounds."

    if not final_content and tool_trace:
        final_content = "Completed advanced tool calls:\n" + "\n".join(
            f"• {t['name']}: {t['preview'][:180]}" for t in tool_trace
        )

    trace.event("loop_end", rounds=round_i + 1, tools=[t["name"] for t in tool_trace])

    return {
        "reply": final_content,
        "source": source,
        "rounds": round_i + 1,
        "tool_trace": tool_trace,
        "messages": messages,
        "tools_available": runtime.registry.names(),
        "trace": trace.to_dict(),
        "protocol": "tool_calling_v2_advanced",
    }
