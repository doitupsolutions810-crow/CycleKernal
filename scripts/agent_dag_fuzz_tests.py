#!/usr/bin/env python3
"""Deterministic seeded DAG, dependency and schema fuzz regressions."""
import asyncio
import random
import unittest
from collections import Counter

from bulkhead import BulkheadConfig, BulkheadRegistry
from tools import ToolCall, ToolRegistry, ToolSpec
from tools_advanced import (
    AdvancedToolRuntime, ToolPolicy, ToolTrace, _approval_signature, validate_args,
)

SEED = 0xC1C1E42


def runtime(observed):
    registry = ToolRegistry()
    async def handler(args):
        observed.append(args["id"])
        await asyncio.sleep(0)
        if args.get("fail", False):
            raise ValueError("intentional seeded handler failure")
        return {"id": args["id"], "ok": True}
    registry.register(ToolSpec(
        name="dag_probe", description="inert deterministic DAG probe",
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "fail": {"type": "boolean"},
            },
            "required": ["id"],
        },
        handler=handler,
    ))
    policy = ToolPolicy(
        timeout_sec=4, max_retries=0, max_concurrency=32,
        rate_limit_per_min=1_000_000, circuit_fail_threshold=1_000_000,
    )
    rt = AdvancedToolRuntime(registry=registry, policies={"dag_probe": policy})
    rt.bulkheads = BulkheadRegistry({
        "dag_probe": BulkheadConfig(
            max_concurrent=32, max_queue=64, acquire_timeout_sec=2,
        )
    })
    return rt


class DagFuzzTests(unittest.IsolatedAsyncioTestCase):
    async def test_180_random_acyclic_graphs_propagate_failures(self):
        rng = random.Random(SEED)
        observed = []
        rt = runtime(observed)
        cases = 0
        total_nodes = 0
        for case in range(180):
            size = rng.randint(1, 24)
            plan = []
            expected = {}
            should_execute = set()
            for i in range(size):
                identifier = f"seed-{case}-node-{i}"
                candidates = [node["id"] for node in plan]
                selected = rng.sample(candidates, rng.randint(0, min(4, len(candidates))))
                fail = rng.random() < 0.21
                deps_ok = all(expected[dependency] for dependency in selected)
                expected[identifier] = deps_ok and not fail
                if deps_ok:
                    should_execute.add(identifier)
                plan.append({
                    "id": identifier, "tool": "dag_probe",
                    "arguments": {"id": identifier, "fail": fail},
                    "depends_on": selected,
                })
            before = len(observed)
            results = await rt.execute_dag(plan, ToolTrace(f"seed-case-{case}"))
            actual = {result.tool_call_id: result for result in results}
            self.assertEqual(len(actual), size, f"trial {case} lost DAG node")
            for identifier in expected:
                self.assertEqual(actual[identifier].success, expected[identifier],
                                 f"incorrect dependency handling in trial {case}: {identifier}")
            self.assertEqual(Counter(observed[before:]), Counter(should_execute),
                             f"blocked agent dispatched unexpectedly in trial {case}")
            cases += 1
            total_nodes += size
        self.assertEqual(cases, 180)
        self.assertGreater(total_nodes, 1600)
        self.assertEqual(rt.bulkheads.get("dag_probe").snapshot()["metrics"]["in_use"], 0)

    async def test_cycle_and_missing_dependencies_fail_closed_but_peers_execute(self):
        for suffix in range(60):
            seen = []
            rt = runtime(seen)
            prefix = f"cycle-{suffix}"
            plan = [
                {"id": prefix + "-peer", "tool": "dag_probe",
                 "arguments": {"id": prefix + "-peer"}, "depends_on": []},
                {"id": prefix + "-left", "tool": "dag_probe",
                 "arguments": {"id": prefix + "-left"}, "depends_on": [prefix + "-right"]},
                {"id": prefix + "-right", "tool": "dag_probe",
                 "arguments": {"id": prefix + "-right"}, "depends_on": [prefix + "-left"]},
                {"id": prefix + "-child", "tool": "dag_probe",
                 "arguments": {"id": prefix + "-child"}, "depends_on": [prefix + "-left"]},
                {"id": prefix + "-missing", "tool": "dag_probe",
                 "arguments": {"id": prefix + "-missing"}, "depends_on": [prefix + "-absent"]},
            ]
            results = await rt.execute_dag(plan)
            self.assertEqual(len(results), len(plan))
            self.assertEqual(seen, [prefix + "-peer"])
            self.assertTrue(next(x for x in results if x.tool_call_id == prefix + "-peer").success)
            for row in results:
                if row.tool_call_id != prefix + "-peer":
                    self.assertFalse(row.success)
                    self.assertIn("unresolved", row.error)

    async def test_result_order_stable_under_parallel_completion(self):
        observed = []
        rt = runtime(observed)
        calls = [ToolCall(f"order-{i}", "dag_probe", {"id": f"order-{i}"})
                 for i in range(30)]
        results = await rt.execute_parallel(calls)
        self.assertEqual([x.tool_call_id for x in results], [x.id for x in calls])
        self.assertTrue(all(x.success for x in results))
        self.assertEqual(rt.bulkheads.get("dag_probe").snapshot()["metrics"]["in_use"], 0)

    def test_approval_binding_canonicalizes_object_order_not_payload(self):
        one = ToolCall("i", "terminal_execute", {"a": 1, "b": ["safe", 2]})
        reordered = ToolCall("i", "terminal_execute", {"b": ["safe", 2], "a": 1})
        changed = ToolCall("i", "terminal_execute", {"b": ["safe", 3], "a": 1})
        renamed = ToolCall("i", "coding", {"a": 1, "b": ["safe", 2]})
        self.assertEqual(_approval_signature(one), _approval_signature(reordered))
        self.assertNotEqual(_approval_signature(one), _approval_signature(changed))
        self.assertNotEqual(_approval_signature(one), _approval_signature(renamed))

    def test_schema_rejects_boolean_as_integer_or_number(self):
        for expected in ("integer", "number"):
            schema = {"type": "object", "properties": {"n": {"type": expected}},
                      "required": ["n"]}
            for bad in (True, False, "17", None, [], {}):
                self.assertIsNotNone(validate_args(schema, {"n": bad}), (expected, bad))
            for good in (0, 1, -123):
                self.assertIsNone(validate_args(schema, {"n": good}))
            if expected == "number":
                self.assertIsNone(validate_args(schema, {"n": 2.5}))

    def test_list_schema_validates_each_item(self):
        schema = {"type": "object", "required": ["values"],
                  "properties": {"values": {"type": "array",
                                            "items": {"type": "string"}}}}
        for bad in ([1], [True], ["good", None], "string", None):
            self.assertIsNotNone(validate_args(schema, {"values": bad}))
        self.assertIsNone(validate_args(schema, {"values": ["one", "two"]}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
