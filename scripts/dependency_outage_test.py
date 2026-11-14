#!/usr/bin/env python3
"""Exercise degraded-mode behavior of chat + tool gateway during CI service outages."""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080").rstrip("/")
mode = sys.argv[2] if len(sys.argv) > 2 else "recovered"
chat = base + "/api/chat"

def request(path, payload=None, authenticated=False):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if authenticated:
        headers["Authorization"] = "Bearer " + os.environ["CK_TOOL_EXECUTION_TOKEN"]
    req = urllib.request.Request(chat + path, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def assert_chat_healthy(expected_mood=None):
    status, health = request("/health")
    assert status == 200 and health.get("status") == "chat-online", (status, health)
    if expected_mood:
        assert health.get("mood") == expected_mood, health
    status, response = request("/v1/chat", {
        "message": "dependency fault injection " + mode,
        "auto_spawn": False,
        "use_tool_protocol": False,
        "session_id": "fault-" + uuid.uuid4().hex,
    })
    assert status == 200 and response.get("reply"), (status, response)
    if expected_mood:
        assert response.get("mood") == expected_mood, response
    print("PASS public read-only chat during " + mode)


def invoke_terminal():
    return request("/v1/tools/execute", {
        "tool_calls": [{
            "id": uuid.uuid4().hex, "type": "function",
            "function": {"name": "terminal_execute",
                         "arguments": json.dumps({
                             "filename": "fault-recovery.py",
                             "content": "print('fault-recovery-ok')\n",
                             "timeout_sec": 5,
                         })}
        }]
    }, authenticated=True)


assert mode in ("bridge-down", "terminal-down", "recovered"), mode
if mode == "bridge-down":
    assert_chat_healthy(expected_mood="neutral")
elif mode == "terminal-down":
    assert_chat_healthy()
    status, result = invoke_terminal()
    rows = result.get("results", []) if isinstance(result, dict) else []
    assert status == 200 and rows and rows[0].get("success") is False, (status, result)
    print("PASS terminal outage surfaces as structured tool failure")
else:
    assert_chat_healthy()
    status, result = invoke_terminal()
    rows = result.get("results", []) if isinstance(result, dict) else []
    assert status == 200 and rows and rows[0].get("success") is True, (status, result)
    assert "fault-recovery-ok" in rows[0].get("content", {}).get("stdout", ""), result
    print("PASS tool execution recovered after dependency restart")
