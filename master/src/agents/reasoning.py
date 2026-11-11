"""
Reasoning Sub-Agent
===================
Neuro-symbolic + mood-aware multi-step reasoning.
Produces structured plans, constraints, and decision traces.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List

from .base import AgentResult, BaseAgent

logger = logging.getLogger("ck.reasoning")


class ReasoningAgent(BaseAgent):
    name = "reasoning"
    role = "multi-step reasoning, constraint analysis, decision traces"

    async def run(self, task: Dict[str, Any]) -> AgentResult:
        started = datetime.utcnow()
        mood = await self.current_mood()
        goal: str = task.get("goal") or task.get("query") or task.get("problem") or ""
        context: Dict[str, Any] = dict(task.get("context") or {})
        max_steps: int = int(task.get("max_steps", 5))

        traits: List[str] = list(mood.get("traits") or [])
        divergent = any("Divergent" in t or "Creative" in t for t in traits)
        convergent = any("Convergent" in t or "Analytical" in t for t in traits)
        survival = any("Survival" in t for t in traits)

        steps: List[Dict[str, Any]] = []
        # Step 1: frame
        steps.append({
            "id": 1,
            "kind": "frame",
            "content": f"Problem frame: {goal[:240]}",
            "bias": mood.get("mood", "neutral"),
        })
        # Step 2: constraints
        constraints = list(context.get("constraints") or [])
        if survival and "prefer_safe_tools" not in constraints:
            constraints.append("prefer_safe_tools")
        if convergent and "require_evidence" not in constraints:
            constraints.append("require_evidence")
        steps.append({
            "id": 2,
            "kind": "constraints",
            "content": constraints or ["no explicit constraints"],
        })
        # Step 3: hypotheses
        hypotheses = []
        if divergent:
            hypotheses.append("Explore alternate formulations before committing")
        hypotheses.append("Decompose into research → plan → implement → verify")
        if survival:
            hypotheses.append("Minimize irreversible side effects; prefer sandbox")
        steps.append({"id": 3, "kind": "hypotheses", "content": hypotheses[:max_steps]})
        # Step 4: recommended agent chain
        chain = ["reasoning"]
        g = goal.lower()
        if any(k in g for k in ("research", "what", "why", "http://", "https://")):
            chain.append("research")
        if any(k in g for k in ("code", "implement", "function", "script")):
            chain.append("coding")
        if any(k in g for k in ("artifact", "file", "package", "zip")):
            chain.append("artifact")
        if any(k in g for k in ("container", "docker", "image")):
            chain.append("container")
        if any(k in g for k in ("server", "host", "serve", "uvicorn", "http")):
            chain.append("server")
        if len(chain) == 1:
            chain.extend(["coding", "artifact"])
        steps.append({"id": 4, "kind": "agent_chain", "content": chain})
        # Step 5: decision
        decision = {
            "strategy": "sandbox-first" if survival else ("explore-then-converge" if divergent else "converge"),
            "next_agent": chain[1] if len(chain) > 1 else "coding",
            "chain": chain,
            "stop_conditions": ["artifact_verified", "server_health_ok", "budget_exhausted"],
        }
        steps.append({"id": 5, "kind": "decision", "content": decision})

        output = {
            "goal": goal,
            "steps": steps[:max_steps],
            "decision": decision,
            "constraints": constraints,
            "cognitive_context": {
                "mood": mood.get("mood"),
                "traits": traits,
                "override": (mood.get("system_prompt_override") or "")[:240],
            },
        }
        logger.info("Reasoning complete next=%s chain=%s", decision["next_agent"], chain)
        return self._wrap(True, output, mood, started)
