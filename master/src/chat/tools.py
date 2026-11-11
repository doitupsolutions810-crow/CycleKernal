"""
CycleKernel Tool Calling Protocol v1
=====================================
OpenAI-compatible function/tool calling schemas + execution runtime.

Protocol flow:
  1. Model receives `tools` array (JSON Schema)
  2. Model may return `tool_calls` (parallel or sequential)
  3. Runtime executes each call via ToolRegistry
  4. Results appended as `role: tool` messages
  5. Loop until model returns a final assistant message (no tool_calls)
     or max_rounds is hit

Wire format matches OpenAI Chat Completions tool_calls:
  {
    "id": "call_xxx",
    "type": "function",
    "function": { "name": "...", "arguments": "{...json...}" }
  }
"""

from __future__ import annotations
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger("ck.tools")

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://cognitive-bridge:8090")
ORCH_URL = os.getenv("ORCH_URL", "http://orchestrator:8100")
CHAT_URL = os.getenv("CHAT_URL", "http://chat:8300")

# ---------------------------------------------------------------------------
# Tool definition (OpenAI-compatible)
# ---------------------------------------------------------------------------

ToolHandler = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema object
    handler: ToolHandler

    def openai_schema(self) -> Dict[str, Any]:
        """Emit the tools[] entry for Chat Completions."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]

    @classmethod
    def from_openai(cls, raw: Dict[str, Any]) -> "ToolCall":
        fn = raw.get("function") or {}
        args_raw = fn.get("arguments") or "{}"
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw) if args_raw.strip() else {}
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
        else:
            args = args_raw
        return cls(
            id=raw.get("id") or f"call_{uuid.uuid4().hex[:12]}",
            name=fn.get("name") or raw.get("name") or "",
            arguments=args,
        )

    def to_openai(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments),
            },
        }


@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: Dict[str, Any]
    success: bool = True
    error: Optional[str] = None

    def to_message(self) -> Dict[str, Any]:
        """OpenAI-compatible tool result message."""
        payload = self.content if self.success else {"error": self.error or "unknown"}
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": json.dumps(payload, default=str)[:12000],
        }


# ---------------------------------------------------------------------------
# Built-in tool handlers
# ---------------------------------------------------------------------------

async def _tool_research(args: Dict[str, Any]) -> Dict[str, Any]:
    from scraper import scrape_and_analyze
    import re

    query = args.get("query") or args.get("goal") or ""
    urls = list(args.get("urls") or [])
    for u in re.findall(r"https?://[^\s<>\"']+", query):
        if u not in urls:
            urls.append(u)

    scrape = None
    if urls:
        scrape = await scrape_and_analyze(urls[:5], query=query)

    return {
        "query": query,
        "urls": urls,
        "scrape": scrape,
        "findings": (
            [
                {
                    "claim": f"Fetched {scrape.get('pages_fetched', 0)} page(s)",
                    "excerpt": (scrape or {}).get("summary_excerpt", "")[:800],
                    "term_salience": (scrape or {}).get("term_salience"),
                }
            ]
            if scrape
            else [{"claim": f"Research context for: {query[:200]}", "note": "no URLs scraped"}]
        ),
    }


async def _tool_planning(args: Dict[str, Any]) -> Dict[str, Any]:
    goal = args.get("goal") or args.get("query") or ""
    return {
        "goal": goal,
        "steps": [
            {"id": 1, "agent": "research", "action": "gather evidence / scrape if URLs"},
            {"id": 2, "agent": "planning", "action": "refine approach under current mood"},
            {"id": 3, "agent": "coding", "action": "emit executable artifact"},
            {"id": 4, "agent": "terminal", "action": "sandbox execute"},
        ],
    }


async def _tool_coding(args: Dict[str, Any]) -> Dict[str, Any]:
    goal = args.get("goal") or ""
    language = args.get("language") or "python"
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            f"{ORCH_URL}/v1/run",
            json={"goal": goal, "language": language, "auto_execute": True},
        )
        if r.status_code == 200:
            return r.json()
        return {"error": r.text, "status_code": r.status_code}


async def _tool_pipeline(args: Dict[str, Any]) -> Dict[str, Any]:
    goal = args.get("goal") or ""
    async with httpx.AsyncClient(timeout=90.0) as c:
        r = await c.post(
            f"{ORCH_URL}/v1/run",
            json={"goal": goal, "auto_execute": True},
        )
        if r.status_code == 200:
            return r.json()
        return {"error": r.text, "status_code": r.status_code}


async def _tool_scrape(args: Dict[str, Any]) -> Dict[str, Any]:
    from scraper import scrape_and_analyze

    urls = args.get("urls") or []
    query = args.get("query") or ""
    if not urls:
        return {"error": "urls required"}
    return await scrape_and_analyze(urls, query=query)


async def _tool_get_mood(args: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=3.0) as c:
        r = await c.get(f"{BRIDGE_URL}/v1/current_mood")
        r.raise_for_status()
        return r.json()


async def _tool_terminal_execute(args: Dict[str, Any]) -> Dict[str, Any]:
    terminal = os.getenv("TERMINAL_URL", "http://terminal-runtime:8200")
    payload = {
        "filename": args.get("filename") or "tool_artifact.py",
        "content": args.get("content") or args.get("code") or "print('ok')\n",
        "command": args.get("command"),
        "timeout_sec": int(args.get("timeout_sec") or 15),
    }
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{terminal}/v1/execute", json=payload)
        if r.status_code == 200:
            return r.json()
        return {"error": r.text, "status_code": r.status_code}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def list_schemas(self) -> List[Dict[str, Any]]:
        return [t.openai_schema() for t in self._tools.values()]

    def names(self) -> List[str]:
        return list(self._tools.keys())

    async def execute(self, call: ToolCall) -> ToolResult:
        spec = self._tools.get(call.name)
        if not spec:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content={},
                success=False,
                error=f"unknown tool: {call.name}",
            )
        try:
            # Validate required fields lightly
            required = (spec.parameters or {}).get("required") or []
            missing = [k for k in required if k not in call.arguments]
            if missing:
                return ToolResult(
                    tool_call_id=call.id,
                    name=call.name,
                    content={},
                    success=False,
                    error=f"missing required args: {missing}",
                )
            result = await spec.handler(call.arguments)
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=result if isinstance(result, dict) else {"result": result},
                success=True,
            )
        except Exception as e:
            logger.exception(f"tool {call.name} failed")
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content={},
                success=False,
                error=str(e),
            )


async def _tool_spawn_agent(args: Dict[str, Any]) -> Dict[str, Any]:
    """Spawn one of the five sandbox sub-agents (or research/planning)."""
    import sys
    from pathlib import Path as _P
    src = str(_P(__file__).resolve().parents[1])
    if src not in sys.path:
        sys.path.insert(0, src)
    import importlib
    importlib.invalidate_caches()
    from agents.spawn import spawn
    agent = args.get("agent") or "reasoning"
    task = dict(args.get("task") or {})
    if args.get("goal") and "goal" not in task:
        task["goal"] = args["goal"]
    for k in ("name", "action", "port", "content", "filename", "language"):
        if k in args and k not in task:
            task[k] = args[k]
    result = await spawn(agent, task, bridge_url=BRIDGE_URL)
    return {
        "agent": result.agent,
        "success": result.success,
        "output": result.output,
        "mood": result.mood_at_start,
        "duration_ms": result.duration_ms,
    }


async def _tool_sandbox_pipeline(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run reasoning → coding → artifact → container → server pipeline."""
    import sys
    from pathlib import Path as _P
    src = str(_P(__file__).resolve().parents[1])
    if src not in sys.path:
        sys.path.insert(0, src)
    import importlib
    importlib.invalidate_caches()
    from agents.spawn import sandbox_pipeline
    goal = args.get("goal") or "sandbox pipeline"
    host = bool(args.get("host", True))
    port = int(args.get("port", 8765))
    return await sandbox_pipeline(goal, bridge_url=BRIDGE_URL, host=host, port=port)


