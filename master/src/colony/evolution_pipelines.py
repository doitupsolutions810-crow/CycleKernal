"""
Automated Genome Evolution Pipelines
====================================
Multiple scheduled / event-driven pipelines that evolve trait genomes
without manual Promote clicks.

Pipelines:
  1. batch_feedback   — classic N-outcome hybrid fitness step
  2. multi_objective  — weighted success / safety / novelty fronts
  3. speciation       — maintain parallel genomes (ops vs research)
  4. job_lineage      — fitness from completed JobGraph outcomes
  5. periodic         — wall-clock interval evolution under baseline context
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("ck.evo_pipeline")


@dataclass
class PipelineRun:
    id: str
    pipeline: str
    started_at: str
    finished_at: Optional[str] = None
    success: bool = False
    result: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Species:
    name: str
    role: str  # ops | research | balanced
    genome: Dict[str, Any] = field(default_factory=dict)
    fitness: float = 0.0
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EvolutionPipelines:
    """
    Orchestrates automated genome evolution strategies.
    Uses local GenePool when bridge is unavailable.
    """

    def __init__(
        self,
        fitness_loop: Any = None,
        bridge_url: str = "http://cognitive-bridge:8090",
    ):
        self.fitness_loop = fitness_loop
        self.bridge_url = bridge_url.rstrip("/")
        self.history: List[PipelineRun] = []
        self.species: Dict[str, Species] = {
            "ops": Species(
                name="ops",
                role="ops",
                genome={},
            ),
            "research": Species(
                name="research",
                role="research",
                genome={},
            ),
            "balanced": Species(
                name="balanced",
                role="balanced",
                genome={},
            ),
        }
        self._last_periodic: float = 0.0
        self.periodic_interval_sec: float = 300.0

    # ----- core GA helpers -----

    def _local_evolve(
        self,
        context: Dict[str, Any],
        generations: int = 3,
        population: int = 10,
        mode: str = "hybrid",
    ) -> Dict[str, Any]:
        from evolution.genome import GenePool, TraitGenome
        from evolution.genetic import GeneticAlgorithm
        from evolution.ns_fitness import hybrid_fitness, neurosymbolic_fitness, default_fitness

        # default_fitness is in genetic
        from evolution.genetic import default_fitness as classic_fn

        fn = hybrid_fitness
        if mode == "ns":
            fn = neurosymbolic_fitness
        elif mode == "classic":
            fn = classic_fn

        pool = GenePool(size=population)
        ga = GeneticAlgorithm(pool, fitness_fn=fn)
        best = ga.run(generations=generations, context=context)
        return {
            "best": best.to_dict(),
            "summary": pool.summary(),
            "history": ga.history,
            "mode": mode,
            "local": True,
        }

    async def _bridge_evolve(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=6.0) as client:
                r = await client.post(
                    f"{self.bridge_url}/v1/genome/evolve",
                    json={"context": context},
                )
                if r.status_code < 400:
                    return r.json()
        except Exception as e:
            logger.debug("bridge evolve unavailable: %s", e)
        return None

    async def _evolve(self, context: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        remote = await self._bridge_evolve(context)
        if remote:
            return remote
        return self._local_evolve(context, **kwargs)

    def _start(self, name: str) -> PipelineRun:
        return PipelineRun(
            id=uuid.uuid4().hex[:10],
            pipeline=name,
            started_at=datetime.utcnow().isoformat(),
        )

    def _finish(self, run: PipelineRun, result: Dict[str, Any], ok: bool = True, error: str = None) -> PipelineRun:
        run.finished_at = datetime.utcnow().isoformat()
        run.success = ok
        run.result = result
        run.error = error
        self.history.append(run)
        self.history = self.history[-100:]
        return run

    # ----- pipelines -----

    async def run_batch_feedback(self, force: bool = True) -> PipelineRun:
        """Pipeline 1: flush fitness buffer → hybrid genome step."""
        run = self._start("batch_feedback")
        try:
            if self.fitness_loop is None:
                ctx = {"success_rate": 0.6, "ns_weight": 0.55, "mood_alignment": 0.6}
                result = await self._evolve(ctx)
            else:
                result = await self.fitness_loop.maybe_step_genome(force=force)
                result = result or {"note": "buffer below batch size", "snapshot": self.fitness_loop.snapshot()}
            return self._finish(run, result or {}, ok=True)
        except Exception as e:
            return self._finish(run, {}, ok=False, error=str(e))

    async def run_multi_objective(
        self,
        weights: Optional[Dict[str, float]] = None,
        generations: int = 4,
    ) -> PipelineRun:
        """
        Pipeline 2: evolve under explicit multi-objective weights.
        weights keys: success, safety, novelty (normalized internally).
        """
        run = self._start("multi_objective")
        try:
            w = weights or {"success": 0.5, "safety": 0.3, "novelty": 0.2}
            total = sum(w.values()) or 1.0
            w = {k: v / total for k, v in w.items()}
            # Map to fitness context
            base = {}
            if self.fitness_loop:
                base = self.fitness_loop.context_from_buffer()
            ctx = {
                **base,
                "success_rate": base.get("success_rate", 0.55) * w.get("success", 0.5) + 0.45 * (1 - w.get("success", 0.5)),
                "risk_events": int(max(0, 3 * (1.0 - w.get("safety", 0.3)))),
                "novelty": w.get("novelty", 0.2),
                "ns_weight": 0.5 + 0.3 * w.get("novelty", 0.2),
                "mood_alignment": 0.5 + 0.4 * w.get("safety", 0.3),
                "multi_objective_weights": w,
            }
            result = await self._evolve(ctx, generations=generations, mode="hybrid")
            return self._finish(run, {"context": ctx, "evolution": result})
        except Exception as e:
            return self._finish(run, {}, ok=False, error=str(e))

    async def run_speciation(self, generations: int = 3) -> PipelineRun:
        """
        Pipeline 3: maintain three species with different fitness priors.
          ops      — high safety / low novelty
          research — high novelty / low safety penalty
          balanced — hybrid center
        """
        run = self._start("speciation")
        try:
            priors = {
                "ops": {
                    "success_rate": 0.7,
                    "risk_events": 0,
                    "novelty": 0.15,
                    "ns_weight": 0.4,
                    "mood_alignment": 0.8,
                },
                "research": {
                    "success_rate": 0.55,
                    "risk_events": 1,
                    "novelty": 0.85,
                    "ns_weight": 0.7,
                    "mood_alignment": 0.5,
                },
                "balanced": {
                    "success_rate": 0.65,
                    "risk_events": 0,
                    "novelty": 0.4,
                    "ns_weight": 0.55,
                    "mood_alignment": 0.65,
                },
            }
            out = {}
            for name, ctx in priors.items():
                evo = self._local_evolve(ctx, generations=generations, population=8, mode="hybrid")
                best = evo["best"]
                self.species[name] = Species(
                    name=name,
                    role=name,
                    genome=best,
                    fitness=float(best.get("fitness") or 0.0),
                )
                out[name] = {
                    "fitness": self.species[name].fitness,
                    "genome_id": best.get("id"),
                    "generation": best.get("generation"),
                }
            return self._finish(run, {"species": out})
        except Exception as e:
            return self._finish(run, {}, ok=False, error=str(e))

    async def run_job_lineage(self, jobs: List[Dict[str, Any]]) -> PipelineRun:
        """
        Pipeline 4: derive fitness context from job graph results and evolve.
        jobs: list of job dicts with status + steps.
        """
        run = self._start("job_lineage")
        try:
            if not jobs:
                return self._finish(run, {"note": "no jobs"}, ok=True)
            ok_n = sum(1 for j in jobs if j.get("status") == "succeeded")
            fail_n = sum(1 for j in jobs if j.get("status") == "failed")
            n = max(1, len(jobs))
            # agent success rates
            agent_ok: Dict[str, List[bool]] = {}
            for j in jobs:
                for s in j.get("steps") or []:
                    agent_ok.setdefault(s.get("agent", "?"), []).append(
                        s.get("status") == "succeeded"
                    )
            tool_eff = []
            for vals in agent_ok.values():
                tool_eff.append(sum(vals) / max(1, len(vals)))
            ctx = {
                "success_rate": ok_n / n,
                "tool_efficiency": sum(tool_eff) / max(1, len(tool_eff)) if tool_eff else 0.5,
                "risk_events": fail_n,
                "mood_alignment": 0.6,
                "novelty": min(1.0, len(agent_ok) / 5.0),
                "ns_weight": 0.55,
                "job_sample": n,
                "agent_rates": {k: sum(v) / len(v) for k, v in agent_ok.items()},
            }
            if self.fitness_loop:
                for j in jobs[-5:]:
                    self.fitness_loop.record_job(
                        j.get("status") == "succeeded",
                        j.get("id") or "",
                        {"status": j.get("status")},
                    )
            result = await self._evolve(ctx, generations=3)
            return self._finish(run, {"context": ctx, "evolution": result})
        except Exception as e:
            return self._finish(run, {}, ok=False, error=str(e))

    async def run_periodic(self, force: bool = False) -> PipelineRun:
        """Pipeline 5: wall-clock periodic evolution with mild baseline context."""
        run = self._start("periodic")
        try:
            now = time.time()
            if not force and (now - self._last_periodic) < self.periodic_interval_sec:
                return self._finish(
                    run,
                    {
                        "skipped": True,
                        "next_in_sec": self.periodic_interval_sec - (now - self._last_periodic),
                    },
                    ok=True,
                )
            ctx = {
                "success_rate": 0.6,
                "tool_efficiency": 0.6,
                "mood_alignment": 0.6,
                "novelty": 0.35,
                "risk_events": 0,
                "ns_weight": 0.55,
                "source": "periodic",
            }
            if self.fitness_loop and len(self.fitness_loop.buffer):
                ctx = {**ctx, **self.fitness_loop.context_from_buffer()}
            result = await self._evolve(ctx, generations=2)
            self._last_periodic = now
            return self._finish(run, {"context": ctx, "evolution": result})
        except Exception as e:
            return self._finish(run, {}, ok=False, error=str(e))

    async def run_all(self, jobs: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """Execute the full automated suite (except periodic skip logic forced)."""
        results = {
            "batch_feedback": (await self.run_batch_feedback(force=True)).to_dict(),
            "multi_objective": (await self.run_multi_objective()).to_dict(),
            "speciation": (await self.run_speciation()).to_dict(),
            "job_lineage": (await self.run_job_lineage(jobs or [])).to_dict(),
            "periodic": (await self.run_periodic(force=True)).to_dict(),
        }
        return results

    def snapshot(self) -> Dict[str, Any]:
        return {
            "species": {k: v.to_dict() for k, v in self.species.items()},
            "history": [h.to_dict() for h in self.history[-20:]],
            "periodic_interval_sec": self.periodic_interval_sec,
            "last_periodic_age_sec": time.time() - self._last_periodic if self._last_periodic else None,
        }
