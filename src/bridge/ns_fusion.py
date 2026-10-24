"""Neuro-symbolic fusion with Great Scale stress and companion evidence.

The legacy scalar ns_fitness = sqrt(symbolic_score * neural_score) remains
backward-compatible. It is non-injective: the companion record preserves both
coordinates, their signed disagreement and ratio, threshold margins, and the
Great Scale residual used in the neural entropy path.
"""
from __future__ import annotations

import hashlib
from math import sqrt
from typing import Any, Dict, Mapping, Optional

from descent_engine import entropy_with_stress, normalized_stress_residual

ALPHA = 0.65
BETA = 0.35
PROMOTE_THRESHOLD = 0.62
DEMOTE_THRESHOLD = 0.28
CONVERGENT_LABEL_THRESHOLD = 0.70
SURVIVAL_LABEL_THRESHOLD = 0.30
FITNESS_EVIDENCE_SCHEMA = "cyclekernel.fusion-evidence/v1"
DESCENT_SCHEMA = "great-scale.descent/v0.4.2"

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
    return _clip(0.55 * truth + 0.45 * viable)


def neural_score(core: float, entropy: float, coupling: float) -> float:
    """Neural / LoopMem side. High entropy is exploratory, not automatically fit."""
    stability = 1.0 - _clip(entropy)
    bind = _clip(coupling / 0.2)
    return _clip(0.5 * _clip(core) + 0.3 * stability + 0.2 * bind)


def summarize_fitness_channels(symbolic: float, neural: float) -> Dict[str, Any]:
    """Preserve the coordinates of the legacy geometric-mean projection."""
    symbolic = _clip(symbolic)
    neural = _clip(neural)
    ratio_defined = neural > 0.0
    return {
        "symbolic_score": symbolic,
        "neural_score": neural,
        "ns_fitness": sqrt(symbolic * neural),
        "signed_eta": symbolic - neural,
        "absolute_channel_gap": abs(symbolic - neural),
        "symbolic_neural_ratio": symbolic / neural if ratio_defined else None,
        "ratio_defined": ratio_defined,
    }


def fitness_channels(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> Dict[str, Any]:
    """Compute symbolic and neural channels plus source metadata."""
    belief_provided = belief is not None
    resources_provided = resources is not None
    belief = belief or {"truth": 0.5, "deception": 0.5}
    resources = resources or {"attention": 50, "compute": 20, "memory_nodes": 1}
    return {
        **summarize_fitness_channels(
            symbolic_score(belief, resources),
            neural_score(core, entropy, coupling),
        ),
        "belief_source": "provided" if belief_provided else "default",
        "resource_source": "provided" if resources_provided else "default",
    }


def ns_fitness(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> float:
    """Compatibility API returning only the historical scalar score."""
    return fitness_channels(
        belief=belief, resources=resources, core=core, entropy=entropy, coupling=coupling
    )["ns_fitness"]


def mood_score(mood: str) -> float:
    return MOOD_SCORE.get(mood or "neutral", 0.5)


def fuse_mood(ns_fit: float, mood: str, alpha: float = ALPHA, beta: float = BETA) -> float:
    return _clip(alpha * _clip(ns_fit) + beta * mood_score(mood))


def build_fitness_evidence(
    channels: Mapping[str, Any],
    fused: float,
    *,
    stress_residual: float = 0.0,
    stress_residual_normalized: float = 0.0,
    neural_entropy_used: float = 0.0,
) -> Dict[str, Any]:
    """Build a JSON-safe companion record; it does not alter decision policy."""
    thresholds = {
        "promote": PROMOTE_THRESHOLD,
        "demote": DEMOTE_THRESHOLD,
        "convergent_label": CONVERGENT_LABEL_THRESHOLD,
        "survival_label": SURVIVAL_LABEL_THRESHOLD,
    }
    return {
        "schema": FITNESS_EVIDENCE_SCHEMA,
        "symbolic_score": round(float(channels["symbolic_score"]), 6),
        "neural_score": round(float(channels["neural_score"]), 6),
        "ns_fitness": round(float(channels["ns_fitness"]), 6),
        "signed_eta": round(float(channels["signed_eta"]), 6),
        "absolute_channel_gap": round(float(channels["absolute_channel_gap"]), 6),
        "symbolic_neural_ratio": (
            round(float(channels["symbolic_neural_ratio"]), 6)
            if channels.get("ratio_defined") else None
        ),
        "ratio_defined": bool(channels.get("ratio_defined")),
        "belief_source": channels.get("belief_source", "derived"),
        "resource_source": channels.get("resource_source", "derived"),
        "mood_dot": round(float(fused), 6),
        "threshold_distances": {
            name: round(abs(float(fused) - threshold), 6)
            for name, threshold in thresholds.items()
        },
        "threshold_margins": {
            name: round(float(fused) - threshold, 6)
            for name, threshold in thresholds.items()
        },
        "stress_residual": round(float(stress_residual), 8),
        "stress_residual_normalized": round(float(stress_residual_normalized), 8),
        "neural_entropy_used": round(float(neural_entropy_used), 8),
        "descent_schema": DESCENT_SCHEMA,
    }


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


def apply_fusion(
    state_mood: str,
    metrics: Mapping[str, Any],
    colony: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Apply Great Scale stress then return legacy outputs plus explicit evidence."""
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    base_entropy = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    coupling = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    residual = float(metrics.get("stress_residual", 0.0))
    residual_normalized = normalized_stress_residual(residual)
    entropy = entropy_with_stress(base_entropy, residual)
    belief = metrics.get("belief") if isinstance(metrics.get("belief"), Mapping) else None
    resources = metrics.get("resources") if isinstance(metrics.get("resources"), Mapping) else None

    channels = fitness_channels(
        belief=belief,
        resources=resources,
        core=core,
        entropy=entropy,
        coupling=coupling,
    )
    fit = channels["ns_fitness"]
    fused = fuse_mood(fit, state_mood)
    colony = dict(colony or {})
    decision = promote_decision(fused, already_promoted=bool(colony.get("promoted", 0)))
    label = state_mood
    if fused >= CONVERGENT_LABEL_THRESHOLD and state_mood == "neutral":
        label = "convergent"
    elif fused < SURVIVAL_LABEL_THRESHOLD and state_mood != "survival":
        label = "survival"
    evidence = build_fitness_evidence(
        channels,
        fused,
        stress_residual=residual,
        stress_residual_normalized=residual_normalized,
        neural_entropy_used=entropy,
    )
    return {
        "ns_fitness": round(fit, 4),
        "mood_dot": round(fused, 4),
        "mood": label,
        "alpha": ALPHA,
        "beta": BETA,
        "promote": decision,
        "genome_id": colony.get("genome_id") or genome_id(f"{label}:{fit:.4f}:{core:.3f}"),
        "fitness_evidence": evidence,
        "stress_residual": residual,
        "stress_residual_normalized": residual_normalized,
        "neural_entropy_used": entropy,
        "descent_schema": DESCENT_SCHEMA,
        "colony": {
            "active": int(colony.get("active", 0)),
            "promoted": int(colony.get("promoted", 0)),
            "held": int(colony.get("held", 0)),
            "dormant": int(colony.get("dormant", 0)),
            "genome_id": colony.get("genome_id") or "",
        },
    }
