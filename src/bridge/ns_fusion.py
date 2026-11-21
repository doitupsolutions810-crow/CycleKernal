"""Neuro-symbolic fitness fused into live mood and colony promotion.

mood_dot = clip(alpha * ns_fitness + beta * mood_score)
Promotion is gated on mood_dot, not on raw symbolic score alone.
"""

from __future__ import annotations

import hashlib
import math
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


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse to float, rejecting NaN and Inf. Non-numeric input returns default."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return v


def _safe_int(value: Any, default: int = 0) -> int:
    """Parse to int via _safe_float so string counts don't crash or lie.

    String "0" yields 0 (not True via bool quirk), "3.5" yields 3,
    "abc" yields default. NaN/Inf yield default.
    """
    return int(_safe_float(value, default))


def symbolic_score(belief: Mapping[str, Any], resources: Mapping[str, Any]) -> float:
    """Constraint side: truth alignment plus resource viability."""
    truth = _clip(_safe_float(belief.get("truth", 0.5)))
    attention = _safe_float(resources.get("attention", 0.0))
    compute = _safe_float(resources.get("compute", 0.0))
    memory_nodes = _safe_float(resources.get("memory_nodes", 0.0))
    viable = _clip((attention / 150.0) * 0.45 + (compute / 40.0) * 0.35 + (memory_nodes / 8.0) * 0.20)
    # Symbolic preference: high truth and enough resources to act on it.
    return _clip(0.55 * truth + 0.45 * viable)


def neural_score(core: float, entropy: float, coupling: float) -> float:
    """Neural / LoopMem side. High entropy is exploratory, not automatically fit."""
    stability = 1.0 - _clip(_safe_float(entropy))
    bind = _clip(_safe_float(coupling) / 0.2)
    return _clip(0.5 * _clip(_safe_float(core)) + 0.3 * stability + 0.2 * bind)


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


def _canonical_mood(mood: Any) -> str:
    """Score key. Non-strings, blanks, and unknown text are neutral."""
    if not isinstance(mood, str):
        return "neutral"
    label = mood.strip() or "neutral"
    if label not in MOOD_SCORE:
        return "neutral"
    return label


def mood_score(mood: str) -> float:
    # Strip before lookup so padded labels from trait mappers still resolve.
    return MOOD_SCORE[_canonical_mood(mood)]


def fuse_mood(ns_fit: float, mood: str, alpha: float = ALPHA, beta: float = BETA) -> float:
    return _clip(alpha * _clip(_safe_float(ns_fit)) + beta * mood_score(mood))


def genome_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"gn-{digest[:12]}"


def colony_genome(members: list) -> str:
    blob = "|".join(sorted(str(m) for m in members)) or "empty-colony"
    return genome_id(f"colony:{blob}")


def promote_decision(fused: float, already_promoted: bool = False) -> Dict[str, Any]:
    # Safe-by-default wrapper: clip before thresholding so raw sensor
    # values outside [0, 1] cannot bypass the hysteresis band.
    fused = _clip(_safe_float(fused))
    if already_promoted and fused <= DEMOTE_THRESHOLD:
        return {"action": "demote", "fused": round(fused, 4), "threshold": DEMOTE_THRESHOLD}
    if (not already_promoted) and fused >= PROMOTE_THRESHOLD:
        return {"action": "promote", "fused": round(fused, 4), "threshold": PROMOTE_THRESHOLD}
    return {"action": "hold", "fused": round(fused, 4), "threshold": PROMOTE_THRESHOLD}


def apply_fusion(state_mood: str, metrics: Mapping[str, Any], colony: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Attach fused mood fields onto a trait-mapper result."""
    core = _safe_float(metrics.get("Core", metrics.get("core", 0.5)), 0.5)
    entropy = _safe_float(metrics.get("L5", metrics.get("entropy", 0.0)))
    coupling = _safe_float(metrics.get("L2", metrics.get("coupling", 0.0)))
    fit = ns_fitness(core=core, entropy=entropy, coupling=coupling)
    canonical = _canonical_mood(state_mood)
    fused = fuse_mood(fit, canonical)
    # Keep a padded known label ("\\tconvergent\\n"). Unknown text becomes neutral.
    if isinstance(state_mood, str) and (state_mood.strip() or "neutral") in MOOD_SCORE:
        label = state_mood
    else:
        label = "neutral"
    colony = dict(colony or {})
    # Count via _safe_int. bool("0") is True, which used to mark a zero
    # string count as already promoted and could demote a colony that is not.
    # A negative count is still a non-zero flag, matching bool(-1).
    decision = promote_decision(fused, already_promoted=_safe_int(colony.get("promoted", 0)) != 0)
    if fused >= 0.7 and canonical == "neutral":
        label = "convergent"
    elif fused < 0.3 and canonical != "survival":
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
            "active": _safe_int(colony.get("active", 0)),
            "promoted": _safe_int(colony.get("promoted", 0)),
            "held": _safe_int(colony.get("held", 0)),
            "dormant": _safe_int(colony.get("dormant", 0)),
            "genome_id": colony.get("genome_id") or "",
        },
    }
