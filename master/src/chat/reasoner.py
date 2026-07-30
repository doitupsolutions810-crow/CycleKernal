"""
Codex-style Reasoner — decides whether to answer directly or spawn sub-agents.
Supports OpenAI-compatible custom LLMs; falls back to deterministic local reasoning.
"""

from __future__ import annotations
import httpx
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ck.reasoner")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT = """You are CycleKernel Colony, a reasoning AI that can either answer directly
or spawn specialized sub-agents to solve complex criteria.

Available tools (sub-agents):
1. research — web scrape + synthesize evidence. Args: query (str), urls (optional list)
2. planning — decompose a goal into ordered steps. Args: goal (str)
3. coding — generate executable code artifact. Args: goal (str), language (str, default python)
4. pipeline — run the full research→plan→code→execute loop. Args: goal (str)

When the user asks something that needs external facts, code, or multi-step work,
respond with a JSON tool call:
{"tool": "<name>", "args": {...}, "reason": "<why>"}

When you can answer directly from conversation context, respond with:
{"tool": null, "answer": "<your reply>", "reason": "direct"}

Always return valid JSON only.
"""


async def call_llm(messages: List[Dict[str, str]], mood_override: str = "") -> str:
    if not LLM_BASE_URL:
        return ""
    headers = {"Content-Type": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    sys = SYSTEM_PROMPT
    if mood_override:
        sys += f"\n\nCurrent cognitive mood: {mood_override}. Adapt tone accordingly."
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": sys}] + messages,
        "temperature": 0.3,
        "max_tokens": 1200,
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(f"{LLM_BASE_URL}/v1/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"LLM call failed: {e}")
        return ""


def local_reason(user_message: str, history: List[Dict] = None) -> Dict[str, Any]:
    msg = user_message.lower().strip()
    history = history or []
    if any(k in msg for k in ["build", "implement", "create a", "write a program", "full pipeline", "solve this"]):
        return {"tool": "pipeline", "args": {"goal": user_message}, "reason": "Goal requires multi-step research + planning + coding + execution"}
    if any(k in msg for k in ["write code", "python function", "script", "implement function", "generate code"]):
        return {"tool": "coding", "args": {"goal": user_message, "language": "python"}, "reason": "User requested code generation"}
    urls = re.findall(r"https?://[^\s]+", user_message)
    if urls or any(k in msg for k in ["research", "scrape", "look up", "search for", "what is", "analyze website"]):
        args: Dict[str, Any] = {"query": user_message}
        if urls:
            args["urls"] = urls
        return {"tool": "research", "args": args, "reason": "User requested research or provided URLs to analyze"}
    if any(k in msg for k in ["plan", "break down", "steps to", "how should we"]):
        return {"tool": "planning", "args": {"goal": user_message}, "reason": "User requested a plan / decomposition"}
    return {
        "tool": None,
        "answer": (
            f"Understood. You said: “{user_message}”.\n\n"
            "I can research (including web scrape), plan multi-step work, write code, "
            "or run the full colony pipeline. Tell me a goal, paste a URL to analyze, "
            "or ask me to build something."
        ),
        "reason": "direct conversational response",
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


async def reason(user_message: str, history: List[Dict] = None, mood: str = "") -> Dict[str, Any]:
    history = history or []
    messages = []
    for h in history[-8:]:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": user_message})
    llm_raw = await call_llm(messages, mood_override=mood)
    if llm_raw:
        decision = parse_tool_response(llm_raw)
        decision["source"] = "custom_llm"
        return decision
    decision = local_reason(user_message, history)
    decision["source"] = "local_reasoner"
    return decision
