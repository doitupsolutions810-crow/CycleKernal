"""Neuro-symbolic fusion with Great Scale stress and companion evidence.

The legacy scalar ns_fitness = sqrt(symbolic_score * neural_score) remains
backward-compatible. It is non-injective: the companion record preserves both
coordinates, their signed disagreement and ratio, threshold margins, and the
Great Scale residual used in the neural entropy path.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite, sqrt
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
    value = float(value)
    if not isfinite(value):
        raise ValueError("fusion values must be finite")
    return max(lo, min(hi, value))


def validate_symbolic_inputs(
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
) -> None:
    """Reject invalid symbolic inputs instead of silently clipping them into a score."""
    if belief is not None:
        if not isinstance(belief, Mapping):
            raise ValueError("belief must be a mapping")
        for field in ("truth", "deception"):
            if field not in belief:
                continue
            try:
                value = float(belief[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"belief.{field} must be numeric") from exc
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"belief.{field} must be finite and in [0, 1]")

    if resources is not None:
        if not isinstance(resources, Mapping):
            raise ValueError("resources must be a mapping")
        for field in ("attention", "compute", "memory_nodes"):
            if field not in resources:
                continue
            try:
                value = float(resources[field])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"resources.{field} must be numeric") from exc
            if not isfinite(value) or value < 0.0:
                raise ValueError(f"resources.{field} must be finite and nonnegative")


def symbolic_score(belief: Mapping[str, Any], resources: Mapping[str, Any]) -> float:
    """Constraint side: truth alignment plus resource viability."""
    validate_symbolic_inputs(belief, resources)
    truth = float(belief.get("truth", 0.5))
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
    ratio = symbolic / neural if neural > 0.0 else None
    ratio_defined = ratio is not None and isfinite(ratio)
    if not ratio_defined:
        ratio = None
    return {
        "symbolic_score": symbolic,
        "neural_score": neural,
        "ns_fitness": sqrt(symbolic * neural),
        "signed_eta": symbolic - neural,
        "absolute_channel_gap": abs(symbolic - neural),
        "symbolic_neural_ratio": ratio,
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
    if belief is not None and not isinstance(belief, Mapping):
        raise ValueError("belief must be a mapping")
    if resources is not None and not isinstance(resources, Mapping):
        raise ValueError("resources must be a mapping")
    belief_provided = bool(belief)
    resources_provided = bool(resources)
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
    descent_source: str = "default_zero",
    mood_input: str = "neutral",
    mood_output: str = "neutral",
    label_projection_threshold: Optional[str] = None,
    metric_source: str = "unknown",
    core: float = 0.5,
    base_entropy: float = 0.0,
    coupling: float = 0.0,
    belief: Optional[Mapping[str, Any]] = None,
    resources: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a JSON-safe companion record; it does not alter decision policy."""
    validate_symbolic_inputs(belief, resources)
    effective_belief = belief or {"truth": 0.5, "deception": 0.5}
    effective_resources = resources or {"attention": 50, "compute": 20, "memory_nodes": 1}
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
        "mood_input": mood_input,
        "mood_output": mood_output,
        "mood_label_projected": mood_input != mood_output,
        "label_projection_threshold": label_projection_threshold,
        "metric_source": metric_source,
        "inputs": {
            "symbolic": {
                "truth": float(effective_belief.get("truth", 0.5)),
                "attention": float(effective_resources.get("attention", 0.0)),
                "compute": float(effective_resources.get("compute", 0.0)),
                "memory_nodes": float(effective_resources.get("memory_nodes", 0.0)),
                "belief_source": channels.get("belief_source", "derived"),
                "resource_source": channels.get("resource_source", "derived"),
            },
            "neural": {
                "core": float(core),
                "base_entropy": float(base_entropy),
                "neural_entropy_used": float(neural_entropy_used),
                "coupling": float(coupling),
            },
            "great_scale": {
                "stress_residual": float(stress_residual),
                "stress_residual_normalized": float(stress_residual_normalized),
                "descent_schema": DESCENT_SCHEMA,
                "descent_source": descent_source,
            },
        },
        "genome_state_schema": FUSION_STATE_ID_SCHEMA,
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
        "descent_source": descent_source,
    }


FUSION_STATE_ID_SCHEMA = "cyclekernel.fusion-state/v2"

