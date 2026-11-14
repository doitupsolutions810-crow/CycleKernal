#!/usr/bin/env python3
"""Orchestrator fail-closed outcome tests with mocked dependency responses."""
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from orchestrator import main as orch


class Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
    def json(self):
        return self._body


class FakeClient:
    def __init__(self, terminal_status, terminal_body):
        self.status = terminal_status
        self.body = terminal_body
        self.feedback = []
        self.headers = []
        self.terminal_count = 0
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        return None
    async def get(self, url, **kwargs):
        return Response(200, {"mood": "neutral"})
    async def post(self, url, json=None, headers=None, **kwargs):
        if url.endswith("/v1/execute"):
            self.terminal_count += 1
            self.headers.append(headers)
            return Response(self.status, self.body)
        if url.endswith("/v1/feedback"):
            self.feedback.append(json)
            return Response(200, {"ok": True})
        raise AssertionError("unexpected URL " + url)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.env = patch.dict(os.environ, {
            "CK_TOOL_EXECUTION_TOKEN": "unit-exec-secret",
            "CK_TERMINAL_SERVICE_TOKEN": "unit-terminal-secret",
        })
        self.env.start()
        def result(output):
            return SimpleNamespace(
                success=True, output=output, duration_ms=1, agent="test"
            )
        self.patchers = [
            patch.object(orch.research_agent, "run",
                         new=AsyncMock(return_value=result({"sources": []}))),
            patch.object(orch.planning_agent, "run",
                         new=AsyncMock(return_value=result({"plan": ["step"]}))),
            patch.object(orch.coding_agent, "run",
                         new=AsyncMock(return_value=result({
                             "filename": "unit.py",
                             "content": "print('ok')",
                             "run_command": "python unit.py",
                         }))),
        ]
        for item in self.patchers:
            item.start()
    async def asyncTearDown(self):
        for item in reversed(self.patchers):
            item.stop()
        self.env.stop()

    async def exercise(self, status, body, auto_execute=True):
        client = FakeClient(status, body)
        with patch.object(orch.httpx, "AsyncClient", return_value=client):
            out = await orch.run_pipeline(
                orch.GoalRequest(goal="mocked pipeline", auto_execute=auto_execute),
                authorization="Bearer unit-exec-secret",
            )
        return out, client

    async def test_normal_success_propagates_to_feedback(self):
        result, client = await self.exercise(200, {
            "exit_code": 0, "stdout": "ok", "stderr": "",
        })
        self.assertTrue(result.success)
        self.assertTrue(result.stages[-1]["success"])
        self.assertTrue(client.feedback[-1]["success"])
        self.assertEqual(client.terminal_count, 1)
        self.assertEqual(client.headers[0]["Authorization"], "Bearer unit-terminal-secret")

    async def test_nonzero_exit_fails_pipeline_and_feedback(self):
        result, client = await self.exercise(200, {
            "exit_code": 7, "stderr": "intentional",
        })
        self.assertFalse(result.success)
        self.assertFalse(result.stages[-1]["success"])
        self.assertFalse(client.feedback[-1]["success"])

    async def test_http_error_fails_pipeline_and_feedback(self):
        result, client = await self.exercise(403, {"detail": "forbidden"})
        self.assertFalse(result.success)
        self.assertFalse(result.stages[-1]["success"])
        self.assertFalse(client.feedback[-1]["success"])

    async def test_missing_exit_code_fails_closed(self):
        result, client = await self.exercise(200, {"status": "unexpected"})
        self.assertFalse(result.success)
        self.assertFalse(result.stages[-1]["success"])
        self.assertFalse(client.feedback[-1]["success"])

    async def test_execution_disabled_does_not_dispatch_terminal(self):
        result, client = await self.exercise(200, {}, auto_execute=False)
        self.assertTrue(result.success)
        self.assertEqual(client.terminal_count, 0)
        self.assertTrue(client.feedback[-1]["success"])

    async def test_duplicate_service_and_execution_tokens_fail_closed(self):
        with patch.dict(os.environ, {
            "CK_TOOL_EXECUTION_TOKEN": "duplicate-value",
            "CK_TERMINAL_SERVICE_TOKEN": "duplicate-value",
        }):
            with self.assertRaises(orch.HTTPException) as ctx:
                await orch.run_pipeline(
                    orch.GoalRequest(goal="must not execute"),
                    authorization="Bearer duplicate-value",
                )
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_missing_execution_token_fails_before_agents_run(self):
        with patch.dict(os.environ, {"CK_TOOL_EXECUTION_TOKEN": ""}):
            with self.assertRaises(orch.HTTPException) as ctx:
                await orch.run_pipeline(
                    orch.GoalRequest(goal="must not run"), authorization=None
                )
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main(verbosity=2)
