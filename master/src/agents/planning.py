"""
Planning Sub-Agent
Produces ordered task graphs that the orchestrator can execute.
"""

from .base import BaseAgent, AgentResult
from datetime import datetime
from typing import Dict, List
import logging

logger = logging.getLogger("ck.planning")


class PlanningAgent(BaseAgent):
    name = "planning"
    role = "task decomposition & sequencing"

    async def run(self, task: Dict) -> AgentResult:
        started = datetime.utcnow()
        mood = await self.current_mood()
        goal = task.get("goal") or "unspecified goal"

        traits = set(mood.get("traits", []))

        steps: List[Dict] = [
            {"id": 1, "agent": "research", "action": "gather context", "input": {"query": goal}},
            {"id": 2, "agent": "planning", "action": "refine plan", "depends_on": [1]},
            {"id": 3, "agent": "coding", "action": "emit artifact", "depends_on": [2]},
            {"id": 4, "agent": "orchestrator", "action": "execute in sandbox", "depends_on": [3]},
        ]

        if "Creative/Divergent" in traits:
            steps.insert(2, {
                "id": 2.5,
                "agent": "research",
                "action": "explore alternative approaches",
                "depends_on": [1],
                "optional": True,
            })

        if "Survival/Conservation" in traits:
            steps = [s for s in steps if not s.get("optional")]
            for s in steps:
                s["safety"] = "high"

        plan = {
            "goal": goal,
            "steps": steps,
            "estimated_agents": list({s["agent"] for s in steps}),
            "cognitive_bias": mood.get("mood"),
        }

        logger.info(f"Plan generated: {len(steps)} steps under mood={mood.get('mood')}")
        return self._wrap(True, plan, mood, started)
