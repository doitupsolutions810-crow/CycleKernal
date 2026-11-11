#!/usr/bin/env python3
"""Bounded HTTP edge tests for the CycleKernel local Compose/Swarm front door."""
from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:8080"
CHAT = BASE + "/api/chat"
COLONY = BASE + "/api/colony"
RESULTS: list[tuple[str, bool, str]] = []


def request(url: str, body=None, method: str | None = None, timeout: float = 20):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
            try:
                parsed = json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                parsed = raw.decode(errors="replace")
            return res.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            parsed = raw.decode(errors="replace")
        return exc.code, parsed
    except Exception as exc:  # surfaced in report
        return 0, {"exception": repr(exc)}


def check(name: str, condition: bool, details=""):
    RESULTS.append((name, bool(condition), str(details)[:240]))


def tool(name: str, args: dict, call_id: str | None = None, timeout=40):
    return request(CHAT + "/v1/tools/execute", {
        "tool_calls": [{
            "id": call_id or uuid.uuid4().hex,
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)},
        }]
    }, timeout=timeout)


# Health, schema, and dependency API checks.
for path in ("/health", "/api/simulation/health", "/api/monitoring/health", "/api/colony/health"):
    status, payload = request(BASE + path)
    check("GET " + path, status == 200, f"status={status} payload={payload}")

status, schemas = request(CHAT + "/v1/tools")
known_tools = {item["function"]["name"] for item in schemas.get("tools", [])} if isinstance(schemas, dict) else set()
check("tool schemas", status == 200 and {"spawn_agent", "sandbox_pipeline", "terminal_execute"} <= known_tools, sorted(known_tools))