def build_default_registry() -> ToolRegistry:
    reg = ToolRegistry()

    reg.register(ToolSpec(
        name="research",
        description=(
            "Research a topic and optionally scrape web pages. "
            "Use when external facts, URLs, or evidence are needed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Research question or topic"},
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of URLs to scrape and analyze",
                },
            },
            "required": ["query"],
        },
        handler=_tool_research,
    ))

    reg.register(ToolSpec(
        name="scrape",
        description="Fetch and analyze one or more web pages. Returns text, title, links, term salience.",
        parameters={
            "type": "object",
            "properties": {
                "urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "HTTP(S) URLs to fetch",
                },
                "query": {"type": "string", "description": "Optional focus query for term salience"},
            },
            "required": ["urls"],
        },
        handler=_tool_scrape,
    ))

    reg.register(ToolSpec(
        name="planning",
        description="Decompose a goal into ordered multi-agent steps.",
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Goal to decompose"},
            },
            "required": ["goal"],
        },
        handler=_tool_planning,
    ))

    reg.register(ToolSpec(
        name="coding",
        description="Generate code and optionally execute it in the sandbox via the colony pipeline.",
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "What to implement"},
                "language": {"type": "string", "enum": ["python", "javascript"], "default": "python"},
            },
            "required": ["goal"],
        },
        handler=_tool_coding,
    ))

    reg.register(ToolSpec(
        name="pipeline",
        description=(
            "Run the full colony pipeline: research → plan → code → sandbox execute. "
            "Use for multi-step build/implement goals."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "End-to-end goal"},
            },
            "required": ["goal"],
        },
        handler=_tool_pipeline,
    ))

    reg.register(ToolSpec(
        name="get_mood",
        description="Read the current CognitiveBridge mood, traits, and system prompt override.",
        parameters={"type": "object", "properties": {}},
        handler=_tool_get_mood,
    ))

    reg.register(ToolSpec(
        name="terminal_execute",
        description="Write a file into the sandbox and execute a command under timeout.",
        parameters={
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "content": {"type": "string", "description": "File contents"},
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout_sec": {"type": "integer", "default": 15},
            },
            "required": ["content"],
        },
        handler=_tool_terminal_execute,
    ))


    reg.register(ToolSpec(
        name="spawn_agent",
        description=(
            "Spawn a CycleKernel sub-agent: reasoning, coding, artifact, container, "
            "server, research, or planning. Use for sandboxed runtime workflows."
        ),
        parameters={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": ["reasoning", "coding", "artifact", "container", "server", "research", "planning"],
                },
                "goal": {"type": "string"},
                "task": {"type": "object", "description": "Agent-specific task payload"},
                "name": {"type": "string"},
                "action": {"type": "string", "description": "For server: start|stop|status"},
                "port": {"type": "integer"},
                "content": {"type": "string"},
                "filename": {"type": "string"},
                "language": {"type": "string"},
            },
            "required": ["agent"],
        },
        handler=_tool_spawn_agent,
    ))

    reg.register(ToolSpec(
        name="sandbox_pipeline",
        description=(
            "Run the five-agent sandbox pipeline: reasoning → coding → artifact → "
            "container → server. Hosts a local runtime when host=true."
        ),
        parameters={
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "host": {"type": "boolean", "default": True},
                "port": {"type": "integer", "default": 8765},
            },
            "required": ["goal"],
        },
        handler=_tool_sandbox_pipeline,
    ))

    return reg


