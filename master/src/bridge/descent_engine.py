"""Python adapter for Great Scale public/scale.js DescentEngine.

This mirrors the deterministic contraction used by Great Scale v0.4.2.
The CycleKernal adapter deliberately restricts the initial state to [1, 8]:
on this interval the raw stress residual |x - f(x)| is bounded by 7,
so residual/7 is a valid normalization for the configured descent trajectory.
That bound is not valid across the continuous circle seam near 0/9.
"""
from __future__ import annotations

from collections import deque
from math import isfinite
from typing import Any

SCHEMA = "great-scale.descent/v0.4.2"
SOURCE_VERSION = "great-scale/public/scale.js@a0fd4b10b964932f90abf7004bbe7e28687168d1"
FIXED = 4.5
STRESS_RESIDUAL_MAX = 7.0
STRESS_ENTROPY_WEIGHT = 0.35


def heat(h: float) -> float:
    return h * (1.0 - h)


def involution(x: float) -> float:
    m = ((x % 9.0) + 9.0) % 9.0
    return (9.0 - m) % 9.0


def modular_distance(a: float, b: float) -> float:
    d = abs((((a - b) % 9.0) + 9.0) % 9.0)
    return min(d, 9.0 - d)


def involution_identity(x: float, tolerance: float = 1e-9) -> bool:
    return modular_distance(involution(involution(x)), x) < tolerance


def stress_residual(x: float) -> float:
    return abs(x - involution(x))


def normalized_stress_residual(residual: float) -> float:
    """Normalize the configured [0, 7] residual range; reject scope violations."""
    residual = float(residual)
    if not isfinite(residual) or residual < 0.0 or residual > STRESS_RESIDUAL_MAX + 1e-9:
        raise ValueError("stress residual is outside the configured [0, 7] domain")
    return min(1.0, residual / STRESS_RESIDUAL_MAX)


def entropy_with_stress(base_entropy: float, residual: float) -> float:
    """Add a bounded, normalized descent-stress contribution to neural entropy."""
    base = float(base_entropy)
    if not isfinite(base):
        raise ValueError("base entropy must be finite")
    normalized = normalized_stress_residual(residual)
    return max(0.0, min(1.0, base + STRESS_ENTROPY_WEIGHT * normalized))


class DescentEngine:
    """Deterministic, scheduler-driven mirror of Great Scale's DescentEngine."""

    def __init__(self, start: float = 1.0, k: float = 0.5, max_history: int = 200):
        start = float(start)
        k = float(k)
        if not isfinite(start) or not 1.0 <= start <= 8.0:
            raise ValueError("start must be within [1, 8] for the residual normalization contract")
        if not isfinite(k) or not abs(k) < 1.0:
            raise ValueError("contraction factor k must satisfy |k| < 1")
        if max_history < 1:
            raise ValueError("max_history must be positive")
        self.x = start
        self.k = k
        self.t = 0
        self.history: deque[dict[str, Any]] = deque(maxlen=max_history)

    def tick(self) -> dict[str, Any]:
        self.x = FIXED + self.k * (self.x - FIXED)
        self.t += 1
        residual = stress_residual(self.x)
        rec = {
            "t": self.t,
            "x": self.x,
            "S": heat(self.x / 9.0),
            "residual": residual,
            "residualNormalized": normalized_stress_residual(residual),
            "nearFixed": abs(self.x - FIXED) < 0.05,
            "involution": involution(self.x),
        }
        self.history.append(rec)
        return dict(rec)

    def snapshot(self, running: bool = False) -> dict[str, Any]:
        residual = stress_residual(self.x)
        return {
            "schema": SCHEMA,
            "sourceVersion": SOURCE_VERSION,
            "running": bool(running),
            "t": self.t,
            "x": self.x,
            "k": self.k,
            "nearFixed": abs(self.x - FIXED) < 0.05,
            "residual": residual,
            "residualNormalized": normalized_stress_residual(residual),
            "historyLen": len(self.history),
            "last": dict(self.history[-1]) if self.history else None,
        }
