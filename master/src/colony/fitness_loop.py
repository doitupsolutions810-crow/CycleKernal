"""
Live Fitness Loop
=================
Maps chat outcomes + server health + job results into hybrid GA fitness context
and optionally steps the genome on the CognitiveBridge.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

import httpx

logger = logging.getLogger("ck.fitness")


@dataclass
class OutcomeEvent:
    kind: str  # chat | job | server | tool
    success: bool
    mood: Optional[str] = None
    tools: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class LiveFitnessLoop:
    def __init__(
        self,
        bridge_url: str = "http://cognitive-bridge:8090",
        batch_size: int = 5,
        ns_weight: float = 0.55,
    ):
        self.bridge_url = bridge_url.rstrip("/")
        self.batch_size = batch_size
        self.ns_weight = ns_weight
        self.buffer: Deque[OutcomeEvent] = deque(maxlen=200)
        self.history: List[Dict[str, Any]] = []

    def record(self, event: OutcomeEvent) -> None:
        self.buffer.append(event)

    def record_chat(
        self,
        success: bool,
        mood: Optional[str] = None,
        tools: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.record(
            OutcomeEvent(
                kind="chat",
                success=success,
                mood=mood,
                tools=list(tools or []),
                meta=dict(meta or {}),
            )
        )

    def record_job(self, success: bool, job_id: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.record(
            OutcomeEvent(
                kind="job",
                success=success,
                meta={"job_id": job_id, **(meta or {})},
            )
        )

    def record_server(self, success: bool, name: str, meta: Optional[Dict[str, Any]] = None) -> None:
        self.record(
            OutcomeEvent(
                kind="server",
                success=success,
                meta={"name": name, **(meta or {})},
            )
        )

    def context_from_buffer(self, n: Optional[int] = None) -> Dict[str, Any]:
        items = list(self.buffer)[-(n or self.batch_size) :]
        if not items:
            return {
                "success_rate": 0.5,
                "tool_efficiency": 0.5,
                "mood_alignment": 0.5,
                "risk_events": 0,
                "novelty": 0.3,
                "ns_weight": self.ns_weight,
            }
        successes = sum(1 for e in items if e.success)
        n_i = len(items)
        risk = sum(1 for e in items if not e.success)
        mood_hits = sum(1 for e in items if e.mood)
        tools = [t for e in items for t in e.tools]
        return {
            "success_rate": successes / n_i,
            "tool_efficiency": successes / n_i,
            "mood_alignment": mood_hits / n_i if n_i else 0.5,
            "risk_events": risk,
            "novelty": min(1.0, len(set(tools)) / 5.0) if tools else 0.3,
            "ns_weight": self.ns_weight,
            "sample_size": n_i,
            "kinds": {k: sum(1 for e in items if e.kind == k) for k in ("chat", "job", "server", "tool")},
        }

    async def maybe_step_genome(self, force: bool = False) -> Optional[Dict[str, Any]]:
        if not force and len(self.buffer) < self.batch_size:
            return None
        ctx = self.context_from_buffer()
        # Prefer bridge closed-loop endpoint
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Push as feedback events so bridge GA can batch
                for e in list(self.buffer)[-self.batch_size :]:
                    await client.post(
                        f"{self.bridge_url}/v1/feedback",
                        json={
                            "success": e.success,
                            "mood": e.mood,
                            "tools": e.tools,
                            "kind": e.kind,
                            **e.meta,
                        },
                    )
                r = await client.post(
                    f"{self.bridge_url}/v1/genome/evolve",
                    json={"context": ctx},
                )
                if r.status_code < 400:
                    data = r.json()
                    self.history.append({"ts": datetime.utcnow().isoformat(), "ctx": ctx, "result": data})
                    return data
        except Exception as e:
            logger.warning("bridge evolve failed, local fallback: %s", e)

        # Local hybrid fitness step
        try:
            from evolution.genome import GenePool
            from evolution.genetic import GeneticAlgorithm
            from evolution.ns_fitness import hybrid_fitness

            pool = GenePool(size=8)
            ga = GeneticAlgorithm(pool, fitness_fn=hybrid_fitness)
            summary = ga.step(ctx)
            best = pool.best()
            data = {"ga": summary, "active": best.to_dict(), "local": True}
            self.history.append({"ts": datetime.utcnow().isoformat(), "ctx": ctx, "result": data})
            return data
        except Exception as e:
            logger.warning("local fitness step failed: %s", e)
            return {"error": str(e), "context": ctx}

    def snapshot(self) -> Dict[str, Any]:
        return {
            "buffer_size": len(self.buffer),
            "batch_size": self.batch_size,
            "context": self.context_from_buffer(),
            "history_len": len(self.history),
            "last": self.history[-1] if self.history else None,
        }
