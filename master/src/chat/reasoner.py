"""
Codex-style Reasoner + Tool Calling Protocol client
===================================================
- Emits OpenAI-compatible `tools` schemas
- Requests tool_calls from custom LLM when configured
- Falls back to local deterministic tool selection
- Drives multi-round tool loop via run_tool_loop()
"""

from __future__ import annotations
import httpx
import json
import logging
import os
import re
import uuid
from typing import Any, Dict, List, Optional

from tools import (
    REGISTRY,
    ToolCall,
    execute_tool_calls,
    parse_tool_calls_from_message,
    tool_results_to_messages,
)

logger = logging.getLogger("ck.reasoner")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "5"))

SYSTEM_PROMPT = """You are CycleKernel Colony, a reasoning AI with tool-calling capabilities.

You may call tools to research (including web scrape), plan, write code, run the full
pipeline, inspect cognitive mood, or execute code in the sandbox.

Rules:
- When external facts, code, or multi-step work are needed, emit tool_calls.
- When you have enough information, respond with a normal assistant message (no tool_calls).
- Prefer research+scrape when URLs are present.
- Prefer pipeline for "build/implement/create" goals.
- Keep final answers concise and actionable.
- Respect the current cognitive mood if provided.
"""


def llm_completions_url() -> str:
    """OpenAI-compatible completions endpoint, or "" when no LLM is configured."""
    if not LLM_BASE_URL:
        return ""
    return f"{LLM_BASE_URL}/v1/chat/completions"


async def call_llm(messages: List[Dict[str, str]], mood_override: str = "") -> str:
    """Single-shot completion returning raw assistant text ("" on any failure or no config)."""
    message = await call_llm_with_tools(messages, mood_override=mood_override, use_tools=False)
    return (message or {}).get("content") or ""


async def call_llm_with_tools(
    messages: List[Dict[str, Any]],
    mood_override: str = "",
    use_tools: bool = True,
) -> Dict[str, Any]:
    if not LLM_BASE_URL:
        return {}

    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"

    sys = SYSTEM_PROMPT
    if mood_override:
        sys += f"\n\nCurrent cognitive mood: {mood_override}. Adapt tone and risk posture accordingly."

    payload: Dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": sys}] + messages,
        "temperature": 0.3,
        "max_tokens": 1600,
    }
    if use_tools:
        payload["tools"] = REGISTRY.list_schemas()
        payload["tool_choice"] = "auto"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(llm_completions_url(), json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]
    except Exception as e:
        logger.warning(f"LLM tool-call request failed: {e}")
        return {}


def local_reason(user_message: str, history: List[Dict] = None) -> Dict[str, Any]:
    msg = user_message.lower().strip()
    history = history or []

    def _call(name: str, args: Dict) -> Dict[str, Any]:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }],
            "source": "local_reasoner",
        }

    if any(k in msg for k in ["build", "implement", "create a", "write a program", "full pipeline", "solve this"]):
        return _call("pipeline", {"goal": user_message})

    if any(k in msg for k in ["write code", "python function", "script", "implement function", "generate code"]):
        return _call("coding", {"goal": user_message, "language": "python"})

    urls = re.findall(r"https?://[^\s]+", user_message)
    if urls or any(k in msg for k in ["research", "scrape", "look up", "search for", "analyze website", "analyze url"]):
        args: Dict[str, Any] = {"query": user_message}
        if urls:
            args["urls"] = urls
            if any(k in msg for k in ["scrape", "fetch", "analyze"]):
                return _call("scrape", {"urls": urls, "query": user_message})
        return _call("research", args)

    if any(k in msg for k in ["plan", "break down", "steps to", "how should we"]):
        return _call("planning", {"goal": user_message})

    if any(k in msg for k in ["mood", "how are you feeling", "cognitive state"]):
        return _call("get_mood", {})

    return {
        "role": "assistant",
        "content": (
            f"Understood. You said: \"{user_message}\".\n\n"
            "I can research (web scrape), plan, write & run code, or run the full colony pipeline. "
            "Paste a URL, ask me to build something, or request a plan."
        ),
        "tool_calls": [],
        "source": "local_reasoner",
    }


def parse_tool_response(raw: str) -> Dict[str, Any]:
    raw = raw.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m:
        raw = m.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        raw = m.group(0)
    try:
        return json.loads(raw)
    except Exception:
        return {"tool": None, "answer": raw, "reason": "unparsed llm text"}


async def run_tool_loop(
    user_message: str,
    history: List[Dict[str, Any]] = None,
    mood: str = "",
    max_rounds: int = None,
) -> Dict[str, Any]:
    max_rounds = max_rounds or MAX_TOOL_ROUNDS
    history = history or []

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
                summary_bits = []
                for t in tool_trace:
                    status = "ok" if t.get("success") else "fail"
                    summary_bits.append(f"- {t['name']} [{status}]: {t.get('preview', '')[:200]}")
                final_content = "Tool protocol complete.\n" + "\n".join(summary_bits)
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

        results = await execute_tool_calls(calls)
        for call, result in zip(calls, results):
            preview = json.dumps(result.content, default=str)[:240] if result.success else (result.error or "error")
            tool_trace.append({
                "name": call.name,
                "args": call.arguments,
                "success": result.success,
                "preview": preview,
            })

        messages.extend(tool_results_to_messages(results))
    else:
        final_content = final_content or "Reached max tool rounds without a final answer."

    if not final_content and tool_trace:
        final_content = "Completed tool calls:\n" + "\n".join(
            f"• {t['name']}: {t['preview'][:180]}" for t in tool_trace
        )

    return {
        "reply": final_content,
        "source": source,
        "rounds": round_i + 1,
        "tool_trace": tool_trace,
        "messages": messages,
        "tools_available": REGISTRY.names(),
    }


async def reason(user_message: str, history: List[Dict] = None, mood: str = "") -> Dict[str, Any]:
    history = history or []
    assistant_msg = await call_llm_with_tools(
        [{"role": h.get("role", "user"), "content": h.get("content", "")} for h in history[-8:]]
        + [{"role": "user", "content": user_message}],
        mood_override=mood,
        use_tools=True,
    )
    llm_url = llm_completions_url()
    if assistant_msg:
        calls = parse_tool_calls_from_message(assistant_msg)
        if calls:
            c = calls[0]
            return {
                "tool": c.name,
                "args": c.arguments,
                "reason": "llm_tool_call",
                "source": "custom_llm",
                "llm_url": llm_url,
                "tool_calls": [c.to_openai() for c in calls],
            }
        text = (assistant_msg.get("content") or "").strip()
        # Models without native tool_calls may answer with a JSON decision in the text body.
        if text.startswith("{") or text.startswith("```"):
            parsed = parse_tool_response(text)
            if isinstance(parsed, dict) and parsed.get("tool"):
                parsed.setdefault("args", {})
                parsed["source"] = "custom_llm"
                parsed["llm_url"] = llm_url
                return parsed
        return {
            "tool": None,
            "answer": text,
            "reason": "direct",
            "source": "custom_llm",
            "llm_url": llm_url,
        }

    local = local_reason(user_message, history)
    calls = parse_tool_calls_from_message(local)
    if calls:
        c = calls[0]
        return {
            "tool": c.name,
            "args": c.arguments,
            "reason": "local_tool_call",
            "source": "local_reasoner",
            "llm_url": llm_url,
            "tool_calls": [c.to_openai() for c in calls],
        }
    return {
        "tool": None,
        "answer": local.get("content") or "",
        "reason": "direct",
        "source": "local_reasoner",
        "llm_url": llm_url,
    }
