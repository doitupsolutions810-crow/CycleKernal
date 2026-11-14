#!/usr/bin/env python3
"""Isolated CycleKernel advanced runtime regression tests, executed in chat container."""
import asyncio
import unittest

from bulkhead import BulkheadConfig, BulkheadRegistry
from tools import ToolCall, ToolRegistry, ToolSpec
from tools_advanced import (
    AdvancedToolRuntime, Middleware, PENDING_APPROVALS,
    ToolPolicy, ToolTrace, validate_args, request_approval, APPROVAL_TTL_SECONDS,
)


def make_runtime(name, handler=None, limit=100, approval=False, timeout=1.0, capacity=2):
    async def default_handler(args):
        return {"value": args["value"]}

    reg = ToolRegistry()
    reg.register(ToolSpec(
        name=name,
        description="Test-only inert tool",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=handler or default_handler,
    ))
    policy = ToolPolicy(
        timeout_sec=timeout, max_retries=0, max_concurrency=capacity,
        rate_limit_per_min=limit, requires_approval=approval,
        circuit_fail_threshold=100,
    )
    rt = AdvancedToolRuntime(registry=reg, policies={name: policy})
    rt.bulkheads = BulkheadRegistry({
        name: BulkheadConfig(
            max_concurrent=capacity, max_queue=0, acquire_timeout_sec=0.05,
        )
    })
    return rt


