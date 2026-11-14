"""
ChatBot Interface — CycleKernel Master v4.1
Conversational front-door with formal tool-calling protocol.
"""

from __future__ import annotations
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import httpx
import logging
import os
from datetime import datetime

from reasoner import reason, run_tool_loop
from tools import REGISTRY, ToolCall, execute_tool_calls
from circuit_breaker import BREAKERS, CircuitState
from bulkhead import BULKHEADS
from tools_advanced import (
    ADVANCED, ToolChoice, ToolChoiceMode, run_advanced_tool_loop,
    PENDING_APPROVALS, AUTO_APPROVE,
)
from scraper import scrape_and_analyze

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ck.chat")

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://cognitive-bridge:8090")
ORCH_URL = os.getenv("ORCH_URL", "http://orchestrator:8100")

app = FastAPI(
    title="CycleKernel ChatBot",
    version="4.1.0",
    description="Tool-calling conversational interface for the Ghost Colony",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

import sys
from pathlib import Path
AGENT_SRC = str(Path(__file__).resolve().parents[1])
if AGENT_SRC not in sys.path:
    sys.path.insert(0, AGENT_SRC)

SESSIONS: Dict[str, List[Dict]] = {}


class ChatMessage(BaseModel):
    role: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"
    history: List[ChatMessage] = Field(default_factory=list)
    auto_spawn: bool = True
    use_tool_protocol: bool = True
    max_rounds: int = 5
    protocol_version: str = "v2"  # v1 | v2
    tool_choice: str = "auto"  # auto | required | none


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    mood: str
    decision: Dict[str, Any]
    agent_result: Optional[Dict[str, Any]] = None
    tool_trace: Optional[List[Dict[str, Any]]] = None
    protocol: str = "tool_calling_v1"
    timestamp: str


async def get_mood() -> Dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{BRIDGE_URL}/v1/current_mood")
            return r.json()
    except Exception:
        return {"mood": "neutral", "traits": [], "system_prompt_override": ""}


def _parse_tool_calls(payload: Any) -> List[ToolCall]:
    """Validate an OpenAI-style tool_calls array; raise 422 instead of 500 on bad shapes."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="body must be a JSON object")
    raw_calls = payload.get("tool_calls", [])
    if not isinstance(raw_calls, list):
        raise HTTPException(status_code=422, detail="tool_calls must be an array")
    if len(raw_calls) > 100:
        raise HTTPException(status_code=422, detail="at most 100 tool_calls per request")
    if not all(isinstance(c, dict) for c in raw_calls):
        raise HTTPException(status_code=422, detail="each tool_call must be an object")
    for call in raw_calls:
        fn = call.get("function")
        if not isinstance(fn, dict):
            raise HTTPException(status_code=422, detail="tool_call.function must be an object")
        if ("id" in call and not isinstance(call["id"], str)
                or "type" in call and call["type"] != "function"
                or "name" in fn and not isinstance(fn["name"], str)
                or "name" in call and not isinstance(call["name"], str)
                or "arguments" in fn and not isinstance(fn["arguments"], (str, dict))):
            raise HTTPException(status_code=422, detail="invalid tool_call fields")
    return [ToolCall.from_openai(c) for c in raw_calls]


@app.get("/health")
async def health():
    mood = await get_mood()
    return {
        "status": "chat-online",
        "version": "4.1.0",
        "mood": mood.get("mood"),
        "llm_configured": bool(os.getenv("LLM_BASE_URL")),
        "tools": REGISTRY.names(),
        "protocol": "tool_calling_v1",
    }


@app.get("/v1/tools")
async def list_tools():
    """Return OpenAI-compatible tool schemas (the protocol surface)."""
    return {
        "protocol": "openai.chat.completions.tools",
        "tools": REGISTRY.list_schemas(),
    }


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    mood_data = await get_mood()
    mood = mood_data.get("mood", "neutral")

    hist = SESSIONS.get(req.session_id, [])
    if req.history:
        hist = [h.model_dump(exclude_none=True) for h in req.history]
    hist.append({"role": "user", "content": req.message})

    agent_result = None
    tool_trace = None
    decision: Dict[str, Any] = {}

    if req.auto_spawn and req.use_tool_protocol:
        choice = ToolChoice(
            mode=ToolChoiceMode(req.tool_choice) if req.tool_choice in ("auto", "required", "none") else ToolChoiceMode.AUTO
        )
        if req.protocol_version == "v2":
            loop_out = await run_advanced_tool_loop(
                req.message,
                history=hist[:-1],
                mood=mood,
                max_rounds=req.max_rounds,
                tool_choice=choice,
            )
        else:
            loop_out = await run_tool_loop(
                req.message,
                history=hist[:-1],
                mood=mood,
                max_rounds=req.max_rounds,
            )
        reply = loop_out["reply"]
        tool_trace = loop_out.get("tool_trace") or []
        decision = {
            "source": loop_out.get("source"),
            "rounds": loop_out.get("rounds"),
            "tools_available": loop_out.get("tools_available"),
            "tool_calls_made": [t["name"] for t in tool_trace],
            "trace_id": (loop_out.get("trace") or {}).get("trace_id"),
            "protocol": loop_out.get("protocol") or req.protocol_version,
        }
        if tool_trace:
            agent_result = {"tool_trace": tool_trace, "trace": loop_out.get("trace")}
    else:
        decision = await reason(req.message, history=hist, mood=mood)
        tool = decision.get("tool")
        args = decision.get("args") or {}

        if not req.auto_spawn or not tool:
            reply = decision.get("answer") or "Acknowledged."
        else:
            call = ToolCall(id="call_legacy", name=tool, arguments=args)
            results = await execute_tool_calls([call])
            result = results[0]
            agent_result = result.content if result.success else {"error": result.error}
            tool_trace = [{
                "name": tool,
                "args": args,
                "success": result.success,
                "preview": str(agent_result)[:240],
            }]
            reply = f"[{tool} executed]\n{str(agent_result)[:2000]}"

    if mood_data.get("system_prompt_override") and tool_trace:
        reply += f"\n\n— cognitive bias active: {mood} —"

    hist.append({"role": "assistant", "content": reply})
    SESSIONS[req.session_id] = hist[-30:]

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{BRIDGE_URL}/v1/feedback", json={
                "source": "chat",
                "message": req.message,
                "tools": [t["name"] for t in (tool_trace or [])],
                "success": True,
            })
    except Exception:
        pass

    return ChatResponse(
        reply=reply,
        session_id=req.session_id,
        mood=mood,
        decision=decision,
        agent_result=agent_result,
        tool_trace=tool_trace,
        protocol="tool_calling_v1",
        timestamp=datetime.utcnow().isoformat(),
    )


@app.post("/v1/scrape")
async def scrape_endpoint(payload: Dict[str, Any]):
    urls = payload.get("urls") or []
    query = payload.get("query") or ""
    if not urls:
        return {"error": "urls list required"}
    return await scrape_and_analyze(urls, query=query)


@app.post("/v1/tools/execute")
async def execute_tools_endpoint(payload: Dict[str, Any]):
    """
    Direct protocol endpoint: accept OpenAI-style tool_calls and return tool results.
    Body: { "tool_calls": [ {id, type, function: {name, arguments}} ] }
    """
    from tools import tool_results_to_messages

    calls = _parse_tool_calls(payload)
    results = await execute_tool_calls(calls)
    return {
        "protocol": "tool_calling_v1",
        "results": [
            {
                "tool_call_id": r.tool_call_id,
                "name": r.name,
                "success": r.success,
                "content": r.content,
                "error": r.error,
            }
            for r in results
        ],
        "messages": tool_results_to_messages(results),
    }


@app.post("/v1/tools/approve")
async def approve_tool(payload: Dict[str, Any]):
    """Approve or deny a pending tool call (approval gate)."""
    call_id = payload.get("call_id")
    approve = bool(payload.get("approve", False))
    if not call_id:
        return {"error": "call_id required"}
    entry = PENDING_APPROVALS.get(call_id)
    if not entry:
        return {"error": "unknown call_id", "call_id": call_id}
    entry["status"] = "approved" if approve else "denied"
    entry["resolved_at"] = datetime.utcnow().isoformat()
    return {"call_id": call_id, "status": entry["status"]}


@app.get("/v1/tools/pending")
async def list_pending():
    return {"pending": PENDING_APPROVALS}


@app.post("/v1/tools/execute_advanced")
async def execute_advanced(payload: Dict[str, Any]):
    """
    Advanced parallel / DAG execution.
    Body:
      {
        "tool_calls": [ ... OpenAI style ... ],
        "tool_choice": "auto"|"required"|"none",
        "plan": [ {"id","tool","arguments","depends_on"} ]  # optional DAG
      }
    """
    from tools_advanced import tool_results_to_messages  # noqa — same helper from tools
    from tools import tool_results_to_messages as v1_msgs

    choice = ToolChoice(
        mode=ToolChoiceMode(payload.get("tool_choice", "auto"))
        if payload.get("tool_choice") in ("auto", "required", "none")
        else ToolChoiceMode.AUTO
    )
    plan = payload.get("plan")
    if plan is not None and (
        not isinstance(plan, list)
        or len(plan) > 100
        or not all(isinstance(step, dict) for step in plan)
    ):
        raise HTTPException(status_code=422, detail="plan must be an array of at most 100 objects")
    if plan:
        seen_ids = set()
        for step in plan:
            step_id, tool_name = step.get("id"), step.get("tool")
            args = step.get("arguments", {})
            deps = step.get("depends_on") or []
            if (not isinstance(step_id, str) or not step_id.strip()
                    or not isinstance(tool_name, str) or not tool_name.strip()
                    or not isinstance(args, dict)
                    or not isinstance(deps, list)
                    or not all(isinstance(dep, str) for dep in deps)
                    or step_id in seen_ids):
                raise HTTPException(status_code=422, detail="invalid or duplicate DAG plan fields")
            seen_ids.add(step_id)
        results = await ADVANCED.execute_dag(plan)
    else:
        calls = _parse_tool_calls(payload)
        results = await ADVANCED.execute_parallel(calls, tool_choice=choice)

    return {
        "protocol": "tool_calling_v2_advanced",
        "results": [
            {
                "tool_call_id": r.tool_call_id,
                "name": r.name,
                "success": r.success,
                "content": r.content,
                "error": r.error,
            }
            for r in results
        ],
        "messages": v1_msgs(results),
    }


@app.get("/v1/tools/policies")
async def tool_policies():
    return {
        name: {
            "timeout_sec": p.timeout_sec,
            "max_retries": p.max_retries,
            "rate_limit_per_min": p.rate_limit_per_min,
            "requires_approval": p.requires_approval,
            "max_concurrency": p.max_concurrency,
        }
        for name, p in ADVANCED.policies.items()
    }


@app.get("/v1/circuits")
async def circuit_status():
    """Snapshot of all tool circuit breakers (CLOSED / OPEN / HALF_OPEN)."""
    return {"protocol": "circuit_breaker_v1", "circuits": BREAKERS.status()}


@app.post("/v1/circuits/{tool_name}/open")
async def circuit_force_open(tool_name: str, payload: Dict[str, Any] = None):
    payload = payload or {}
    await BREAKERS.force_open(tool_name, reason=payload.get("reason", "manual"))
    return {"tool": tool_name, "action": "force_open", "status": BREAKERS.status().get(tool_name)}


@app.post("/v1/circuits/{tool_name}/close")
async def circuit_force_close(tool_name: str, payload: Dict[str, Any] = None):
    payload = payload or {}
    await BREAKERS.force_close(tool_name, reason=payload.get("reason", "manual"))
    return {"tool": tool_name, "action": "force_close", "status": BREAKERS.status().get(tool_name)}


@app.post("/v1/circuits/reset")
async def circuit_reset_all():
    await BREAKERS.reset_all()
    return {"action": "reset_all", "circuits": BREAKERS.status()}


@app.get("/v1/bulkheads")
async def bulkhead_status():
    """Capacity isolation pools per tool."""
    return {"protocol": "bulkhead_v1", "bulkheads": BULKHEADS.status()}


@app.post("/v1/bulkheads/{tool_name}/configure")
async def bulkhead_configure(tool_name: str, payload: Dict[str, Any]):
    try:
        BULKHEADS.configure(
            tool_name,
            max_concurrent=int(payload.get("max_concurrent", 4)),
            max_queue=int(payload.get("max_queue", 8)),
            acquire_timeout_sec=float(payload.get("acquire_timeout_sec", 5.0)),
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"tool": tool_name, "status": BULKHEADS.get(tool_name).snapshot()}