# Chat request schema, modes, message/session boundaries.
status, payload = request(CHAT + "/v1/chat", {})
check("missing message validation", status == 422, f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": 42})
check("wrong message type validation", status == 422, f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": "bad session", "session_id": 12})
check("wrong session type validation", status == 422, f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": "bad history", "history": [{"role": "bad-role", "content": 7}]})
check("invalid history fields validation", status == 422, f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": "bad history shape", "history": ["not-an-object"]})
check("invalid history shape validation", status == 422, f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": "session boundary", "session_id": "s" * 4096, "auto_spawn": False, "use_tool_protocol": False})
check("long session id handled", status in (200, 422), f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": "mode probe", "auto_spawn": False, "use_tool_protocol": True, "protocol_version": "v1", "max_rounds": 0})
check("v1 protocol and zero rounds", status == 200, f"status={status}")
status, payload = request(CHAT + "/v1/chat", {"message": "mode probe", "auto_spawn": False, "use_tool_protocol": True, "protocol_version": "unexpected", "tool_choice": "unexpected"})
check("unknown protocol fallback", status == 200, f"status={status}")
for message, sid in (("edge smoke", "edge-smoke"), ("x" * 10000, "edge-large"), ("z" * 64000, "edge-64k")):
    status, payload = request(CHAT + "/v1/chat", {
        "message": message, "session_id": sid, "auto_spawn": False, "use_tool_protocol": False,
    })
    check("chat " + sid, status == 200 and payload.get("session_id") == sid, f"status={status}")

# Direct tool protocol error handling and useful tools.
status, result = request(CHAT + "/v1/tools/execute", {"tool_calls": [{
    "id": "bad-json", "type": "function", "function": {"name": "planning", "arguments": "{bad"}
}]})
check("malformed tool JSON", status == 200 and result["results"][0]["success"] is False, result)
status, result = request(CHAT + "/v1/tools/execute", {"tool_calls": [{
    "id": "missing-args", "type": "function", "function": {"name": "planning", "arguments": "{}"}
}]})
check("missing required tool arg", status == 200 and result["results"][0]["success"] is False, result)
status, result = tool("not-a-tool", {})
check("unknown tool", status == 200 and result["results"][0]["success"] is False, result)
status, result = tool("planning", {"goal": "bounded edge-test plan"})
check("planning tool", status == 200 and result["results"][0]["success"] is True, result)

# All specialist agents must load and return a structured result.
for agent in ("reasoning", "planning", "research", "coding", "artifact", "container"):
    status, result = tool("spawn_agent", {
        "agent": agent,
        "goal": "Produce a bounded integration-test outline",
        "task": {"goal": "Produce a bounded integration-test outline", "language": "python"},
    }, timeout=30)
    entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
    check("agent " + agent, status == 200 and entry.get("success") is True, entry)

# Server agent status is safe and should not launch a new host listener.
status, result = tool("spawn_agent", {"agent": "server", "action": "status", "name": "edge-test-runtime"}, timeout=15)
entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
check("server agent status", status == 200 and entry.get("success") is True, entry)

# Exercise the full local agent pipeline without starting a generated server.
status, result = tool("sandbox_pipeline", {
    "goal": "Produce a tiny Python integration-check artifact",
    "host": False,
}, timeout=60)
entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
check("sandbox pipeline without host server", status == 200 and entry.get("success") is True, entry)

# Runner input guards and bounded timeout. Commands are fixed safe Python snippets.
status, result = tool("terminal_execute", {
    "filename": "edge-check.py", "content": "print('edge-ok')\n", "timeout_sec": 5,
}, timeout=15)
entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
check("terminal normal execution", status == 200 and entry.get("success") is True and "edge-ok" in str(entry), entry)
status, result = tool("terminal_execute", {
    "filename": "../edge-escape.py", "content": "print('must not run')\n", "timeout_sec": 2,
}, timeout=10)
entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
check("terminal traversal rejected", status == 200 and entry.get("content", {}).get("status_code") == 400, entry)
status, result = tool("terminal_execute", {
    "filename": "/tmp/edge-absolute.py", "content": "print('must not run')\\n", "timeout_sec": 2,
}, timeout=10)
entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
check("terminal absolute path rejected", status == 200 and entry.get("content", {}).get("status_code") == 400, entry)
status, result = tool("terminal_execute", {
    "filename": "edge-timeout.py", "content": "import time; time.sleep(4)\n",
    "command": "python -c 'import time; time.sleep(4)'", "timeout_sec": 1,
}, timeout=12)
entry = result.get("results", [{}])[0] if isinstance(result, dict) else {}
check("terminal timeout bounded", status == 200 and entry.get("success") is True and entry.get("content", {}).get("exit_code") == 124, entry)

# Bulkhead bounds and API input validation.
status, result = request(CHAT + "/v1/bulkheads/edge-test/configure", {
    "max_concurrent": -1, "max_queue": -1, "acquire_timeout_sec": 0,
}, "POST")
check("invalid bulkhead settings are 422", status == 422, f"status={status} result={result}")
status, result = request(CHAT + "/v1/bulkheads/edge-test/configure", {
    "max_concurrent": 2, "max_queue": 1, "acquire_timeout_sec": 0.5,
}, "POST")
check("valid bulkhead settings", status == 200, f"status={status}")

# Colony approval path: create, ensure execution is gated, then approve.
sid = "edge-" + uuid.uuid4().hex[:8]
status, job = request(COLONY + "/v1/jobs", {
    "goal": "Approval-gate regression test", "require_approval": True, "host_server": False,
})
job_id = job.get("id") if isinstance(job, dict) else None
check("colony creates approval-gated job", status == 200 and bool(job_id) and job.get("status") == "waiting_approval", job)
if job_id:
    status, before = request(COLONY + f"/v1/jobs/{job_id}/run", {}, "POST")
    check("colony blocks unapproved execution", status == 402, f"status={status} result={before}")
    status, approved = request(COLONY + f"/v1/jobs/{job_id}/approve", {}, "POST")
    check("colony approval transition", status == 200 and approved.get("status") == "pending", approved)

# Concurrent request stability; increase counts with EDGE_SOAK_REQUESTS for longer soak runs.
soak_requests = int(os.getenv("EDGE_SOAK_REQUESTS", "100"))
soak_workers = int(os.getenv("EDGE_SOAK_WORKERS", "12"))
if not 1 <= soak_requests <= 10000 or not 1 <= soak_workers <= 128:
    raise SystemExit("EDGE_SOAK_REQUESTS must be 1..10000 and EDGE_SOAK_WORKERS 1..128")
payload = {"message": "concurrency regression", "session_id": "edge-concurrent", "auto_spawn": False, "use_tool_protocol": False}
with concurrent.futures.ThreadPoolExecutor(max_workers=soak_workers) as pool:
    responses = list(pool.map(lambda _: request(CHAT + "/v1/chat", payload, timeout=30)[0], range(soak_requests)))
passed = sum(status == 200 for status in responses)
check(f"{soak_requests} concurrent chat requests ({soak_workers} workers)", passed >= soak_requests - max(2, soak_requests // 50), f"{passed}/{soak_requests} returned 200")

failures = 0
for name, ok, details in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}: {details}")
    failures += not ok
print(f"RESULT {len(RESULTS)-failures}/{len(RESULTS)} passed")
sys.exit(1 if failures else 0)
