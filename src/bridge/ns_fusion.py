"""Neuro-symbolic fitness fusion with explicit channel evidence.

mood_dot = clip(alpha * ns_fitness + beta * mood_score)
Promotion remains gated on mood_dot. Raw symbolic/neural channels and their
margins are emitted beside the scalar so equal projections remain auditable.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Dict, Mapping, Optional

ALPHA = 0.65
BETA = 0.35
PROMOTE_THRESHOLD = 0.62
DEMOTE_THRESHOLD = 0.28
CHANNEL_COLLISION_TOLERANCE = 0.30
FUSED_SCORE_TOLERANCE = 1e-4

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
    viable = _clip(
        (attention / 150.0) * 0.45
        + (compute / 40.0) * 0.35
        + (memory_nodes / 8.0) * 0.20
    )
    return _clip(0.55 * truth + 0.45 * viable)


def neural_score(core: float, entropy: float, coupling: float) -> float:
    """Neural / LoopMem side. High entropy is exploratory, not automatically fit."""
    stability = 1.0 - _clip(entropy)
    bind = _clip(coupling / 0.2)
    return _clip(0.5 * _clip(core) + 0.3 * stability + 0.2 * bind)


def fusion_evidence(symbolic: float, neural: float) -> Dict[str, Any]:
    """Return the scalar projection and the companion channels that explain it.

    For s,n in [0,1], sigma=sqrt(s*n) is non-injective. The signed delta
    s-n, together with sigma, recovers the ordered pair:
      s=(sqrt(delta**2 + 4*sigma**2)+delta)/2
      n=(sqrt(delta**2 + 4*sigma**2)-delta)/2
    """
    symbolic = _clip(symbolic)
    neural = _clip(neural)
    fitness = math.sqrt(symbolic * neural)
    delta = symbolic - neural
    return {
        "symbolic_score": symbolic,
        "neural_score": neural,
        "ns_fitness": fitness,
        "channel_delta": delta,
        "channel_gap": abs(delta),
        # These four margins compare each raw channel with the existing
        # fused-decision thresholds for diagnosis only; they do not gate action.
        "threshold_distances": {
            "symbolic_to_promote": symbolic - PROMOTE_THRESHOLD,
            "symbolic_to_demote": symbolic - DEMOTE_THRESHOLD,
            "neural_to_promote": neural - PROMOTE_THRESHOLD,
            "neural_to_demote": neural - DEMOTE_THRESHOLD,
        },
    }


def ns_components(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> Dict[str, Any]:
    """Compute both fitness channels before projecting them to one scalar."""
    belief = belief or {"truth": 0.5, "deception": 0.5}
    resources = resources or {"attention": 50, "compute": 20, "memory_nodes": 1}
    symbolic = symbolic_score(belief, resources)
    neural = neural_score(core, entropy, coupling)
    return fusion_evidence(symbolic, neural)


def ns_fitness(
    *,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
    core: float = 0.5,
    entropy: float = 0.0,
    coupling: float = 0.0,
) -> float:
    """Backward-compatible scalar API; use ns_components for explainability."""
    return ns_components(
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


def genome_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"gn-{digest[:12]}"


def colony_genome(members: list) -> str:
    blob = "|".join(sorted(str(m) for m in members)) or "empty-colony"
    return genome_id(f"colony:{blob}")


def promote_decision(fused: float, already_promoted: bool = False) -> Dict[str, Any]:
    if already_promoted:
        if fused < DEMOTE_THRESHOLD:
            return {"action": "demote", "fused": round(fused, 4), "threshold": DEMOTE_THRESHOLD}
        return {"action": "hold", "fused": round(fused, 4), "threshold": DEMOTE_THRESHOLD}
    if fused >= PROMOTE_THRESHOLD:
        return {"action": "promote", "fused": round(fused, 4), "threshold": PROMOTE_THRESHOLD}
    return {"action": "hold", "fused": round(fused, 4), "threshold": PROMOTE_THRESHOLD}


def find_promotion_collisions(
    records: list,
    channel_tolerance: float = CHANNEL_COLLISION_TOLERANCE,
    fused_tolerance: float = FUSED_SCORE_TOLERANCE,
) -> list:
    """Find promoted records with equal fused scores but materially different channels.

    This is an audit diagnostic, not an automatic change to promotion policy.
    """
    promoted = [
        row for row in records
        if row.get("action") == "promote"
        and row.get("mood_dot") is not None
        and row.get("symbolic_score") is not None
        and row.get("neural_score") is not None
    ]
    findings = []
    for index, left in enumerate(promoted):
        for right in promoted[index + 1:]:
            if abs(float(left["mood_dot"]) - float(right["mood_dot"])) > fused_tolerance:
                continue
            symbolic_delta = abs(float(left["symbolic_score"]) - float(right["symbolic_score"]))
            neural_delta = abs(float(left["neural_score"]) - float(right["neural_score"]))
            if symbolic_delta > channel_tolerance or neural_delta > channel_tolerance:
                findings.append({
                    "first_event_id": left.get("event_id"),
                    "second_event_id": right.get("event_id"),
                    "mood_dot": max(float(left["mood_dot"]), float(right["mood_dot"])),
                    "symbolic_delta": symbolic_delta,
                    "neural_delta": neural_delta,
                    "channel_tolerance": channel_tolerance,
                })
    return findings


def apply_fusion(
    state_mood: str,
    metrics: Mapping[str, Any],
    colony: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach the scalar and its companion evidence to a trait-mapper result."""
    core = float(metrics.get("Core", metrics.get("core", 0.5)))
    entropy = float(metrics.get("L5", metrics.get("entropy", 0.0)))
    coupling = float(metrics.get("L2", metrics.get("coupling", 0.0)))
    belief = metrics.get("belief")
    resources = metrics.get("resources")
    if not isinstance(belief, Mapping):
        belief = None
    if not isinstance(resources, Mapping):
        resources = None

    symbolic_complete = isinstance(belief, Mapping) and isinstance(resources, Mapping)
    neural_complete = (
        ("Core" in metrics or "core" in metrics)
        and ("L5" in metrics or "entropy" in metrics)
        and ("L2" in metrics or "coupling" in metrics)
    )
    evidence = ns_components(
        belief=belief,
        resources=resources,
        core=core,
        entropy=entropy,
        coupling=coupling,
    )
    channel_provenance = {
        "symbolic": {
            "source": "belief+resources" if symbolic_complete else "defaulted_inputs",
            "complete": symbolic_complete,
        },
        "neural": {
            "source": "Core+L5+L2" if neural_complete else "partial_or_defaulted_inputs",
            "complete": neural_complete,
        },
    }
    evidence["channel_provenance"] = channel_provenance
    fit = evidence["ns_fitness"]
    fused = fuse_mood(fit, state_mood)
    colony = dict(colony or {})
    # Do not let the promote threshold hide the demotion path: promoted state
    # must be passed through unchanged, and promote_decision checks demotion.
    decision = promote_decision(fused, already_promoted=bool(colony.get("promoted", 0)))
    label = state_mood
    if fused >= 0.7 and state_mood == "neutral":
        label = "convergent"
    elif fused < 0.3 and state_mood != "survival":
        label = "survival"

    mood_threshold_distances = {
        "to_promote": fused - PROMOTE_THRESHOLD,
        "to_demote": fused - DEMOTE_THRESHOLD,
    }
    return {
        "ns_fitness": round(fit, 4),
        "mood_dot": round(fused, 4),
        "symbolic_score": evidence["symbolic_score"],
        "neural_score": evidence["neural_score"],
        "channel_delta": evidence["channel_delta"],
        "channel_gap": evidence["channel_gap"],
        "threshold_distances": evidence["threshold_distances"],
        "mood_threshold_distances": mood_threshold_distances,
        "fusion_evidence": evidence,
        "channel_provenance": channel_provenance,
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
