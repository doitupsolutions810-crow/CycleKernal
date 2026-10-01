"""Neuro-symbolic fitness fused into live mood and colony promotion.

mood_dot = clip(alpha * ns_fitness + beta * mood_score)
Promotion is gated on mood_dot, not on raw symbolic score alone.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, Mapping, Optional

ALPHA = 0.65
BETA = 0.35
PROMOTE_THRESHOLD = 0.62
DEMOTE_THRESHOLD = 0.28

MOOD_SCORE = {
    "survival": 0.15,
    "neutral": 0.50,
    "balanced-tension": 0.58,
    "convergent": 0.72,
    "divergent": 0.66,
}


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def symbolic_score(belief: Mapping[str, Any], resources: Mapping[str, Any]) -> float:
    """Constraint side: truth alignment plus resource viability."""
    truth = _clip(float(belief.get("truth", 0.5)))
    attention = float(resources.get("attention", 0.0))
    compute = float(resources.get("compute", 0.0))
    memory_nodes = float(resources.get("memory_nodes", 0.0))
    viable = _clip((attention / 150.0) * 0.45 + (compute / 40.0) * 0.35 + (memory_nodes / 8.0) * 0.20)
    # Symbolic preference: high truth and enough resources to act on it.
    return _clip(0.55 * truth + 0.45 * viable)


def neural_score(core: float, entropy: float, coupling: float) -> float:
    """Neural / LoopMem side. High entropy is exploratory, not automatically fit."""
    stability = 1.0 - _clip(entropy)
    bind = _clip(coupling / 0.2)
    return _clip(0.5 * _clip(core) + 0.3 * stability + 0.2 * bind)


def ns_fitness(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> float:
    belief = belief or {"truth": 0.5, "deception": 0.5}
    resources = resources or {"attention": 50, "compute": 20, "memory_nodes": 1}
    symbolic = symbolic_score(belief, resources)
    neural = neural_score(core, entropy, coupling)
    # Tight fusion: both sides must agree. Geometric mean punishes a one-sided spike.
    return _clip((symbolic * neural) ** 0.5)


def mood_score(mood: str) -> float:
    return MOOD_SCORE.get(mood or "neutral", 0.5)


def fuse_mood(ns_fit: float, mood: str, alpha: float = ALPHA, beta: float = BETA) -> float:
    return _clip(alpha * _clip(ns_fit) + beta * mood_score(mood))


def genome_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"gn-{digest[:12]}"


def colony_genome(members: list) -> str:
    blob = "|".join(sorted(str(m) for m in members)) or "empty-colony"
    return genome_id(f"colony:{blob}")


def promote_decision(fused: float, already_promoted: bool = False) -> Dict[str, Any]:
    if already_promoted and fused < DEMOTE_THRESHOLD:
        return {"action": "demote", "fused": round(fused, 4), "threshold": DEMOTE_THRESHOLD}
    if (not already_promoted) and fused >= PROMOTE_THRESHOLD:
        return {"action": "promote", "fused": round(fused, 4), "threshold": PROMOTE_THRESHOLD}
    return {"action": "hold", "fused": round(fused, 4), "threshold": PROMOTE_THRESHOLD}


def apply_fusion(state_mood: str, metrics: Mapping[str, Any], colony: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Attach fused mood fields onto a trait-mapper result."""
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    entropy = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    coupling = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    fit = ns_fitness(core=core, entropy=entropy, coupling=coupling)
    fused = fuse_mood(fit, state_mood)
    colony = dict(colony or {})
    decision = promote_decision(fused, already_promoted=bool(colony.get("promoted", 0) and fused >= PROMOTE_THRESHOLD))
    label = state_mood
    if fused >= 0.7 and state_mood == "neutral":
        label = "convergent"
    elif fused < 0.3 and state_mood != "survival":
        label = "survival"
    return {
        "ns_fitness": round(fit, 4),
        "mood_dot": round(fused, 4),
        "mood": label,
        "alpha": ALPHA,
        "beta": BETA,
        "promote": decision,
        "genome_id": colony.get("genome_id") or genome_id(f"{label}:{fit:.4f}:{core:.3f}"),
        "colony": {
            "active": int(colony.get("active", 0)),
            "promoted": int(colony.get("promoted", 0)),
            "held": int(colony.get("held", 0)),
            "dormant": int(colony.get("dormant", 0)),
            "genome_id": colony.get("genome_id") or "",
        },
    }
