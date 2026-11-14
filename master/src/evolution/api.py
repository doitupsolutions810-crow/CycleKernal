"""
Evolution + Neuro-Symbolic FastAPI surface
Mount under chat or run standalone on port 8400.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from genome import TraitGenome, GenePool
from genetic import GeneticAlgorithm, evolve_traits, map_metrics_with_genome
from ns_fitness import hybrid_fitness, evolve_traits_ns, evaluate_genome_ns, neurosymbolic_fitness
from tool_evolution import evolve_tool_policies, CodingEvolution
from neurosymbolic import NeuroSymbolicReasoner

app = FastAPI(title="CycleKernel Evolution Lab", version="4.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Persistent pool for interactive evolution
_POOL = GenePool(size=16)
_GA = GeneticAlgorithm(_POOL, fitness_fn=hybrid_fitness)
_NS = NeuroSymbolicReasoner()
_CODING = CodingEvolution(population=12)


class EvolveRequest(BaseModel):
    generations: int = 8
    population: int = 16
    context: Dict[str, Any] = Field(default_factory=dict)


class MetricsGoal(BaseModel):
    metrics: Dict[str, float] = Field(default_factory=dict)
    goal: str = ""
    genome_id: Optional[str] = None


@app.get("/health")
async def health():
    return {
        "status": "evolution-online",
        "version": "4.2.0",
        "pool": _POOL.summary(),
    }


@app.post("/v1/evolve/traits")
async def api_evolve_traits(req: EvolveRequest):
    result = evolve_traits(
        generations=req.generations,
        population=req.population,
        context=req.context,
    )
    # refresh module pool with best
    best = TraitGenome.from_dict(result["best"])
    _POOL.population[0] = best
    return result


@app.post("/v1/evolve/step")
async def api_evolve_step(context: Dict[str, Any] = None):
    summary = _GA.step(context or {})
    return {"summary": summary, "best": _POOL.best().to_dict()}


@app.post("/v1/evolve/tools")
async def api_evolve_tools(
    generations: int = 6,
    tools: Optional[List[str]] = None,
    context_by_tool: Optional[Dict[str, Dict[str, Any]]] = None,
):
    return evolve_tool_policies(
        tools=tools,
        generations=generations,
        context_by_tool=context_by_tool,
    )


@app.post("/v1/evolve/code")
async def api_evolve_code(generations: int = 12):
    return _CODING.run(generations=generations)


@app.post("/v1/neurosymbolic/reason")
async def api_ns_reason(body: MetricsGoal):
    # Optionally bind genome weights
    weights = {}
    if body.genome_id:
        for g in _POOL.population:
            if g.id == body.genome_id:
                weights = {
                    "divergent_weight": g.get("divergent_weight"),
                    "convergent_weight": g.get("convergent_weight"),
                    "survival_weight": g.get("survival_weight"),
                }
                break
    ns = NeuroSymbolicReasoner(genome_weights=weights)
    decision = ns.reason(body.metrics, body.goal)
    return decision.to_dict()


@app.post("/v1/genome/map")
async def api_map_with_genome(body: MetricsGoal):
    genome = _POOL.best()
    if body.genome_id:
        for g in _POOL.population:
            if g.id == body.genome_id:
                genome = g
                break
    return map_metrics_with_genome(body.metrics, genome)


@app.get("/v1/genome/best")
async def api_best_genome():
    return _POOL.best().to_dict()


@app.get("/v1/genome/pool")
async def api_pool():
    return {
        "summary": _POOL.summary(),
        "population": [g.to_dict() for g in sorted(_POOL.population, key=lambda x: -x.fitness)[:8]],
    }


class EvolveNSRequest(BaseModel):
    generations: int = 8
    population: int = 16
    context: Dict[str, Any] = Field(default_factory=dict)
    mode: str = "hybrid"  # hybrid | ns | classic


@app.post("/v1/evolve/traits_ns")
async def api_evolve_traits_ns(req: EvolveNSRequest):
    """Evolve traits with neuro-symbolic fitness integration."""
    result = evolve_traits_ns(
        generations=req.generations,
        population=req.population,
        context=req.context,
        mode=req.mode,
    )
    best = TraitGenome.from_dict(result["best"])
    _POOL.population[0] = best
    return result


@app.post("/v1/evolve/evaluate_ns")
async def api_evaluate_ns(body: MetricsGoal):
    """Evaluate best (or specified) genome across NS scenario bank."""
    genome = _POOL.best()
    if body.genome_id:
        for g in _POOL.population:
            if g.id == body.genome_id:
                genome = g
                break
    return evaluate_genome_ns(genome)


@app.post("/v1/evolve/fitness_ns")
async def api_fitness_ns(body: Dict[str, Any]):
    """Score a genome dict with hybrid or pure NS fitness."""
    gdict = body.get("genome") or _POOL.best().to_dict()
    genome = TraitGenome.from_dict(gdict)
    mode = body.get("mode", "hybrid")
    ctx = body.get("context") or {}
    if mode == "ns":
        fr = neurosymbolic_fitness(genome, ctx)
    else:
        fr = hybrid_fitness(genome, ctx)
    return {
        "genome_id": fr.genome_id,
        "score": fr.score,
        "components": fr.components,
        "notes": fr.notes,
        "mode": mode,
    }

