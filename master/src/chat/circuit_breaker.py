"""
CycleKernel Circuit Breaker — production-grade per-tool isolation
=================================================================
States:
  CLOSED     — normal traffic; failures accumulate in a sliding window
  OPEN       — all calls rejected until cooldown expires
  HALF_OPEN  — limited probe traffic; success → CLOSED, failure → OPEN

Features:
  • Sliding failure window (time-based, not unbounded counter)
  • Explicit half-open probe budget
  • Async-safe (asyncio.Lock)
  • Structured status / metrics
  • Optional on_state_change callbacks
  • Manual force open / force close for operators
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger("ck.circuit")


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitConfig:
    """Per-tool breaker configuration."""
    failure_threshold: int = 5          # failures in window → OPEN
    success_threshold: int = 2          # consecutive half-open successes → CLOSED
    window_sec: float = 60.0            # sliding window for failure counting
    cooldown_sec: float = 60.0          # OPEN duration before HALF_OPEN
    half_open_max_probes: int = 2       # concurrent/total probes allowed in HALF_OPEN
    name: str = "default"


@dataclass
class CircuitMetrics:
    total_calls: int = 0
    total_successes: int = 0
    total_failures: int = 0
    total_rejected: int = 0             # short-circuited while OPEN
    consecutive_successes: int = 0      # for half-open graduation
    last_failure_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_state_change_at: Optional[float] = None
    opened_count: int = 0               # how many times we entered OPEN


@dataclass
class CircuitSnapshot:
    name: str
    state: CircuitState
    metrics: Dict[str, Any]
    config: Dict[str, Any]
    failures_in_window: int
    probes_in_flight: int
    cooldown_remaining_sec: float


StateChangeCallback = Callable[[str, CircuitState, CircuitState], None]


class CircuitBreaker:
    """
    One logical breaker, usually keyed by tool name.
    Thread/async safe via asyncio.Lock.
    """

    def __init__(self, config: Optional[CircuitConfig] = None):
        self.config = config or CircuitConfig()
        self.state = CircuitState.CLOSED
        self.metrics = CircuitMetrics()
        self._failure_ts: Deque[float] = deque()
        self._opened_at: Optional[float] = None
        self._probes_in_flight: int = 0
        self._lock = asyncio.Lock()
        self._on_state_change: List[StateChangeCallback] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def on_state_change(self, cb: StateChangeCallback) -> None:
        self._on_state_change.append(cb)

    async def allow(self) -> bool:
        """
        Return True if a call may proceed.
        In HALF_OPEN, consumes a probe slot.
        """
        async with self._lock:
            self._expire_window()
            self._maybe_transition_to_half_open()

            if self.state == CircuitState.OPEN:
                self.metrics.total_rejected += 1
                return False

            if self.state == CircuitState.HALF_OPEN:
                if self._probes_in_flight >= self.config.half_open_max_probes:
                    self.metrics.total_rejected += 1
                    return False
                self._probes_in_flight += 1
                return True

            # CLOSED
            return True

    async def record_success(self) -> None:
        async with self._lock:
            self.metrics.total_calls += 1
            self.metrics.total_successes += 1
            self.metrics.last_success_at = time.time()
            self.metrics.consecutive_successes += 1

            if self.state == CircuitState.HALF_OPEN:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                if self.metrics.consecutive_successes >= self.config.success_threshold:
                    self._set_state(CircuitState.CLOSED)
                    self._failure_ts.clear()
                    self.metrics.consecutive_successes = 0
            elif self.state == CircuitState.CLOSED:
                # healthy — optionally decay is handled by sliding window
                pass

    async def record_failure(self) -> None:
        async with self._lock:
            now = time.time()
            self.metrics.total_calls += 1
            self.metrics.total_failures += 1
            self.metrics.last_failure_at = now
            self.metrics.consecutive_successes = 0
            self._failure_ts.append(now)
            self._expire_window()

            if self.state == CircuitState.HALF_OPEN:
                self._probes_in_flight = max(0, self._probes_in_flight - 1)
                # any failure in half-open re-trips the breaker
                self._trip(now)
                return

            if self.state == CircuitState.CLOSED:
                if len(self._failure_ts) >= self.config.failure_threshold:
                    self._trip(now)

    async def force_open(self, reason: str = "manual") -> None:
        async with self._lock:
            logger.warning(f"circuit[{self.config.name}] FORCE OPEN reason={reason}")
            self._trip(time.time())

    async def force_close(self, reason: str = "manual") -> None:
        async with self._lock:
            logger.info(f"circuit[{self.config.name}] FORCE CLOSE reason={reason}")
            self._failure_ts.clear()
            self._probes_in_flight = 0
            self._opened_at = None
            self.metrics.consecutive_successes = 0
            self._set_state(CircuitState.CLOSED)

    async def reset(self) -> None:
        await self.force_close("reset")
        self.metrics = CircuitMetrics()

    def snapshot(self) -> CircuitSnapshot:
        self._expire_window()
        cooldown_left = 0.0
        if self.state == CircuitState.OPEN and self._opened_at is not None:
            cooldown_left = max(
                0.0,
                self.config.cooldown_sec - (time.time() - self._opened_at),
            )
        return CircuitSnapshot(
            name=self.config.name,
            state=self.state,
            metrics={
                "total_calls": self.metrics.total_calls,
                "total_successes": self.metrics.total_successes,
                "total_failures": self.metrics.total_failures,
                "total_rejected": self.metrics.total_rejected,
                "consecutive_successes": self.metrics.consecutive_successes,
                "opened_count": self.metrics.opened_count,
                "last_failure_at": self.metrics.last_failure_at,
                "last_success_at": self.metrics.last_success_at,
                "last_state_change_at": self.metrics.last_state_change_at,
            },
            config={
                "failure_threshold": self.config.failure_threshold,
                "success_threshold": self.config.success_threshold,
                "window_sec": self.config.window_sec,
                "cooldown_sec": self.config.cooldown_sec,
                "half_open_max_probes": self.config.half_open_max_probes,
            },
            failures_in_window=len(self._failure_ts),
            probes_in_flight=self._probes_in_flight,
            cooldown_remaining_sec=round(cooldown_left, 2),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _expire_window(self) -> None:
        cutoff = time.time() - self.config.window_sec
        while self._failure_ts and self._failure_ts[0] < cutoff:
            self._failure_ts.popleft()

    def _maybe_transition_to_half_open(self) -> None:
        if self.state != CircuitState.OPEN or self._opened_at is None:
            return
        if time.time() - self._opened_at >= self.config.cooldown_sec:
            self._probes_in_flight = 0
            self.metrics.consecutive_successes = 0
            self._set_state(CircuitState.HALF_OPEN)

    def _trip(self, now: float) -> None:
        self._opened_at = now
        self._probes_in_flight = 0
        self.metrics.opened_count += 1
        self._set_state(CircuitState.OPEN)
        logger.warning(
            f"circuit[{self.config.name}] OPEN "
            f"(failures_in_window={len(self._failure_ts)} "
            f"threshold={self.config.failure_threshold})"
        )

    def _set_state(self, new_state: CircuitState) -> None:
        if new_state == self.state:
            return
        old = self.state
        self.state = new_state
        self.metrics.last_state_change_at = time.time()
        logger.info(f"circuit[{self.config.name}] {old.value} → {new_state.value}")
        for cb in self._on_state_change:
            try:
                cb(self.config.name, old, new_state)
            except Exception:
                logger.exception("on_state_change callback failed")


class CircuitBreakerRegistry:
    """
    Manages one CircuitBreaker per tool name.
    Used by AdvancedToolRuntime.
    """

    def __init__(self, default_config: Optional[CircuitConfig] = None):
        self._default = default_config or CircuitConfig()
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._configs: Dict[str, CircuitConfig] = {}
        self._lock = asyncio.Lock()

    def configure(self, name: str, **kwargs: Any) -> None:
        values = {**self._default.__dict__, **kwargs, "name": name}
        values.pop("name", None)
        cfg = CircuitConfig(name=name, **values)
        self._configs[name] = cfg
        if name in self._breakers:
            self._breakers[name].config = cfg

    def get(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            cfg = self._configs.get(name) or CircuitConfig(
                name=name,
                failure_threshold=self._default.failure_threshold,
                success_threshold=self._default.success_threshold,
                window_sec=self._default.window_sec,
                cooldown_sec=self._default.cooldown_sec,
                half_open_max_probes=self._default.half_open_max_probes,
            )
            cfg.name = name
            self._breakers[name] = CircuitBreaker(cfg)
        return self._breakers[name]

    async def allow(self, name: str) -> bool:
        return await self.get(name).allow()

    async def record_success(self, name: str) -> None:
        await self.get(name).record_success()

    async def record_failure(self, name: str) -> None:
        await self.get(name).record_failure()

    def status(self) -> Dict[str, Any]:
        return {
            name: {
                "state": br.state.value,
                "failures_in_window": br.snapshot().failures_in_window,
                "probes_in_flight": br.snapshot().probes_in_flight,
                "cooldown_remaining_sec": br.snapshot().cooldown_remaining_sec,
                "metrics": br.snapshot().metrics,
                "config": br.snapshot().config,
            }
            for name, br in self._breakers.items()
        }

    async def force_open(self, name: str, reason: str = "manual") -> None:
        await self.get(name).force_open(reason)

    async def force_close(self, name: str, reason: str = "manual") -> None:
        await self.get(name).force_close(reason)

    async def reset_all(self) -> None:
        for br in self._breakers.values():
            await br.reset()


# Process-wide registry used by the advanced runtime
BREAKERS = CircuitBreakerRegistry(
    CircuitConfig(
        failure_threshold=5,
        success_threshold=2,
        window_sec=60.0,
        cooldown_sec=60.0,
        half_open_max_probes=2,
    )
)
