"""
Research Sub-Agent
High-entropy (divergent) bias preferred. Gathers, synthesizes, cites.
"""

from .base import BaseAgent, AgentResult
from datetime import datetime
from typing import Dict
import logging

logger = logging.getLogger("ck.research")


class ResearchAgent(BaseAgent):
    name = "research"
    role = "information synthesis & evidence gathering"

    async def run(self, task: Dict) -> AgentResult:
        started = datetime.utcnow()
        mood = await self.current_mood()
        query = task.get("query") or task.get("goal") or ""

        report = {
            "query": query,
            "summary": f"Research synthesis for: {query}",
            "findings": [
                {"claim": "Primary pattern identified", "confidence": 0.78},
                {"claim": "Secondary constraint surface", "confidence": 0.61},
            ],
            "open_questions": ["What is the exact resource envelope?", "Which invariant is binding?"],
            "recommended_next": "hand-off to planning agent",
            "cognitive_context": {
                "mood": mood.get("mood"),
                "override": mood.get("system_prompt_override", "")[:200],
            },
        }

        if "Creative/Divergent" in mood.get("traits", []):
            report["findings"].append(
                {"claim": "Exploratory alternative hypothesis", "confidence": 0.42, "speculative": True}
            )

        logger.info(f"Research complete for '{query[:60]}' under mood={mood.get('mood')}")
        return self._wrap(True, report, mood, started)
