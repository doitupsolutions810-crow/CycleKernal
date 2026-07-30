"""
Base Sub-Agent — every specialist inherits cognitive awareness.
"""

from __future__ import annotations
import httpx
from typing import Any, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger("ck.agent")


@dataclass
class AgentResult:
    agent: str
    success: bool
    output: Any
    mood_at_start: str = "neutral"
    traits_used: list = field(default_factory=list)
    duration_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class BaseAgent:
    name: str = "base"
    role: str = "generic"

    def __init__(self, bridge_url: str = "http://cognitive-bridge:8090"):
        self.bridge_url = bridge_url.rstrip("/")

    async def current_mood(self) -> Dict:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.bridge_url}/v1/current_mood")
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.warning(f"{self.name}: mood fetch failed — {e}")
            return {"mood": "neutral", "traits": [], "system_prompt_override": ""}

    async def run(self, task: Dict) -> AgentResult:
        raise NotImplementedError

    def _wrap(self, success: bool, output: Any, mood: Dict, started: datetime) -> AgentResult:
        elapsed = int((datetime.utcnow() - started).total_seconds() * 1000)
        return AgentResult(
            agent=self.name,
            success=success,
            output=output,
            mood_at_start=mood.get("mood", "neutral"),
            traits_used=mood.get("traits", []),
            duration_ms=elapsed,
        )
