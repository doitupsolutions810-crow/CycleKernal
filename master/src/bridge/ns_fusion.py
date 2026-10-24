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


def fusion_components(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> Dict[str, Any]:
    """Return score components and the exact inputs used by the fusion."""
    belief_was_provided = bool(belief)
    resources_were_provided = bool(resources)
    resolved_belief = belief or {"truth": 0.5, "deception": 0.5}
    resolved_resources = resources or {"attention": 50, "compute": 20, "memory_nodes": 1}

    symbolic = symbolic_score(resolved_belief, resolved_resources)
    neural = neural_score(core, entropy, coupling)
    fit = _clip((symbolic * neural) ** 0.5)

    if belief_was_provided and resources_were_provided:
        symbolic_source = "provided"
    elif belief_was_provided or resources_were_provided:
        symbolic_source = "partial-default"
    else:
        symbolic_source = "default-fallback"

    return {
        "symbolic_score": symbolic,
        "neural_score": neural,
        "ns_fitness": fit,
        "symbolic_source": symbolic_source,
        "inputs": {
            "symbolic": {
                "truth": float(resolved_belief.get("truth", 0.5)),
                "attention": float(resolved_resources.get("attention", 0.0)),
                "compute": float(resolved_resources.get("compute", 0.0)),
                "memory_nodes": float(resolved_resources.get("memory_nodes", 0.0)),
            },
            "neural": {
                "core": float(core),
                "entropy": float(entropy),
                "coupling": float(coupling),
            },
        },
    }


def ns_fitness(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> float:
    """Backwards-compatible scalar API; use fusion_components for diagnostics."""
    return fusion_components(
        belief=belief,
        resources=resources,
        core=core,
        entropy=entropy,
        coupling=coupling,
    )["ns_fitness"]

def mood_score(mood: str) -> float:
    return MOOD_SCORE.get(mood or "neutral", 0.5)


def fuse_mood(ns_fit: float, mood: str, alpha: float = ALPHA, beta: float = BETA) -> float:
    return _clip(alpha * _clip(ns_fit) + beta * mood_score(mood))


def build_companion_channel(
    *,
    components: Mapping[str, Any],
    fused: float,
    state_mood: str,
    decision: Mapping[str, Any],
    telemetry_source: str = "unspecified",
    already_promoted: bool = False,
) -> Dict[str, Any]:
    """Preserve score attribution and signed distances to every decision boundary."""
    thresholds = {
        "promote": PROMOTE_THRESHOLD,
        "demote": DEMOTE_THRESHOLD,
        "survival_label": 0.30,
        "convergent_label": 0.70,
    }
    return {
        "schema": "cyclekernel.ns-fusion-companion/v1",
        "telemetry_source": str(telemetry_source or "unspecified"),
        "symbolic_source": components["symbolic_source"],
        "symbolic_score": components["symbolic_score"],
        "neural_score": components["neural_score"],
        "ns_fitness": components["ns_fitness"],
        "mood_score": mood_score(state_mood),
        "mood_dot": float(fused),
        "thresholds": thresholds,
        # Signed distance = mood_dot - threshold; positive means above threshold.
        "threshold_distances": {
            name: float(fused) - float(threshold)
            for name, threshold in thresholds.items()
        },
        "decision": str(decision.get("action", "unknown")),
        "already_promoted": bool(already_promoted),
        "inputs": components["inputs"],
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


def apply_fusion(state_mood: str, metrics: Mapping[str, Any], colony: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Attach fused mood fields onto a trait-mapper result."""
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    entropy = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    coupling = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    belief = metrics.get("belief")
    resources = metrics.get("resources")
    if not isinstance(belief, Mapping):
        belief = None
    if not isinstance(resources, Mapping):
        resources = None
    components = fusion_components(
        belief=belief,
        resources=resources,
        core=core,
        entropy=entropy,
        coupling=coupling,
    )
    fit = components["ns_fitness"]
    fused = fuse_mood(fit, state_mood)
    colony = dict(colony or {})
    # FIX: pass the raw promoted flag. The prior conjunction with the promote
    # threshold made the demote branch unreachable for any previously promoted
    # colony whose fused score had fallen below DEMOTE_THRESHOLD.
    decision = promote_decision(fused, already_promoted=bool(colony.get("promoted", 0)))
    companion = build_companion_channel(
        components=components,
        fused=fused,
        state_mood=state_mood,
        decision=decision,
        telemetry_source=metrics.get("telemetry_source", "unspecified"),
        already_promoted=bool(colony.get("promoted", 0)),
    )
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
        "companion_channel": companion,
        "genome_id": colony.get("genome_id") or genome_id(f"{label}:{fit:.4f}:{core:.3f}"),
        "colony": {
            "active": int(colony.get("active", 0)),
            "promoted": int(colony.get("promoted", 0)),
            "held": int(colony.get("held", 0)),
            "dormant": int(colony.get("dormant", 0)),
            "genome_id": colony.get("genome_id") or "",
        },
    }
