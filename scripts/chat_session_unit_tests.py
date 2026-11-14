#!/usr/bin/env python3
"""Chat session isolation and bounded-memory regression suite inside chat container."""
import asyncio
import os
from unittest import IsolatedAsyncioTestCase, TestCase, main
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError
import main as chat


class FakeClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, *_args, **_kwargs):
        return None


class SessionCacheTests(TestCase):
    def setUp(self):
        chat.SESSIONS.clear()

    def tearDown(self):
        chat.SESSIONS.clear()

    def test_lru_evicts_oldest_sessions_at_fixed_capacity(self):
        for i in range(chat.MAX_SESSIONS + 32):
            chat._save_session(f"sid-{i}", [{"role": "user", "content": "safe"}])
        self.assertEqual(len(chat.SESSIONS), chat.MAX_SESSIONS)
        self.assertNotIn("sid-0", chat.SESSIONS)
        self.assertIn("sid-" + str(chat.MAX_SESSIONS + 31), chat.SESSIONS)

    def test_defensive_copy_prevents_session_mutation(self):
        chat._save_session("copy", [{"role": "user", "content": "original"}])
        loaded = chat._load_session("copy")
        loaded[0]["content"] = "changed"
        self.assertEqual(chat._load_session("copy")[0]["content"], "original")

    def test_message_depth_and_retained_payload_are_bounded(self):
        messages = [{"role": "user", "content": str(i) + "X" * 100000}
                    for i in range(50)]
        chat._save_session("bounded", messages)
        self.assertEqual(len(chat._load_session("bounded")), chat.MAX_SESSION_MESSAGES)
        self.assertTrue(all(len(m["content"]) <= chat.MAX_STORED_CONTENT_CHARS
                            for m in chat._load_session("bounded")))

    def test_invalid_session_id_or_huge_history_rejected(self):
        with self.assertRaises(ValidationError):
            chat.ChatRequest(message="hello", session_id="x" * 129)
        with self.assertRaises(ValidationError):
            chat.ChatRequest(message="hello", session_id="")
        with self.assertRaises(ValidationError):
            chat.ChatRequest(message="hello", history=[
                {"role": "user", "content": "x"} for _ in range(65)
            ])


class SessionAccessTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        chat.SESSIONS.clear()
        self.mood = patch.object(chat, "get_mood", new=AsyncMock(
            return_value={"mood": "neutral", "system_prompt_override": ""}
        ))
        self.reason = patch.object(chat, "reason", new=AsyncMock(
            return_value={"tool": None, "answer": "safe-response"}
        ))
        self.client = patch.object(chat.httpx, "AsyncClient", return_value=FakeClient())
        self.mood.start()
        self.reason.start()
        self.client.start()

    async def asyncTearDown(self):
        self.client.stop()
        self.reason.stop()
        self.mood.stop()
        chat.SESSIONS.clear()

    async def test_public_chat_does_not_persist_shared_history(self):
        for _ in range(3):
            result = await chat.chat(chat.ChatRequest(
                message="public read-only", session_id="predictable-default",
                auto_spawn=False, use_tool_protocol=False,
            ), authorization=None)
            self.assertEqual(result.reply, "safe-response")
        self.assertNotIn("predictable-default", chat.SESSIONS)

    async def test_public_chat_cannot_read_operator_history(self):
        chat._save_session("shared-id", [{"role": "user", "content": "private-marker"}])
        await chat.chat(chat.ChatRequest(
            message="public", session_id="shared-id", auto_spawn=False,
            use_tool_protocol=False,
        ), authorization=None)
        # The mocked reasoner receives history as a keyword argument.
        self.assertNotIn("private-marker", str(chat.reason.call_args.kwargs.get("history", [])))
        self.assertEqual(chat._load_session("shared-id")[0]["content"], "private-marker")

    async def test_duplicate_role_tokens_do_not_grant_session_access(self):
        chat._save_session("collision", [
            {"role": "user", "content": "private-do-not-read"},
        ])
        with patch.dict(os.environ, {
            "CK_TOOL_EXECUTION_TOKEN": "reused-credential",
            "CK_TOOL_APPROVAL_TOKEN": "reused-credential",
            "CK_TERMINAL_SERVICE_TOKEN": "separate-internal",
        }):
            await chat.chat(chat.ChatRequest(
                message="read-only under collision",
                session_id="collision", auto_spawn=False,
                use_tool_protocol=False,
            ), authorization="Bearer reused-credential")
        self.assertNotIn("private-do-not-read",
                         str(chat.reason.call_args.kwargs.get("history", [])))
        self.assertEqual(chat._load_session("collision")[0]["content"],
                         "private-do-not-read")

    async def test_concurrent_authorized_turns_are_not_lost(self):
        async def delayed_reason(message, **_kwargs):
            await asyncio.sleep(0.03)
            return {"tool": None, "answer": "reply:" + message}

        chat.reason.side_effect = delayed_reason
        with patch.dict(os.environ, {"CK_TOOL_EXECUTION_TOKEN": "unit-execution-secret"}):
            await asyncio.gather(*[
                chat.chat(chat.ChatRequest(
                    message=f"turn-{i}", session_id="parallel",
                    auto_spawn=False, use_tool_protocol=False,
                ), authorization="Bearer unit-execution-secret")
                for i in range(12)
            ])
        history = chat._load_session("parallel")
        self.assertEqual(len(history), 24)
        actual = {x["content"] for x in history if x["role"] == "user"}
        self.assertEqual(actual, {f"turn-{i}" for i in range(12)})

    async def test_authorized_session_persists_bounded_history(self):
        with patch.dict(os.environ, {"CK_TOOL_EXECUTION_TOKEN": "unit-execution-secret"}):
            req = chat.ChatRequest(message="authorized", session_id="trusted",
                                   auto_spawn=False, use_tool_protocol=False)
            await chat.chat(req, authorization="Bearer unit-execution-secret")
            self.assertIn("trusted", chat.SESSIONS)
            self.assertEqual(chat._load_session("trusted")[-1]["content"], "safe-response")


if __name__ == "__main__":
    main(verbosity=2)