# Global registry instance
REGISTRY = build_default_registry()


# ---------------------------------------------------------------------------
# Protocol helpers
# ---------------------------------------------------------------------------

def parse_tool_calls_from_message(message: Dict[str, Any]) -> List[ToolCall]:
    """Extract ToolCall list from an assistant message (OpenAI or local format)."""
    calls = message.get("tool_calls") or []
    if calls:
        return [ToolCall.from_openai(c) for c in calls]

    # Fallback: model returned JSON in content
    content = message.get("content") or ""
    if isinstance(content, str) and "tool" in content:
        try:
            from reasoner import parse_tool_response
            decision = parse_tool_response(content)
            if decision.get("tool"):
                return [ToolCall(
                    id=f"call_{uuid.uuid4().hex[:12]}",
                    name=decision["tool"],
                    arguments=decision.get("args") or {},
                )]
        except Exception:
            pass
    return []


async def execute_tool_calls(calls: List[ToolCall], registry: ToolRegistry = None) -> List[ToolResult]:
    registry = registry or REGISTRY
    results = []
    for call in calls:
        logger.info(f"Executing tool {call.name} id={call.id} args={call.arguments}")
        results.append(await registry.execute(call))
    return results


def tool_results_to_messages(results: List[ToolResult]) -> List[Dict[str, Any]]:
    return [r.to_message() for r in results]
