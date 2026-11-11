"""
CognitiveBridge Service — CycleKernel Master v4.2
=================================================
Live path:
  LoopMem metrics
    → optional evolved TraitGenome thresholds/weights
    → NeuroSymbolicReasoner fusion (when available)
    → CognitiveState for Chat / agents / HUD

Also accepts GA closed-loop feedback to adjust the active genome.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from traits import CognitiveState, map_metrics_to_traits

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cognitive-bridge")

# Allow importing evolution package when running in colony network / monorepo
_SRC = Path(__file__).resolve().parents[1]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

app = FastAPI(title="CycleKernel CognitiveBridge", version="4.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

current_state = CognitiveState()
ws_clients: list = []

# Live evolution state
_active_genome: Any = None
_feedback_buffer: List[Dict[str, Any]] = []
_ga_stats: Dict[str, Any] = {"steps": 0, "last_fitness": None, "mode": "hybrid"}
USE_NS = os.getenv("BRIDGE_USE_NS", "1") != "0"


def _load_evolution():
    """Load the optional evolutionary engine when the source package is mounted."""
    try:
        from evolution.genome import TraitGenome, GenePool
        from evolution.genetic import GeneticAlgorithm, map_metrics_with_genome
        from evolution.ns_fitness import hybrid_fitness, neurosymbolic_fitness
        from evolution.neurosymbolic import NeuroSymbolicReasoner
        return {
            "TraitGenome": TraitGenome,
            "GenePool": GenePool,
            "GeneticAlgorithm": GeneticAlgorithm,
            "map_metrics_with_genome": map_metrics_with_genome,
            "hybrid_fitness": hybrid_fitness,
            "neurosymbolic_fitness": neurosymbolic_fitness,
            "NeuroSymbolicReasoner": NeuroSymbolicReasoner,
        }
    except Exception as e:
        logger.warning("evolution package unavailable: %s", e)
        return None


_EVO = None
_POOL = None
_GA = None


def _ensure_evo():
    global _EVO, _POOL, _GA, _active_genome
    if _EVO is None:
        _EVO = _load_evolution()
    if _EVO and _POOL is None:
        _POOL = _EVO["GenePool"](size=12)
        _GA = _EVO["GeneticAlgorithm"](_POOL, fitness_fn=_EVO["hybrid_fitness"])
        _active_genome = _POOL.best()
        logger.info("evolution pool online genome=%s", _active_genome.id)
    return _EVO


def _state_from_ns(metrics: Dict, goal: str = "") -> CognitiveState:
    """Build CognitiveState via neuro-symbolic reasoner + genome weights."""
    evo = _ensure_evo()
    if not evo or not USE_NS:
        return map_metrics_to_traits(metrics)

    genome = _active_genome or evo["TraitGenome"]()
    weights = {
        "divergent_weight": genome.get("divergent_weight", 1.0),
        "convergent_weight": genome.get("convergent_weight", 1.0),
        "survival_weight": genome.get("survival_weight", 1.0),
    }
    explore = genome.get("exploration_bias", 0.5)
    thr = max(0.35, min(0.75, 0.55 - (explore - 0.5) * 0.15))
    ns = evo["NeuroSymbolicReasoner"](genome_weights=weights, trait_threshold=thr)
    decision = ns.reason(metrics, goal)

    # Also apply genome threshold mapping for continuity with classic HUD fields
    mapped = evo["map_metrics_with_genome"](metrics, genome)

    state = CognitiveState(
        mood=mapped.get("mood") or "neutral",
        traits=decision.traits or mapped.get("traits") or ["Neutral-Baseline"],
        system_prompt_override=decision.system_prompt_override or mapped.get("system_prompt_override", ""),
        metrics=metrics,
        entropy=float(metrics.get("L5", metrics.get("entropy", 0.0))),
        coupling=float(metrics.get("L2", metrics.get("coupling", 0.0))),
        core=float(metrics.get("Core", metrics.get("core", 0.5))),
        explanation=decision.explanation or mapped.get("explanation", ""),
    )
    # annotate
    state.metrics = {
        **metrics,
        "_genome_id": genome.id,
        "_genome_generation": genome.generation,
        "_ns_tool": decision.tool,
        "_ns_rules": decision.applied_rules,
    }
    return state


async def sync_state(metrics: Dict, goal: str = "") -> CognitiveState:
    global current_state
    try:
        current_state = _state_from_ns(metrics, goal=goal)
    except Exception as e:
        logger.warning("NS path failed, classic fallback: %s", e)
        current_state = map_metrics_to_traits(metrics)

    dead = []
    for ws in ws_clients:
        try:
            await ws.send_json(current_state.to_dict())
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in ws_clients:
            ws_clients.remove(ws)
    return current_state


async def _synthetic_heartbeat():
    t = 0.0
    while True:
        t += 0.08
        metrics = {
            "Core": 0.25 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.35)),
            "U2": 0.3 + 0.4 * (0.5 + 0.5 * math.sin(t * 0.6 + 1)),
            "L2": 0.01 + 0.09 * (0.5 + 0.5 * math.sin(t * 0.9 + 2)),
            "L5": 0.3 + 0.6 * (0.5 + 0.5 * math.sin(t * 0.5)),
            "entropy": 0.3 + 0.6 * (0.5 + 0.5 * math.sin(t * 0.5)),
            "coupling": 0.01 + 0.09 * (0.5 + 0.5 * math.sin(t * 0.9 + 2)),
        }
        await sync_state(metrics)
        await asyncio.sleep(1.5)


@app.on_event("startup")
async def startup():
    logger.info("CognitiveBridge v4.2 online (NS=%s)", USE_NS)
    _ensure_evo()
    asyncio.create_task(_synthetic_heartbeat())


@app.get("/v1/current_mood")
async def get_current_mood():
    return current_state.to_dict()


@app.post("/v1/metrics")
async def push_metrics(payload: Dict):
    metrics = payload.get("LoopMem") or payload.get("metrics") or payload
    goal = payload.get("goal") or ""
    state = await sync_state(metrics, goal=goal)
    return state.to_dict()


@app.post("/v1/feedback")
async def ingest_feedback(payload: Dict):
    """
    Closed-loop entry from Chat / orchestrator.
    Accumulates outcomes; every N feedbacks runs one GA step with hybrid NS fitness.
    """
    global _active_genome, _ga_stats
    _feedback_buffer.append({**payload, "ts": datetime.utcnow().isoformat()})
    logger.info("Feedback received (%d buffered): %s", len(_feedback_buffer), list(payload.keys()))

    evo = _ensure_evo()
    evolved = None
    if evo and _GA and len(_feedback_buffer) >= int(os.getenv("GA_FEEDBACK_BATCH", "5")):
        # Derive fitness context from recent outcomes
        batch = list(_feedback_buffer)
        _feedback_buffer.clear()
        successes = sum(1 for f in batch if f.get("success") is True)
        n = max(1, len(batch))
        tools_used = []
        for f in batch:
            tools_used.extend(f.get("tools") or [])
        context = {
            "success_rate": successes / n,
            "tool_efficiency": successes / n,
            "mood_alignment": float(sum(1 for f in batch if f.get("mood")) / n),
            "novelty": 0.4,
            "risk_events": sum(1 for f in batch if f.get("success") is False),
            "ns_weight": float(os.getenv("GA_NS_WEIGHT", "0.55")),
        }
        try:
            summary = _GA.step(context)
            _active_genome = _POOL.best()
            _ga_stats = {
                "steps": _ga_stats.get("steps", 0) + 1,
                "last_fitness": _active_genome.fitness,
                "last_summary": summary,
                "mode": "hybrid",
                "genome_id": _active_genome.id,
            }
            evolved = _ga_stats
            logger.info("GA step complete fitness=%.4f genome=%s", _active_genome.fitness, _active_genome.id)
        except Exception as e:
            logger.warning("GA step failed: %s", e)

    return {
        "status": "ingested",
        "buffered": len(_feedback_buffer),
        "evolved": evolved,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/v1/genome")
async def get_genome():
    evo = _ensure_evo()
    if not evo or not _active_genome:
        return {"status": "evolution_unavailable"}
    return {
        "active": _active_genome.to_dict(),
        "pool": _POOL.summary() if _POOL else None,
        "ga": _ga_stats,
    }


@app.post("/v1/genome/evolve")
async def force_evolve(payload: Dict = None):
    """Operator-triggered GA step with optional context override."""
    global _active_genome, _ga_stats
    evo = _ensure_evo()
    if not evo or not _GA:
        return {"error": "evolution_unavailable"}
    ctx = (payload or {}).get("context") or {
        "success_rate": 0.6,
        "ns_weight": 0.55,
        "mood_alignment": 0.6,
    }
    summary = _GA.step(ctx)
    _active_genome = _POOL.best()
    _ga_stats = {
        "steps": _ga_stats.get("steps", 0) + 1,
        "last_fitness": _active_genome.fitness,
        "last_summary": summary,
        "mode": "hybrid",
        "genome_id": _active_genome.id,
    }
    return {"ga": _ga_stats, "active": _active_genome.to_dict()}


@app.get("/health")
async def health():
    return {
        "status": "ghost-online",
        "version": "4.2.0",
        "mood": current_state.mood,
        "ns_enabled": USE_NS,
        "genome_id": getattr(_active_genome, "id", None),
        "ga_steps": _ga_stats.get("steps", 0),
    }


@app.websocket("/ws/hud")
async def hud_stream(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        await websocket.send_json(current_state.to_dict())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)
