"""
CycleKernel Bulkhead — resource isolation pools per tool
=======================================================
Complements circuit breakers (fail-fast) with capacity limits (noisy-neighbor isolation).

Each tool gets:
  • max_concurrent in-flight slots
  • optional queue depth (wait) or fail-fast when full
  • metrics: in_use, accepted, rejected, completed, wait_ms

Bulkhead rejects do NOT count as circuit failures.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Dict, List, Optional, Type, Union


@dataclass
class BulkheadConfig:
    max_concurrent: int = 4
    max_queue: int = 8  # 0 = fail-fast when no free slot
    acquire_timeout_sec: float = 5.0


DEFAULT_BULKHEADS: Dict[str, BulkheadConfig] = {
    "get_mood": BulkheadConfig(max_concurrent=8, max_queue=0, acquire_timeout_sec=1.0),
    "research": BulkheadConfig(max_concurrent=4, max_queue=8),
    "scrape": BulkheadConfig(max_concurrent=3, max_queue=4),
    "planning": BulkheadConfig(max_concurrent=4, max_queue=4),
    "coding": BulkheadConfig(max_concurrent=2, max_queue=4),
    "pipeline": BulkheadConfig(max_concurrent=2, max_queue=2),
    "terminal_execute": BulkheadConfig(max_concurrent=2, max_queue=2),
}


@dataclass
class BulkheadMetrics:
    accepted: int = 0
    rejected: int = 0
    completed: int = 0
    total_wait_ms: float = 0.0
    in_use: int = 0
    peak_in_use: int = 0

    def to_dict(self) -> Dict[str, Union[int, float]]:
        avg_wait: float = (
            (self.total_wait_ms / self.accepted) if self.accepted else 0.0
        )
        return {
            "in_use": self.in_use,
            "peak_in_use": self.peak_in_use,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "completed": self.completed,
            "avg_wait_ms": round(avg_wait, 2),
        }


class Bulkhead:
    """
    Semaphore-backed pool:
      - free slot → acquire immediately
      - full + max_queue==0 → reject
      - full + max_queue>0 → wait up to acquire_timeout_sec (bounded waiters)
    """

    name: str
    config: BulkheadConfig
    metrics: BulkheadMetrics

    def __init__(
        self,
        name: str,
        config: Optional[BulkheadConfig] = None,
    ) -> None:
        self.name = name
        self.config: BulkheadConfig = config or BulkheadConfig()
        self._sem: asyncio.Semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._waiters: int = 0
        self.metrics = BulkheadMetrics()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._cm_stack: List[bool] = []

    async def acquire(self) -> bool:
        """
        Acquire an execution slot.

        Returns:
            True if a slot was acquired, False if rejected (full / timeout).
        """
        start: float = time.time()
        cfg: BulkheadConfig = self.config

        # Fast path: free slot
        if self._sem._value > 0:  # noqa: SLF001
            await self._sem.acquire()
            async with self._lock:
                self.metrics.in_use += 1
                self.metrics.peak_in_use = max(
                    self.metrics.peak_in_use, self.metrics.in_use
                )
                self.metrics.accepted += 1
                self.metrics.total_wait_ms += (time.time() - start) * 1000.0
            return True

        # No free slot — fail-fast if no queue
        if cfg.max_queue == 0:
            async with self._lock:
                self.metrics.rejected += 1
            return False

        async with self._lock:
            if self._waiters >= cfg.max_queue:
                self.metrics.rejected += 1
                return False
            self._waiters += 1

        try:
            await asyncio.wait_for(
                self._sem.acquire(),
                timeout=cfg.acquire_timeout_sec,
            )
        except asyncio.TimeoutError:
            async with self._lock:
                self._waiters = max(0, self._waiters - 1)
                self.metrics.rejected += 1
            return False

        async with self._lock:
            self._waiters = max(0, self._waiters - 1)
            self.metrics.in_use += 1
            self.metrics.peak_in_use = max(
                self.metrics.peak_in_use, self.metrics.in_use
            )
            self.metrics.accepted += 1
            self.metrics.total_wait_ms += (time.time() - start) * 1000.0
        return True

    async def try_acquire(self) -> bool:
        """Non-blocking acquire (no queue wait)."""
        if self._sem._value <= 0:  # noqa: SLF001
            async with self._lock:
                self.metrics.rejected += 1
            return False
        return await self.acquire()

    async def release(self) -> None:
        """Release one execution slot."""
        async with self._lock:
            self.metrics.in_use = max(0, self.metrics.in_use - 1)
            self.metrics.completed += 1
        self._sem.release()

    # ------------------------------------------------------------------
    # Async context manager (nest-safe via acquisition stack)
    #   async with BULKHEADS.get("coding") as ok:
    #       if not ok:
    #           return  # rejected — no slot held
    #       await do_work()
    # ------------------------------------------------------------------

    async def __aenter__(self) -> bool:
        """Acquire a slot. Returns True if acquired, False if rejected."""
        acquired: bool = await self.acquire()
        self._cm_stack.append(acquired)
        return acquired

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        """Release only if this context successfully acquired a slot."""
        if not self._cm_stack:
            return None
        acquired: bool = self._cm_stack.pop()
        if acquired:
            await self.release()
        return None

    def snapshot(self) -> Dict[str, Any]:
        """Point-in-time status for operators / metrics exporters."""
        return {
            "name": self.name,
            "config": {
                "max_concurrent": self.config.max_concurrent,
                "max_queue": self.config.max_queue,
                "acquire_timeout_sec": self.config.acquire_timeout_sec,
            },
            "metrics": self.metrics.to_dict(),
            "available": self._sem._value,
            "waiters": self._waiters,
        }


class BulkheadRegistry:
    """Named registry of per-tool bulkheads."""

    def __init__(
        self,
        configs: Optional[Dict[str, BulkheadConfig]] = None,
    ) -> None:
        self._configs: Dict[str, BulkheadConfig] = dict(
            configs or DEFAULT_BULKHEADS
        )
        self._bulkheads: Dict[str, Bulkhead] = {}

    def get(self, name: str) -> Bulkhead:
        """Return (creating if needed) the bulkhead for ``name``."""
        if name not in self._bulkheads:
            cfg: BulkheadConfig = self._configs.get(name, BulkheadConfig())
            self._bulkheads[name] = Bulkhead(name, cfg)
        return self._bulkheads[name]

    def configure(self, name: str, **kwargs: Any) -> None:
        """Replace config for ``name`` and rebuild the bulkhead instance."""
        base: BulkheadConfig = self._configs.get(name, BulkheadConfig())
        max_concurrent = int(kwargs.get("max_concurrent", base.max_concurrent))
        max_queue = int(kwargs.get("max_queue", base.max_queue))
        acquire_timeout_sec = float(kwargs.get("acquire_timeout_sec", base.acquire_timeout_sec))
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if max_queue < 0:
            raise ValueError("max_queue cannot be negative")
        if acquire_timeout_sec <= 0:
            raise ValueError("acquire_timeout_sec must be positive")
        cfg = BulkheadConfig(
            max_concurrent=max_concurrent,
            max_queue=max_queue,
            acquire_timeout_sec=acquire_timeout_sec,
        )
        self._configs[name] = cfg
        self._bulkheads[name] = Bulkhead(name, cfg)

    def status(self) -> Dict[str, Dict[str, Any]]:
        """Snapshot of every known bulkhead."""
        for name in self._configs:
            self.get(name)
        return {name: bh.snapshot() for name, bh in self._bulkheads.items()}


BULKHEADS: BulkheadRegistry = BulkheadRegistry()