def genome_id(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"gn-{digest[:12]}"


def _canonical_fitness_state(state: Mapping[str, Any]) -> str:
    return json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fitness_state_id(state: Mapping[str, Any]) -> str:
    """Full SHA-256 fingerprint of the canonical state and companion channels."""
    canonical = _canonical_fitness_state(state)
    return "fs-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fitness_state_genome_id(state: Mapping[str, Any]) -> str:
    """Backward-sized gn- identifier derived from the complete canonical state."""
    canonical = _canonical_fitness_state(state)
    return genome_id(canonical)


def build_fusion_identity_state(
    *,
    mood_input: str,
    mood_output: str,
    channels: Mapping[str, Any],
    fused: float,
    core: float,
    base_entropy: float,
    neural_entropy_used: float,
    coupling: float,
    belief: Optional[Mapping[str, Any]],
    resources: Optional[Mapping[str, Any]],
    stress_residual: float,
    descent_source: str,
    metric_source: str,
) -> Dict[str, Any]:
    """Canonical state material, keeping latent channels distinct from the scalar."""
    effective_belief = belief or {"truth": 0.5, "deception": 0.5}
    effective_resources = resources or {"attention": 50, "compute": 20, "memory_nodes": 1}
    return {
        "schema": FUSION_STATE_ID_SCHEMA,
        "mood_input": mood_input,
        "mood_output": mood_output,
        "symbolic_score": channels["symbolic_score"],
        "neural_score": channels["neural_score"],
        "belief_source": channels.get("belief_source", "derived"),
        "resource_source": channels.get("resource_source", "derived"),
        "metric_source": metric_source,
        "ns_fitness": channels["ns_fitness"],
        "mood_dot": fused,
        "signed_eta": channels["signed_eta"],
        "symbolic_neural_ratio": channels["symbolic_neural_ratio"],
        "ratio_defined": channels["ratio_defined"],
        "belief_truth": float(effective_belief.get("truth", 0.5)),
        "resource_attention": float(effective_resources.get("attention", 0.0)),
        "resource_compute": float(effective_resources.get("compute", 0.0)),
        "resource_memory_nodes": float(effective_resources.get("memory_nodes", 0.0)),
        "core": core,
        "base_entropy": base_entropy,
        "neural_entropy_used": neural_entropy_used,
        "coupling": coupling,
        "stress_residual": stress_residual,
        "descent_source": descent_source,
        "descent_schema": DESCENT_SCHEMA,
    }


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
    descent_source = "provided" if "stress_residual" in metrics else "default_zero"
    metric_source = str(metrics.get("_metric_source", "unknown"))
    residual_normalized = normalized_stress_residual(residual)
    entropy = entropy_with_stress(base_entropy, residual)
    belief_raw = metrics.get("belief")
    resources_raw = metrics.get("resources")
    if belief_raw is not None and not isinstance(belief_raw, Mapping):
        raise ValueError("belief must be a mapping")
    if resources_raw is not None and not isinstance(resources_raw, Mapping):
        raise ValueError("resources must be a mapping")
    belief = belief_raw if isinstance(belief_raw, Mapping) else None
    resources = resources_raw if isinstance(resources_raw, Mapping) else None

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
    label_projection_threshold = None
    if fused >= CONVERGENT_LABEL_THRESHOLD and state_mood == "neutral":
        label = "convergent"
        label_projection_threshold = "convergent_label"
    elif fused < SURVIVAL_LABEL_THRESHOLD and state_mood != "survival":
        label = "survival"
        label_projection_threshold = "survival_label"

    evidence = build_fitness_evidence(
        channels,
        fused,
        stress_residual=residual,
        stress_residual_normalized=residual_normalized,
        neural_entropy_used=entropy,
        descent_source=descent_source,
        mood_input=state_mood,
        mood_output=label,
        label_projection_threshold=label_projection_threshold,
        metric_source=metric_source,
        core=core,
        base_entropy=base_entropy,
        coupling=coupling,
        belief=belief,
        resources=resources,
    )
    identity_state = build_fusion_identity_state(
        mood_input=state_mood,
        mood_output=label,
        channels=channels,
        fused=fused,
        core=core,
        base_entropy=base_entropy,
        neural_entropy_used=entropy,
        coupling=coupling,
        belief=belief,
        resources=resources,
        stress_residual=residual,
        descent_source=descent_source,
        metric_source=metric_source,
    )
    state_id = fitness_state_id(identity_state)
    derived_genome_id = fitness_state_genome_id(identity_state)
    evidence["fusion_state_id"] = state_id
    # Retain the exact canonical payload so consumers can independently recompute the digest.
    evidence["fusion_state_witness"] = identity_state
    return {
        "ns_fitness": round(fit, 4),
        "mood_dot": round(fused, 4),
        "mood": label,
        "alpha": ALPHA,
        "beta": BETA,
        "promote": decision,
        "genome_id": colony.get("genome_id") or derived_genome_id,
        "fusion_state_id": state_id,
        "genome_state_schema": FUSION_STATE_ID_SCHEMA,
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
