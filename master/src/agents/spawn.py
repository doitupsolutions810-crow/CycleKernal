"""
Sub-Agent Spawn & Orchestration
===============================
Registry + sequential/parallel spawn for the five sandbox specialists
plus existing research/planning/coding agents.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Type

from .base import AgentResult, BaseAgent
from .reasoning import ReasoningAgent
from .coding import CodingAgent
from .artifact import ArtifactAgent
from .container import ContainerAgent
from .server import ServerHostAgent

# Optional existing agents
try:
    from .research import ResearchAgent
except Exception:  # pragma: no cover
    ResearchAgent = None  # type: ignore
try:
    from .planning import PlanningAgent
except Exception:  # pragma: no cover
    PlanningAgent = None  # type: ignore

logger = logging.getLogger("ck.spawn")

AGENT_TYPES: Dict[str, Type[BaseAgent]] = {
    "reasoning": ReasoningAgent,
    "coding": CodingAgent,
    "artifact": ArtifactAgent,
    "container": ContainerAgent,
    "server": ServerHostAgent,
}
if ResearchAgent:
    AGENT_TYPES["research"] = ResearchAgent
if PlanningAgent:
    AGENT_TYPES["planning"] = PlanningAgent


def list_agents() -> List[Dict[str, str]]:
    return [
        {"name": name, "role": getattr(cls, "role", ""), "class": cls.__name__}
        for name, cls in AGENT_TYPES.items()
    ]


def get_agent(name: str, bridge_url: str = "http://cognitive-bridge:8090") -> BaseAgent:
    key = name.lower().strip()
    if key not in AGENT_TYPES:
        raise KeyError(f"unknown agent '{name}'; known={list(AGENT_TYPES)}")
    return AGENT_TYPES[key](bridge_url=bridge_url)


async def spawn(
    name: str,
    task: Dict[str, Any],
    bridge_url: str = "http://cognitive-bridge:8090",
) -> AgentResult:
    agent = get_agent(name, bridge_url=bridge_url)
    logger.info("spawn agent=%s keys=%s", name, list(task.keys()))
    return await agent.run(task)


async def spawn_many(
    steps: List[Dict[str, Any]],
    bridge_url: str = "http://cognitive-bridge:8090",
    parallel: bool = False,
    thread_context: bool = True,
) -> List[AgentResult]:
    """
    steps: [{ "agent": "reasoning", "task": {...} }, ...]
    If thread_context, each step receives previous outputs under task["_prior"].
    """
    if parallel and not thread_context:
        coros = [
            spawn(s["agent"], s.get("task") or {}, bridge_url=bridge_url)
            for s in steps
        ]
        return list(await asyncio.gather(*coros))

    results: List[AgentResult] = []
    prior: Dict[str, Any] = {}
    for s in steps:
        task = dict(s.get("task") or {})
        if thread_context and prior:
            task["_prior"] = prior
            # Convenience: bubble manifest / artifact_root
            if "manifest" in prior and "manifest" not in task:
                task["manifest"] = prior["manifest"]
            if "artifact_root" in prior and "artifact_root" not in task:
                task["artifact_root"] = prior["artifact_root"]
            if "entry" in prior and "entry" not in task:
                task["entry"] = prior["entry"]
        result = await spawn(s["agent"], task, bridge_url=bridge_url)
        results.append(result)
        if result.success and isinstance(result.output, dict):
            prior.update(result.output)
            if "manifest" in result.output:
                prior["manifest"] = result.output["manifest"]
                prior["artifact_root"] = result.output["manifest"].get("root")
                prior["entry"] = result.output["manifest"].get("entry")
    return results


async def sandbox_pipeline(
    goal: str,
    bridge_url: str = "http://cognitive-bridge:8090",
    host: bool = True,
    port: int = 8765,
) -> Dict[str, Any]:
    """
    Canonical five-agent path:
      reasoning → coding → artifact → container → server(start)
    """
    steps = [
        {"agent": "reasoning", "task": {"goal": goal}},
        {"agent": "coding", "task": {"goal": goal, "language": "python"}},
        {"agent": "artifact", "task": {"name": "pipeline", "goal": goal}},
        {"agent": "container", "task": {"name": "ck-pipeline"}},
    ]
    if host:
        steps.append({
            "agent": "server",
            "task": {"action": "start", "name": "ck-pipeline", "port": port, "mode": "static"},
        })
    results = await spawn_many(steps, bridge_url=bridge_url, thread_context=True)
    return {
        "goal": goal,
        "results": [
            {
                "agent": r.agent,
                "success": r.success,
                "duration_ms": r.duration_ms,
                "mood": r.mood_at_start,
                "output": r.output,
            }
            for r in results
        ],
    }