def call(name, suffix, value="ok"):
    return ToolCall(id=f"{name}-{suffix}", name=name, arguments={"value": value})


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def assert_pool_clean(self, rt, name, capacity=2):
        state = rt.bulkheads.get(name).snapshot()
        self.assertEqual(state["metrics"]["in_use"], 0, state)
        self.assertEqual(state["available"], capacity, state)
        self.assertEqual(state["metrics"]["accepted"], state["metrics"]["completed"], state)

    async def test_unknown_tools_do_not_allocate_global_capacity_state(self):
        name = "unit_known"
        rt = make_runtime(name)
        for i in range(600):
            result = await rt.execute_one(
                ToolCall(f"id-{i}", f"unknown_{i}", {"value": "x"}),
                ToolTrace("unknown-names"),
            )
            self.assertFalse(result.success)
            self.assertIn("unknown tool", result.error)
        self.assertEqual(rt.bulkheads._bulkheads, {})
        self.assertEqual(dict(rt.rates.hits), {})
        self.assertEqual(rt._semaphores, {})
        result = await rt.execute_one(call(name, "normal"), ToolTrace("recovery"))
        self.assertTrue(result.success)
        self.assert_pool_clean(rt, name)

    async def test_schema_rejections_release_capacity(self):
        name = "unit_schema"
        rt = make_runtime(name)
        for i in range(16):
            result = await rt.execute_one(ToolCall(f"invalid-{i}", name, {}), ToolTrace("schema"))
            self.assertFalse(result.success)
            self.assertIn("schema validation", result.error)
        self.assert_pool_clean(rt, name)
        result = await rt.execute_one(call(name, "recovery"), ToolTrace("schema"))
        self.assertTrue(result.success)
        self.assert_pool_clean(rt, name)

    async def test_rate_limit_rejections_release_capacity(self):
        name = "unit_rate"
        rt = make_runtime(name, limit=2)
        results = [await rt.execute_one(call(name, i), ToolTrace("rate")) for i in range(7)]
        self.assertEqual(sum(x.success for x in results), 2)
        self.assertTrue(all("rate limit" in x.error for x in results[2:]))
        self.assert_pool_clean(rt, name)

    async def test_approval_rejections_release_capacity(self):
        name = "unit_approval"
        rt = make_runtime(name, approval=True)
        try:
            results = [await rt.execute_one(call(name, i), ToolTrace("approval")) for i in range(8)]
            self.assertTrue(all(x.error == "pending_approval" for x in results))
            self.assert_pool_clean(rt, name)
        finally:
            for i in range(8):
                PENDING_APPROVALS.pop(f"{name}-{i}", None)

    async def test_middleware_denials_release_capacity(self):
        name = "unit_middleware"
        rt = make_runtime(name)
        async def deny(_call, _trace):
            return "policy-denied"
        rt.middleware.before.append(deny)
        results = [await rt.execute_one(call(name, i), ToolTrace("deny")) for i in range(10)]
        self.assertTrue(all("denied by middleware" in x.error for x in results))
        self.assert_pool_clean(rt, name)

    async def test_cancellation_releases_capacity(self):
        name = "unit_cancel"
        started = asyncio.Event()
        async def slow(_args):
            started.set()
            await asyncio.sleep(10)
            return {"done": True}
        rt = make_runtime(name, handler=slow, timeout=30)
        task = asyncio.create_task(rt.execute_one(call(name, "cancel"), ToolTrace("cancel")))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_pool_clean(rt, name)

    async def test_timeout_releases_capacity(self):
        name = "unit_timeout"
        async def slow(_args):
            await asyncio.sleep(0.25)
            return {"done": True}
        rt = make_runtime(name, handler=slow, timeout=0.02)
        result = await rt.execute_one(call(name, "timeout"), ToolTrace("timeout"))
        self.assertFalse(result.success)
        self.assert_pool_clean(rt, name)

    async def test_dag_failed_parent_blocks_dependents_but_not_peers(self):
        name = "unit_dag"
        observed = []
        async def handler(args):
            observed.append(args["value"])
            if args["value"] == "fail":
                raise RuntimeError("simulated")
            return {"ok": True}
        rt = make_runtime(name, handler=handler, capacity=4)
        plan = [
            {"id": "root", "tool": name, "arguments": {"value": "fail"}},
            {"id": "child", "tool": name, "arguments": {"value": "child"}, "depends_on": ["root"]},
            {"id": "grandchild", "tool": name, "arguments": {"value": "grandchild"}, "depends_on": ["child"]},
            {"id": "peer", "tool": name, "arguments": {"value": "peer"}},
        ]
        results = await rt.execute_dag(plan)
        by_id = {x.tool_call_id: x for x in results}
        self.assertFalse(by_id["root"].success)
        self.assertFalse(by_id["child"].success)
        self.assertFalse(by_id["grandchild"].success)
        self.assertTrue(by_id["peer"].success)
        self.assertIn("dependency failed", by_id["child"].error)
        self.assertEqual(sorted(observed), ["fail", "peer"])
        self.assert_pool_clean(rt, name, capacity=4)

    async def test_dag_cycle_is_bounded(self):
        name = "unit_cycle"
        rt = make_runtime(name)
        results = await asyncio.wait_for(rt.execute_dag([
            {"id": "a", "tool": name, "arguments": {"value": "a"}, "depends_on": ["b"]},
            {"id": "b", "tool": name, "arguments": {"value": "b"}, "depends_on": ["a"]},
        ]), timeout=2)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(not x.success for x in results))
        self.assert_pool_clean(rt, name)

    async def test_approval_cannot_be_reused_or_changed(self):
        cid = "unit-exact-once-approval"
        original = ToolCall(cid, "unit_gate", {"value": "safe"})
        changed = ToolCall(cid, "unit_gate", {"value": "dangerous"})
        try:
            self.assertFalse(await request_approval(original, ToolTrace("bind")))
            PENDING_APPROVALS[cid]["status"] = "approved"
            self.assertFalse(await request_approval(changed, ToolTrace("bind")))
            self.assertTrue(await request_approval(original, ToolTrace("bind")))
            self.assertFalse(await request_approval(original, ToolTrace("bind")))
            self.assertEqual(PENDING_APPROVALS[cid]["status"], "pending")
        finally:
            PENDING_APPROVALS.pop(cid, None)

    async def test_approval_expiry_fails_closed(self):
        cid = "unit-expired-approval"
        tool = ToolCall(cid, "unit_gate", {"value": "safe"})
        try:
            self.assertFalse(await request_approval(tool, ToolTrace("expiry")))
            PENDING_APPROVALS[cid]["status"] = "approved"
            PENDING_APPROVALS[cid]["created_at"] -= APPROVAL_TTL_SECONDS + 1
            self.assertFalse(await request_approval(tool, ToolTrace("expiry")))
            self.assertEqual(PENDING_APPROVALS[cid]["status"], "pending")
        finally:
            PENDING_APPROVALS.pop(cid, None)

    def test_json_types_reject_bool_as_numeric(self):
        self.assertIsNotNone(validate_args({
            "type": "object", "properties": {"n": {"type": "integer"}},
        }, {"n": True}))
        self.assertIsNotNone(validate_args({
            "type": "object", "properties": {"n": {"type": "number"}},
        }, {"n": False}))
        self.assertIsNotNone(validate_args({"type": "object"}, []))


if __name__ == "__main__":
    unittest.main(verbosity=2)
