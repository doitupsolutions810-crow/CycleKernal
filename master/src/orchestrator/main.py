"""
Master Orchestrator — CycleKernel v4.0
Routes goals through research → planning → coding → terminal execution.
All decisions are mood-aware via the CognitiveBridge.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import httpx
import logging
import os
from datetime import datetime

from agents.research import ResearchAgent
from agents.coding import CodingAgent
from agents.planning import PlanningAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ck.orchestrator")

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://cognitive-bridge:8090")
TERMINAL_URL = os.getenv("TERMINAL_URL", "http://terminal-runtime:8200")
ARTIFACT_ROOT = os.getenv("ARTIFACT_ROOT", "/artifacts")

app = FastAPI(title="CycleKernel Master Orchestrator", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

research_agent = ResearchAgent(BRIDGE_URL)
coding_agent = CodingAgent(BRIDGE_URL)
planning_agent = PlanningAgent(BRIDGE_URL)


class GoalRequest(BaseModel):
    goal: str
    language: str = "python"
    filename: Optional[str] = None
    auto_execute: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    goal: str
    mood_at_start: str
    stages: List[Dict[str, Any]]
    final_artifact: Optional[Dict] = None
    execution: Optional[Dict] = None
    success: bool
    timestamp: str


@app.get("/health")
async def health():
    mood = {}
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{BRIDGE_URL}/v1/current_mood")
            mood = r.json()
    except Exception:
        mood = {"mood": "unreachable"}
    return {
        "status": "orchestrator-online",
        "version": "4.0.0",
        "bridge_mood": mood.get("mood"),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/v1/mood")
async def proxy_mood():
    async with httpx.AsyncClient(timeout=3.0) as c:
        r = await c.get(f"{BRIDGE_URL}/v1/current_mood")
        r.raise_for_status()
        return r.json()


@app.post("/v1/run", response_model=PipelineResult)
async def run_pipeline(req: GoalRequest):
    stages = []
    started_mood = {}

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            started_mood = (await c.get(f"{BRIDGE_URL}/v1/current_mood")).json()
    except Exception:
        started_mood = {"mood": "neutral", "traits": []}

    research_res = await research_agent.run({"query": req.goal, **req.context})
    stages.append({"stage": "research", **research_res.__dict__})

    plan_res = await planning_agent.run({"goal": req.goal, "research": research_res.output})
    stages.append({"stage": "planning", **plan_res.__dict__})

    filename = req.filename or f"artifact_{datetime.utcnow().strftime('%H%M%S')}.py"
    code_res = await coding_agent.run({
        "goal": req.goal,
        "language": req.language,
        "filename": filename,
        "plan": plan_res.output,
    })
    stages.append({"stage": "coding", **code_res.__dict__})

    final_artifact = code_res.output if code_res.success else None
    execution = None

    if req.auto_execute and final_artifact:
        try:
            async with httpx.AsyncClient(timeout=30.0) as c:
                exec_payload = {
                    "filename": final_artifact["filename"],
                    "content": final_artifact["content"],
                    "command": final_artifact.get("run_command"),
                }
                r = await c.post(f"{TERMINAL_URL}/v1/execute", json=exec_payload)
                execution = r.json()
                stages.append({"stage": "execution", "success": r.status_code == 200, "output": execution})
        except Exception as e:
            execution = {"error": str(e)}
            stages.append({"stage": "execution", "success": False, "output": execution})

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            await c.post(f"{BRIDGE_URL}/v1/feedback", json={
                "goal": req.goal,
                "success": code_res.success and (execution is None or not execution.get("error")),
                "stages": [s["stage"] for s in stages],
                "mood_at_start": started_mood.get("mood"),
            })
    except Exception as e:
        logger.warning(f"Feedback failed: {e}")

    success = code_res.success and (execution is None or not execution.get("error"))
    return PipelineResult(
        goal=req.goal,
        mood_at_start=started_mood.get("mood", "unknown"),
        stages=stages,
        final_artifact=final_artifact,
        execution=execution,
        success=success,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/v1/agents")
async def list_agents():
    return {
        "agents": [
            {"name": "research", "role": research_agent.role},
            {"name": "planning", "role": planning_agent.role},
            {"name": "coding", "role": coding_agent.role},
            {"name": "orchestrator", "role": "pipeline coordination + terminal dispatch"},
        ]
    }
