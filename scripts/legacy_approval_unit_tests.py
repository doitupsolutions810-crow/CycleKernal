#!/usr/bin/env python3
"""Legacy/v2 policy parity, approval replay and downstream outcome tests."""
import asyncio
import os
import time
import unittest
from unittest.mock import patch

from tools import ToolCall, ToolRegistry, ToolSpec, tool_failure_reason, _tool_pipeline, _tool_coding
from tools_advanced import PENDING_APPROVALS, AdvancedToolRuntime, ToolTrace


def register(name="terminal_execute", handler=None):
    hits = []
    async def safe(args):
        hits.append(dict(args))
        return {"exit_code": 0, "stdout": "executed"}
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name=name, description="isolated inert unit handler",
        parameters={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "goal": {"type": "string"},
                "agent": {"type": "string"},
            },
            "required": ["content"] if name == "terminal_execute" else (
                ["agent"] if name == "spawn_agent" else ["goal"]
            ),
        }, handler=handler or safe,
    ))
    return reg, hits


class LegacyPolicyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        PENDING_APPROVALS.clear()

    def tearDown(self):
        PENDING_APPROVALS.clear()

    async def test_sensitive_tools_are_all_denied_before_approval(self):
        args_for = {
            "terminal_execute": {"content": "print('x')"},
            "coding": {"goal": "tiny"},
            "pipeline": {"goal": "tiny"},
            "spawn_agent": {"agent": "reasoning"},
            "sandbox_pipeline": {"goal": "tiny"},
        }
        for name, args in args_for.items():
            registry, calls = register(name)
            result = await registry.execute(ToolCall("request-" + name, name, args))
            self.assertFalse(result.success, name)
            self.assertEqual(result.error, "pending_approval", name)
            self.assertEqual(result.content["call_id"], "request-" + name)
            self.assertEqual(calls, [])

    async def test_original_payload_approved_exactly_once(self):
        reg, calls = register()
        original = ToolCall("bound-once", "terminal_execute", {"content": "safe"})
        changed = ToolCall("bound-once", "terminal_execute", {"content": "malicious"})
        first = await reg.execute(original)
        self.assertEqual(first.error, "pending_approval")
        PENDING_APPROVALS[original.id]["status"] = "approved"
        self.assertEqual((await reg.execute(changed)).error, "pending_approval")
        self.assertEqual(len(calls), 0)
        result = await reg.execute(original)
        self.assertTrue(result.success, result)
        self.assertEqual(len(calls), 1)
        self.assertEqual((await reg.execute(original)).error, "pending_approval")
        self.assertEqual(len(calls), 1)

    async def test_approval_consumed_cross_protocol(self):
        reg, calls = register()
        c = ToolCall("cross-protocol", "terminal_execute", {"content": "safe"})
        self.assertEqual((await reg.execute(c)).error, "pending_approval")
        PENDING_APPROVALS[c.id]["status"] = "approved"
        runtime = AdvancedToolRuntime(registry=reg)
        result = await runtime.execute_one(c, ToolTrace("cross-protocol"))
        self.assertTrue(result.success, result)
        self.assertEqual(len(calls), 1)
        self.assertEqual((await reg.execute(c)).error, "pending_approval")
        self.assertEqual(len(calls), 1)

    async def test_concurrent_retries_execute_at_most_once(self):
        reg, calls = register()
        tool = ToolCall("single-flight", "terminal_execute", {"content": "safe"})
        self.assertEqual((await reg.execute(tool)).error, "pending_approval")
        PENDING_APPROVALS[tool.id]["status"] = "approved"
        results = await asyncio.gather(*[reg.execute(tool) for _ in range(40)])
        self.assertEqual(sum(result.success for result in results), 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(result.success or result.error == "pending_approval"
                            for result in results))

    async def test_simultaneous_legacy_and_advanced_retries_share_single_approval(self):
        reg, calls = register()
        call = ToolCall("interleaved-approval", "terminal_execute", {"content": "safe"})
        self.assertEqual((await reg.execute(call)).error, "pending_approval")
        PENDING_APPROVALS[call.id]["status"] = "approved"
        advanced = AdvancedToolRuntime(registry=reg)
        results = await asyncio.gather(
            reg.execute(call),
            advanced.execute_one(call, ToolTrace("dual-protocol")),
        )
        self.assertEqual(sum(result.success for result in results), 1)
        self.assertEqual(len(calls), 1)

    async def test_expired_admin_approval_is_rejected_with_410(self):
        import main as chat
        call = ToolCall("expired-admin", "terminal_execute", {"content": "safe"})
        reg, _ = register()
        self.assertEqual((await reg.execute(call)).error, "pending_approval")
        PENDING_APPROVALS[call.id]["created_at"] -= 10000
        with self.assertRaises(chat.HTTPException) as exception:
            await chat.approve_tool(
                {"call_id": call.id, "approve": True},
                authorization="Bearer " + os.environ["CK_TOOL_APPROVAL_TOKEN"],
            )
        self.assertEqual(exception.exception.status_code, 410)
        self.assertNotIn(call.id, PENDING_APPROVALS)

    async def test_admin_listing_prunes_expired_and_retains_current(self):
        import main as chat
        reg, _ = register()
        for cid in ("stale-item", "current-item"):
            call = ToolCall(cid, "terminal_execute", {"content": cid})
            self.assertEqual((await reg.execute(call)).error, "pending_approval")
        PENDING_APPROVALS["stale-item"]["created_at"] -= 10000
        result = await chat.list_pending(
            authorization="Bearer " + os.environ["CK_TOOL_APPROVAL_TOKEN"]
        )
        self.assertNotIn("stale-item", result["pending"])
        self.assertIn("current-item", result["pending"])

    async def test_misconfigured_equal_role_tokens_fail_closed(self):
        import main as chat
        with patch.dict(os.environ, {
            "CK_TOOL_EXECUTION_TOKEN": "same-token",
            "CK_TOOL_APPROVAL_TOKEN": "same-token",
            "CK_TERMINAL_SERVICE_TOKEN": "distinct-service",
        }):
            for guard in (chat._require_execution_token, chat._require_approval_token):
                with self.assertRaises(chat.HTTPException) as exception:
                    guard("Bearer same-token")
                self.assertEqual(exception.exception.status_code, 503)

    async def test_missing_required_arguments_do_not_request_approval(self):
        reg, calls = register()
        result = await reg.execute(ToolCall("invalid", "terminal_execute", {}))
        self.assertFalse(result.success)
        self.assertIn("required", result.error)
        self.assertNotIn("invalid", PENDING_APPROVALS)
        self.assertFalse(calls)

    async def test_legacy_nonzero_exit_and_downstream_errors_fail_closed(self):
        for response in (
            {"exit_code": 124, "stderr": "TIMEOUT"},
            {"error": "forbidden", "status_code": 403},
            {"success": False, "detail": "no"},
            {"exit_code": "0"},
        ):
            async def handler(_args, response=response):
                return response
            reg, _ = register(handler=handler)
            c = ToolCall("fail-" + str(len(PENDING_APPROVALS)), "terminal_execute", {"content": "x"})
            self.assertEqual((await reg.execute(c)).error, "pending_approval")
            PENDING_APPROVALS[c.id]["status"] = "approved"
            result = await reg.execute(c)
            self.assertFalse(result.success, result)
            self.assertIsNotNone(result.error)
            self.assertEqual(result.content, response)

    async def test_advanced_nonzero_exit_fails_closed(self):
        async def fail(_args):
            return {"exit_code": 7, "stderr": "failed"}
        reg, _ = register(handler=fail)
        c = ToolCall("v2-error", "terminal_execute", {"content": "x"})
        self.assertEqual((await reg.execute(c)).error, "pending_approval")
        PENDING_APPROVALS[c.id]["status"] = "approved"
        result = await AdvancedToolRuntime(registry=reg).execute_one(c, ToolTrace("outcome"))
        self.assertFalse(result.success)
        self.assertIn("exit code", result.error)

    async def test_read_only_tool_does_not_require_approval(self):
        reg, calls = register(name="planning")
        result = await reg.execute(ToolCall("read", "planning", {"goal": "safe"}))
        self.assertTrue(result.success)
        self.assertEqual(len(calls), 1)
        self.assertEqual(PENDING_APPROVALS, {})


class OrchestratorForwardingTests(unittest.IsolatedAsyncioTestCase):
    async def test_coding_and_pipeline_forward_execution_token(self):
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"success": True, "stages": []}
        class FakeClient:
            def __init__(self):
                self.headers = []
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                return None
            async def post(self, _url, json=None, headers=None):
                self.headers.append(headers)
                return FakeResponse()
        client = FakeClient()
        with patch.dict(os.environ, {"CK_TOOL_EXECUTION_TOKEN": "mock-operator-secret"}):
            with patch("tools.httpx.AsyncClient", return_value=client):
                self.assertTrue((await _tool_coding({"goal": "x"}))["success"])
                self.assertTrue((await _tool_pipeline({"goal": "y"}))["success"])
        self.assertEqual(len(client.headers), 2)
        for header in client.headers:
            self.assertEqual(header["Authorization"], "Bearer mock-operator-secret")


if __name__ == "__main__":
    unittest.main(verbosity=2)
