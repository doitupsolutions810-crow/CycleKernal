"""LLM_BASE_URL contract tests for the ChatBot reasoner.

Run: python3 master/src/chat/test_reasoner_llm.py
Does not call a live model. Proves the production URL path and the fallback.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

CHAT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CHAT_DIR))

os.environ.pop("LLM_BASE_URL", None)
os.environ.pop("LLM_API_KEY", None)

import reasoner  # noqa: E402


def test_empty_base_url_skips_network():
    reasoner.LLM_BASE_URL = ""
    assert asyncio.run(reasoner.call_llm([{"role": "user", "content": "hi"}])) == ""


def test_completions_path_is_openai_compatible():
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{\"tool\": null, \"answer\": \"ok\"}"}}]}

    class FakeClient:
        def __init__(self, timeout=0):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    reasoner.LLM_BASE_URL = "http://llm.internal:8000"
    reasoner.LLM_API_KEY = "test-key"
    reasoner.LLM_MODEL = "colony-reasoner"
    reasoner.httpx.AsyncClient = FakeClient
    raw = asyncio.run(reasoner.call_llm([{"role": "user", "content": "plan a migration"}], mood_override="convergent"))
    assert raw.startswith("{")
    assert captured["url"] == "http://llm.internal:8000/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == "colony-reasoner"
    assert "convergent" in captured["json"]["messages"][0]["content"]


def test_reason_falls_back_when_base_url_missing():
    reasoner.LLM_BASE_URL = ""
    decision = asyncio.run(reasoner.reason("write code for a mood function"))
    assert decision["source"] == "local_reasoner"
    assert decision["tool"] == "coding"


def test_reason_uses_custom_llm_when_configured():
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "{\"tool\": \"planning\", \"args\": {\"goal\": \"x\"}, \"reason\": \"llm\"}"}}]}

    class FakeClient:
        def __init__(self, timeout=0):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            return FakeResponse()

    reasoner.LLM_BASE_URL = "https://llm.example"
    reasoner.LLM_API_KEY = ""
    reasoner.httpx.AsyncClient = FakeClient
    decision = asyncio.run(reasoner.reason("hello colony"))
    assert decision["source"] == "custom_llm"
    assert decision["tool"] == "planning"


if __name__ == "__main__":
    test_empty_base_url_skips_network()
    test_completions_path_is_openai_compatible()
    test_reason_falls_back_when_base_url_missing()
    test_reason_uses_custom_llm_when_configured()
    print("reasoner LLM_BASE_URL contract: 4 passed")
