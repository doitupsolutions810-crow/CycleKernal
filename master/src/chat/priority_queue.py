"""
CycleKernel Priority Queue Logic — SKETCH
========================================
Complements bulkheads + circuit breakers.

Goal
----
Prevent low-urgency, long-running tools (scrape, pipeline, coding)
from starving high-urgency, short tools (get_mood, health, approve).

Model
-----
  • Each enqueued work item has a priority band + monotonic sequence.
  • Scheduler is fair *within* a band (FIFO) and strict *across* bands
    unless a starvation guard promotes aged low-priority items.
  • Integrates with bulkhead acquire: you only pull from the queue when
    the target tool's bulkhead has a free slot.

Priority bands (lower number = higher priority)
-----------------------------------------------
  0  CRITICAL   — circuit force, approvals, kill switches
  1  HIGH       — get_mood, health probes, user-facing chat turns
  2  NORMAL     — research, planning, coding
  3  LOW        — bulk pipeline, background scrape fan-out
  4  BEST_EFFORT— speculative / optional branches

Starvation guard
----------------
  If an item sits longer than `promote_after_sec`, its effective priority
  is raised by one band (clamped at CRITICAL). Stops LOW work from
  never running under sustained HIGH load.

This file is a sketch: interfaces + algorithms are real and testable;
wiring into AdvancedToolRuntime is intentionally left as a follow-up.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Awaitable, Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Priority bands
# ---------------------------------------------------------------------------

class Priority(IntEnum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BEST_EFFORT = 4


# Default mapping: tool name → priority band
TOOL_PRIORITY: Dict[str, Priority] = {
    "get_mood": Priority.HIGH,
    "terminal_execute": Priority.NORMAL,  # gated by approval; still not CRITICAL
    "research": Priority.NORMAL,
    "scrape": Priority.NORMAL,
    "planning": Priority.NORMAL,
    "coding": Priority.NORMAL,
    "pipeline": Priority.LOW,
}

# Operator / protocol actions (not tools, but queueable control plane work)
CONTROL_PRIORITY: Dict[str, Priority] = {
    "circuit_force_open": Priority.CRITICAL,
    "circuit_force_close": Priority.CRITICAL,
    "approve_tool": Priority.CRITICAL,
    "chat_turn": Priority.HIGH,
}


def priority_for_tool(name: str) -> Priority:
    return TOOL_PRIORITY.get(name, Priority.NORMAL)


# ---------------------------------------------------------------------------
# Queue item
# ---------------------------------------------------------------------------

@dataclass(order=True)
class QueueItem:
    """
    heapq orders by the tuple (effective_priority, seq).
    Non-ordered fields are excluded from comparison via compare=False.
    """
    effective_priority: int
    seq: int
    enqueued_at: float = field(compare=False)
    base_priority: Priority = field(compare=False)
    tool: str = field(compare=False, default="")
    call_id: str = field(compare=False, default="")
    payload: Dict[str, Any] = field(compare=False, default_factory=dict)
    future: Any = field(compare=False, default=None)  # asyncio.Future[Any]


# ---------------------------------------------------------------------------
# Priority queue + scheduler sketch
# ---------------------------------------------------------------------------

@dataclass
class PriorityQueueConfig:
    promote_after_sec: float = 15.0     # age before +1 band promotion
    max_promotions: int = 2             # max band steps an item may climb
    max_queue_depth: int = 128          # global depth; reject beyond this
    per_band_depth: Dict[int, int] = field(default_factory=lambda: {
        int(Priority.CRITICAL): 32,
        int(Priority.HIGH): 32,
        int(Priority.NORMAL): 48,
        int(Priority.LOW): 24,
        int(Priority.BEST_EFFORT): 16,
    })
    tick_sec: float = 0.05              # scheduler loop cadence


class PriorityWorkQueue:
    """
    Async priority queue with aging-based promotion.

    Producers:  await q.enqueue(tool, call_id, payload, priority=...)
    Consumer:   item = await q.dequeue()   # blocks until work available
    """

    def __init__(self, config: Optional[PriorityQueueConfig] = None):
        self.config = config or PriorityQueueConfig()
        self._heap: List[QueueItem] = []
        self._seq = itertools.count()
        self._cv = asyncio.Condition()
        self._depth_by_band: Dict[int, int] = {int(p): 0 for p in Priority}
        self._rejected = 0
        self._enqueued = 0
        self._dequeued = 0
        self._promotions = 0
        self._closed = False

    # ---- producer --------------------------------------------------------

    async def enqueue(
        self,
        tool: str,
        call_id: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: Optional[Priority] = None,
    ) -> asyncio.Future:
        """
        Enqueue work. Returns a Future resolved by the worker that runs it.
        Raises QueueFull if depth limits are exceeded.
        """
        band = priority if priority is not None else priority_for_tool(tool)
        async with self._cv:
            if self._closed:
                raise RuntimeError("queue closed")

            total = sum(self._depth_by_band.values())
            if total >= self.config.max_queue_depth:
                self._rejected += 1
                raise QueueFull(f"global depth {total} >= {self.config.max_queue_depth}")

            band_depth = self._depth_by_band[int(band)]
            band_limit = self.config.per_band_depth.get(int(band), 32)
            if band_depth >= band_limit:
                self._rejected += 1
                raise QueueFull(f"band {band.name} depth {band_depth} >= {band_limit}")

            loop = asyncio.get_event_loop()
            fut: asyncio.Future = loop.create_future()
            item = QueueItem(
                effective_priority=int(band),
                seq=next(self._seq),
                enqueued_at=time.time(),
                base_priority=band,
                tool=tool,
                call_id=call_id,
                payload=payload or {},
                future=fut,
            )
            heapq.heappush(self._heap, item)
            self._depth_by_band[int(band)] += 1
            self._enqueued += 1
            self._cv.notify()
            return fut

    # ---- consumer --------------------------------------------------------

    async def dequeue(self, timeout: Optional[float] = None) -> Optional[QueueItem]:
        """
        Pop the highest-priority (lowest band) oldest item.
        Applies aging promotions before pop.
        """
        deadline = None if timeout is None else time.time() + timeout
        async with self._cv:
            while not self._heap and not self._closed:
                if deadline is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        return None
                    try:
                        await asyncio.wait_for(self._cv.wait(), timeout=remaining)
                    except asyncio.TimeoutError:
                        return None
                else:
                    await self._cv.wait()

            if not self._heap:
                return None

            self._apply_promotions_unlocked()
            item = heapq.heappop(self._heap)
            self._depth_by_band[int(item.base_priority)] = max(
                0, self._depth_by_band[int(item.base_priority)] - 1
            )
            self._dequeued += 1
            return item

    # ---- aging / promotion ----------------------------------------------

    def _apply_promotions_unlocked(self) -> None:
        """
        Re-heap items whose age warrants a higher effective priority.
        Called under self._cv.
        """
        if not self._heap:
            return
        now = time.time()
        changed = False
        for item in self._heap:
            age = now - item.enqueued_at
            steps = min(
                int(age // self.config.promote_after_sec),
                self.config.max_promotions,
            )
            # effective = base - steps (lower is higher priority), floor at CRITICAL
            new_eff = max(int(Priority.CRITICAL), int(item.base_priority) - steps)
            if new_eff != item.effective_priority:
                item.effective_priority = new_eff
                changed = True
                self._promotions += 1
        if changed:
            heapq.heapify(self._heap)

    # ---- lifecycle / metrics --------------------------------------------

    async def close(self) -> None:
        async with self._cv:
            self._closed = True
            self._cv.notify_all()

    def stats(self) -> Dict[str, Any]:
        return {
            "depth": sum(self._depth_by_band.values()),
            "depth_by_band": {
                Priority(b).name: d for b, d in self._depth_by_band.items()
            },
            "enqueued": self._enqueued,
            "dequeued": self._dequeued,
            "rejected": self._rejected,
            "promotions": self._promotions,
            "closed": self._closed,
        }


class QueueFull(Exception):
    pass


# ---------------------------------------------------------------------------
# Scheduler sketch — ties queue to bulkhead acquire
# ---------------------------------------------------------------------------

# Type of the bulkhead "try acquire" hook the real system would inject.
BulkheadAcquire = Callable[[str], Awaitable[bool]]
BulkheadRelease = Callable[[str], Awaitable[None]]
WorkExecutor = Callable[[QueueItem], Awaitable[Any]]


class PriorityScheduler:
    """
    Worker loop sketch:

      while True:
          item = await queue.dequeue()
          if not await bulkhead.try_acquire(item.tool):
              # no capacity — re-queue at same priority (or soft-park)
              await queue.requeue(item)   # not implemented in sketch
              await asyncio.sleep(tick)
              continue
          try:
              result = await execute(item)
              item.future.set_result(result)
          except Exception as e:
              item.future.set_exception(e)
          finally:
              await bulkhead.release(item.tool)

    In this sketch, requeue is omitted; a production version would park
    items that cannot acquire capacity without busy-looping.
    """

    def __init__(
        self,
        queue: PriorityWorkQueue,
        acquire: BulkheadAcquire,
        release: BulkheadRelease,
        execute: WorkExecutor,
        workers: int = 4,
    ):
        self.queue = queue
        self.acquire = acquire
        self.release = release
        self.execute = execute
        self.workers = workers
        self._tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        for i in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(i), name=f"pq-worker-{i}"))

    async def stop(self) -> None:
        await self.queue.close()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _worker(self, worker_id: int) -> None:
        while True:
            item = await self.queue.dequeue(timeout=1.0)
            if item is None:
                if self.queue._closed:
                    return
                continue

            got = await self.acquire(item.tool)
            if not got:
                # SKETCH: simple soft-retry — production should park, not spin
                await asyncio.sleep(0.05)
                # Re-insert without changing base priority
                async with self.queue._cv:
                    heapq.heappush(self.queue._heap, item)
                    self.queue._depth_by_band[int(item.base_priority)] += 1
                    self.queue._cv.notify()
                continue

            try:
                result = await self.execute(item)
                if not item.future.done():
                    item.future.set_result(result)
            except Exception as e:
                if not item.future.done():
                    item.future.set_exception(e)
            finally:
                await self.release(item.tool)




# ---------------------------------------------------------------------------
# Code examples
# ---------------------------------------------------------------------------

async def example_basic_priority_order() -> None:
    """
    Minimal usage: enqueue mixed-priority work and dequeue in band order.

        HIGH  (get_mood)  before
        NORMAL (scrape)   before
        LOW   (pipeline)
    """
    q = PriorityWorkQueue()

    # Producers (order of enqueue does NOT control run order)
    fut_pipeline = await q.enqueue(
        tool="pipeline",
        call_id="call_pipe_1",
        payload={"goal": "build full report"},
        priority=Priority.LOW,
    )
    fut_mood = await q.enqueue(
        tool="get_mood",
        call_id="call_mood_1",
        payload={},
        priority=Priority.HIGH,
    )
    fut_scrape = await q.enqueue(
        tool="scrape",
        call_id="call_scrape_1",
        payload={"urls": ["https://example.com"]},
        priority=Priority.NORMAL,
    )

    # Consumer: always gets highest priority next
    first = await q.dequeue()
    second = await q.dequeue()
    third = await q.dequeue()

    assert first.tool == "get_mood"      # HIGH
    assert second.tool == "scrape"       # NORMAL
    assert third.tool == "pipeline"      # LOW

    # Resolve futures (workers would do this after execute)
    first.future.set_result({"mood": "neutral"})
    second.future.set_result({"pages_fetched": 1})
    third.future.set_result({"success": True})

    print("basic order OK:", first.tool, second.tool, third.tool)
    print("results:", await fut_mood, await fut_scrape, await fut_pipeline)


async def example_aging_promotion() -> None:
    """
    Starvation guard: a LOW item that waits long enough is promoted
    so it is not stuck forever behind a stream of HIGH work.
    """
    q = PriorityWorkQueue(PriorityQueueConfig(
        promote_after_sec=0.25,   # demo-friendly; production ~15s
        max_promotions=2,
    ))

    await q.enqueue("pipeline", "aged", {"goal": "old job"}, Priority.LOW)
    await asyncio.sleep(0.55)  # 2 promotion steps → effective priority climbs
    await q.enqueue("get_mood", "fresh", {}, Priority.HIGH)

    a = await q.dequeue()
    b = await q.dequeue()
    print(
        f"aging example → first={a.tool}(eff={a.effective_priority}) "
        f"second={b.tool}(eff={b.effective_priority})"
    )
    a.future.set_result("ok")
    b.future.set_result("ok")


async def example_queue_full_rejection() -> None:
    """Load shed when a band is at capacity."""
    q = PriorityWorkQueue(PriorityQueueConfig(
        max_queue_depth=10,
        per_band_depth={int(Priority.LOW): 2},  # only 2 LOW slots
    ))
    await q.enqueue("pipeline", "1", {}, Priority.LOW)
    await q.enqueue("pipeline", "2", {}, Priority.LOW)
    try:
        await q.enqueue("pipeline", "3", {}, Priority.LOW)
        print("ERROR: expected QueueFull")
    except QueueFull as e:
        print("queue full as expected:", e)
    print("stats:", q.stats())


async def example_scheduler_with_fake_bulkhead() -> None:
    """
    Sketch of PriorityScheduler + bulkhead acquire/release hooks.
    In production, acquire/release bind to formal bulkhead pools.
    """
    slots = {"get_mood": 2, "scrape": 1, "pipeline": 1}
    in_use = {"get_mood": 0, "scrape": 0, "pipeline": 0}

    async def acquire(tool: str) -> bool:
        if in_use.get(tool, 0) < slots.get(tool, 1):
            in_use[tool] = in_use.get(tool, 0) + 1
            return True
        return False

    async def release(tool: str) -> None:
        in_use[tool] = max(0, in_use.get(tool, 0) - 1)

    async def execute(item: QueueItem) -> Any:
        await asyncio.sleep(0.01)  # pretend work
        return {"tool": item.tool, "call_id": item.call_id, "ok": True}

    q = PriorityWorkQueue()
    sched = PriorityScheduler(q, acquire, release, execute, workers=2)
    await sched.start()

    futs = [
        await q.enqueue("pipeline", "p1", {}, Priority.LOW),
        await q.enqueue("get_mood", "m1", {}, Priority.HIGH),
        await q.enqueue("scrape", "s1", {"urls": ["https://x"]}, Priority.NORMAL),
        await q.enqueue("get_mood", "m2", {}, Priority.HIGH),
    ]
    results = await asyncio.gather(*futs)
    print("scheduler results:", results)
    print("queue stats:", q.stats())
    await sched.stop()


async def run_all_examples() -> None:
    print("--- example_basic_priority_order ---")
    await example_basic_priority_order()
    print("--- example_aging_promotion ---")
    await example_aging_promotion()
    print("--- example_queue_full_rejection ---")
    await example_queue_full_rejection()
    print("--- example_scheduler_with_fake_bulkhead ---")
    await example_scheduler_with_fake_bulkhead()


if __name__ == "__main__":
    asyncio.run(run_all_examples())
