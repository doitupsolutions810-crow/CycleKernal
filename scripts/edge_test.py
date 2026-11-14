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


# ---------------------------------------------------------------------------
# Advanced edge cases
# ---------------------------------------------------------------------------
def raw_post(url: str, data: bytes, content_type: str = "application/json", timeout: float = 20):
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, res.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except Exception as exc:
        return 0, repr(exc)


def first(result):
    return result.get("results", [{}])[0] if isinstance(result, dict) else {}


def content(result):
    return first(result).get("content", {}) or {}


# Malformed transport shapes must be rejected with 4xx, never 5xx.
for label, data, ctype in (
    ("truncated JSON", b'{"message": "x"', "application/json"),
    ("JSON array body", b"[1, 2, 3]", "application/json"),
    ("JSON null body", b"null", "application/json"),
    ("plain-text body", b"message=hi", "text/plain"),
    ("empty body", b"", "application/json"),
    ("deeply nested JSON", b'{"message":' + b"[" * 200 + b"]" * 200 + b"}", "application/json"),
):
    status, _ = raw_post(CHAT + "/v1/chat", data, ctype)
    check("malformed body: " + label, 400 <= status < 500, f"status={status}")

# tool_calls shape validation (previously HTTP 500).
for label, body in (
    ("tool_calls is a string", {"tool_calls": "oops"}),
    ("tool_calls contains null", {"tool_calls": [None]}),
    ("tool_calls contains scalar", {"tool_calls": [7]}),
    ("tool_calls object not list", {"tool_calls": {"a": 1}}),
):
    for ep in ("/v1/tools/execute", "/v1/tools/execute_advanced"):
        status, _ = request(CHAT + ep, body, "POST")
        check(f"{label} on {ep}", status == 422, f"status={status}")
status, _ = request(CHAT + "/v1/tools/execute_advanced", {"plan": "nope"}, "POST")
check("plan is not an array", status == 422, f"status={status}")
status, _ = request(CHAT + "/v1/tools/execute_advanced", {"plan": [None]}, "POST")
check("plan contains null", status == 422, f"status={status}")

# Nested protocol shapes that previously escaped validation and raised 500.
for label, malformed in (
    ("false tool_calls", {"tool_calls": False}),
    ("empty-string tool_calls", {"tool_calls": ""}),
    ("null tool_calls", {"tool_calls": None}),
    ("scalar function", {"tool_calls": [{"function": 7}]}),
    ("list function", {"tool_calls": [{"function": []}]}),
    ("numeric tool id", {"tool_calls": [{"id": 5, "function": {"name": "planning"}}]}),
    ("numeric tool name", {"tool_calls": [{"function": {"name": 17}}]}),
    ("list arguments", {"tool_calls": [{"function": {"name": "planning", "arguments": []}}]}),
    ("unknown tool type", {"tool_calls": [{"type": "other", "function": {"name": "planning"}}]}),
):
    for endpoint in ("/v1/tools/execute", "/v1/tools/execute_advanced"):
        status, _ = request(CHAT + endpoint, malformed, "POST")
        check(label + " on " + endpoint, status == 422, f"status={status}")

for label, invalid_plan in (
    ("missing DAG id", [{"tool": "planning", "arguments": {"goal": "x"}}]),
    ("missing DAG tool", [{"id": "a", "arguments": {"goal": "x"}}]),
    ("numeric DAG id", [{"id": 5, "tool": "planning"}]),
    ("list DAG arguments", [{"id": "a", "tool": "planning", "arguments": []}]),
    ("scalar DAG dependencies", [{"id": "a", "tool": "planning", "depends_on": 8}]),
    ("non-string DAG dependency", [{"id": "a", "tool": "planning", "depends_on": [1]}]),
    ("duplicate DAG ids", [{"id": "a", "tool": "planning"}, {"id": "a", "tool": "planning"}]),
):
    status, _ = request(CHAT + "/v1/tools/execute_advanced", {"plan": invalid_plan}, "POST")
    check(label + " rejected", status == 422, f"status={status}")

# Batch limits and duplicate ids.
def planning_call(i, call_id=None):
    return {"id": call_id or f"batch-{i}", "type": "function",
            "function": {"name": "planning", "arguments": json.dumps({"goal": f"batch goal {i}"})}}

status, result = request(CHAT + "/v1/tools/execute", {"tool_calls": [planning_call(i) for i in range(100)]}, "POST", timeout=60)
ok_count = sum(r.get("success") is True for r in result.get("results", [])) if isinstance(result, dict) else 0
check("100 tool calls in one request", status == 200 and ok_count == 100, f"status={status} ok={ok_count}")
status, _ = request(CHAT + "/v1/tools/execute", {"tool_calls": [planning_call(i) for i in range(101)]}, "POST", timeout=30)
check("101 tool calls rejected", status == 422, f"status={status}")
status, result = request(CHAT + "/v1/tools/execute", {"tool_calls": [planning_call(0, "dup"), planning_call(1, "dup")]}, "POST")
check("duplicate tool_call ids handled", status == 200 and len(result.get("results", [])) == 2, f"status={status}")

# Hostile but well-formed message content (no tool execution).
hostile = [
    "emoji \U0001F9EA\U0001F680 and RTL \u202eevil\u202c text",
    "null byte \u0000 inside",
    "'; DROP TABLE users; --",
    "{{7*7}} ${jndi:ldap://127.0.0.1/x} $(id) `id`",
    "<script>alert(1)</script>",
    "\r\n\r\nInjected: header\r\n",
    "A" * 100000,
    "   ",
]
for index, text in enumerate(hostile):
    status, payload = request(CHAT + "/v1/chat", {
        "message": text, "session_id": f"hostile-{index}", "auto_spawn": False, "use_tool_protocol": False,
    })
    check(f"hostile message #{index}", status == 200 and isinstance(payload, dict) and isinstance(payload.get("reply"), str),
          f"status={status}")

# Session isolation under interleaved concurrency: every response echoes its own session.
def session_probe(i):
    sid = f"iso-{i % 10}"
    status, payload = request(CHAT + "/v1/chat", {
        "message": f"isolation {i}", "session_id": sid, "auto_spawn": False, "use_tool_protocol": False,
    }, timeout=30)
    return status == 200 and isinstance(payload, dict) and payload.get("session_id") == sid
with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
    iso = list(pool.map(session_probe, range(120)))
check("session ids isolated across 120 interleaved requests", all(iso), f"{sum(iso)}/120 correct")

# Terminal runner: sandbox boundaries and output handling.
status, result = tool("terminal_execute", {"filename": "nested/dir/ok.py", "content": "print('nested-ok')\n", "timeout_sec": 5})
check("terminal nested path runs", status == 200 and content(result).get("exit_code") == 0 and "nested-ok" in str(content(result)), content(result))
status, result = tool("terminal_execute", {"filename": "big-output.py", "content": "print('x' * 50000)\n", "timeout_sec": 10})
check("terminal stdout truncated to 8000 chars", status == 200 and len(content(result).get("stdout", "")) <= 8000, len(content(result).get("stdout", "")))
status, result = tool("terminal_execute", {"filename": "exit-three.py", "content": "import sys; sys.stderr.write('boom'); sys.exit(3)\n", "timeout_sec": 5})
check("terminal preserves non-zero exit and stderr", status == 200 and content(result).get("exit_code") == 3 and "boom" in content(result).get("stderr", ""), content(result))
status, result = tool("terminal_execute", {"filename": "large-source.py", "content": "# " + "z" * 500000 + "\nprint('large-ok')\n", "timeout_sec": 10})
check("terminal 500KB source file", status == 200 and "large-ok" in str(content(result)), str(content(result))[:120])
for label, value in (("negative", -5), ("above maximum", 9999)):
    status, result = tool("terminal_execute", {"filename": "t.py", "content": "print(1)\n", "timeout_sec": value})
    check(f"terminal timeout_sec {label} rejected", status == 200 and content(result).get("status_code") == 422, content(result))
status, result = tool("terminal_execute", {"filename": "nul\u0000byte.py", "content": "print(1)\n", "timeout_sec": 3})
check("terminal NUL in filename rejected", status == 200 and content(result).get("status_code") in (400, 422), content(result))
status, result = tool("terminal_execute", {"filename": ".", "content": "x", "timeout_sec": 3})
check("terminal root path as filename rejected", status == 200 and content(result).get("status_code") in (400, 422), content(result))

# Symlink escape: a link pointing outside the artifact root must not be writable through the API.
tool("terminal_execute", {"filename": "mk-link.py", "content": "pass\n", "timeout_sec": 5,
                          "command": "ln -sfn /tmp/edge-outside-target edge_link.py"})
status, result = tool("terminal_execute", {"filename": "edge_link.py", "content": "print('escaped')\n", "timeout_sec": 5})
check("terminal symlink escape rejected", status == 200 and content(result).get("status_code") == 400, content(result))
tool("terminal_execute", {"filename": "rm-link.py", "content": "pass\n", "timeout_sec": 5, "command": "rm -f edge_link.py"})

# Circuit breaker lifecycle: open -> fast-fail -> close -> recovers.
try:
    status, _ = request(CHAT + "/v1/circuits/planning/open", {"reason": "edge test"}, "POST")
    check("circuit opens", status == 200, f"status={status}")
    status, result = request(CHAT + "/v1/tools/execute_advanced", {"tool_calls": [planning_call(0, "circ-open")]}, "POST")
    check("open circuit fails fast", status == 200 and first(result).get("success") is False and "circuit" in str(first(result).get("error", "")).lower(), first(result))
finally:
    request(CHAT + "/v1/circuits/planning/close", {}, "POST")
status, result = request(CHAT + "/v1/tools/execute_advanced", {"tool_calls": [planning_call(0, "circ-closed")]}, "POST")
check("closed circuit recovers", status == 200 and first(result).get("success") is True, first(result))

# Approval gate: sensitive tool is held, can be denied, and a decision cannot be replayed on unknown ids.
status, result = request(CHAT + "/v1/tools/execute_advanced", {"tool_calls": [{
    "id": "gate-" + uuid.uuid4().hex[:8], "type": "function",
    "function": {"name": "terminal_execute", "arguments": json.dumps({"filename": "gated.py", "content": "print('must-not-run')\n"})}}]}, "POST")
gated = first(result)
gate_id = (gated.get("content") or {}).get("call_id")
check("sensitive tool held for approval", status == 200 and (gated.get("content") or {}).get("status") == "pending_approval" and bool(gate_id), gated)
if gate_id:
    status, decision = request(CHAT + "/v1/tools/approve", {"call_id": gate_id, "approve": False}, "POST")
    check("approval can be denied", status == 200 and decision.get("status") == "denied", decision)
status, decision = request(CHAT + "/v1/tools/approve", {"call_id": "never-issued-" + uuid.uuid4().hex[:6], "approve": True}, "POST")
check("approval of unknown id is refused", status == 200 and "error" in decision, decision)

# DAG execution: cycle detection and a valid dependency chain.
status, result = request(CHAT + "/v1/tools/execute_advanced", {"plan": [
    {"id": "a", "tool": "planning", "arguments": {"goal": "x"}, "depends_on": ["b"]},
    {"id": "b", "tool": "planning", "arguments": {"goal": "y"}, "depends_on": ["a"]},
]}, "POST")
check("DAG cycle is reported not hung", status == 200 and all(r.get("success") is False for r in result.get("results", [])), result)
status, result = request(CHAT + "/v1/tools/execute_advanced", {"plan": [
    {"id": "first", "tool": "planning", "arguments": {"goal": "one"}},
    {"id": "second", "tool": "planning", "arguments": {"goal": "two"}, "depends_on": ["first"]},
]}, "POST")
check("valid DAG chain succeeds", status == 200 and len(result.get("results", [])) == 2 and all(r.get("success") for r in result["results"]), result)

# Agents: repeated, concurrent execution must be stable and structured.
def agent_run(i):
    agent = ("reasoning", "planning", "research", "coding", "artifact", "container")[i % 6]
    status, result = tool("spawn_agent", {"agent": agent, "goal": f"repeat run {i}", "task": {"goal": f"repeat run {i}", "language": "python"}}, timeout=60)
    return first(result).get("success") is True if status == 200 else False
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    agent_ok = list(pool.map(agent_run, range(36)))
check("36 concurrent specialist agent runs", all(agent_ok), f"{sum(agent_ok)}/36 succeeded")

# Server agent lifecycle (always cleaned up).
rt_name = "edge-rt-" + uuid.uuid4().hex[:6]
try:
    status, result = tool("spawn_agent", {"agent": "server", "action": "start", "name": rt_name, "port": 8791, "mode": "static"}, timeout=30)
    check("server agent starts a runtime", status == 200 and first(result).get("success") is True, first(result))
    status, result = tool("spawn_agent", {"agent": "server", "action": "status", "name": rt_name}, timeout=15)
    check("server agent reports runtime", status == 200 and first(result).get("success") is True, first(result))
finally:
    status, result = tool("spawn_agent", {"agent": "server", "action": "stop", "name": rt_name}, timeout=15)
    check("server agent stops runtime", status == 200 and first(result).get("success") is True, first(result))

# Colony control plane: error paths and consensus/evolution surfaces.
status, _ = request(COLONY + "/v1/jobs/does-not-exist")
check("colony unknown job is 404", status == 404, f"status={status}")
status, _ = request(COLONY + "/v1/jobs/does-not-exist/run", {}, "POST")
check("colony run unknown job is 404", status == 404, f"status={status}")
status, _ = request(COLONY + "/v1/approvals/decide", {"id": "never-issued", "approve": True}, "POST")
check("colony decide unknown approval is 404", status == 404, f"status={status}")
status, _ = request(COLONY + "/v1/jobs", {"goal": 123}, "POST")
check("colony job with non-string goal rejected", status == 422, f"status={status}")
status, _ = request(COLONY + "/v1/fitness/feedback", {"success": "maybe"}, "POST")
check("colony fitness feedback type validation", status == 422, f"status={status}")
status, proposal = request(COLONY + "/v1/consensus/decide", {
    "type": "custom", "summary": "edge-test proposal", "payload": {}, "protocol": "majority"}, "POST", timeout=30)
check("colony consensus reaches a decision", status == 200 and proposal.get("status") in ("approved", "denied", "rejected", "closed", "open"), proposal.get("status") if isinstance(proposal, dict) else proposal)
status, _ = request(COLONY + "/v1/consensus/proposals/does-not-exist")
check("colony unknown proposal is 404", status == 404, f"status={status}")
status, _ = request(COLONY + "/v1/evolution/pipelines")
check("colony evolution status available", status == 200, f"status={status}")

# Mixed workload: chat + tools + reads in parallel; nothing may return a 5xx.
def mixed(i):
    kind = i % 5
    if kind == 0:
        return request(CHAT + "/v1/chat", {"message": f"mixed {i}", "session_id": f"mix-{i % 9}", "auto_spawn": False, "use_tool_protocol": False}, timeout=30)[0]
    if kind == 1:
        return tool("planning", {"goal": f"mixed {i}"}, timeout=30)[0]
    if kind == 2:
        return request(CHAT + "/v1/tools")[0]
    if kind == 3:
        return request(COLONY + "/health")[0]
    return request(BASE + "/api/simulation/state", timeout=30)[0]
with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
    mixed_status = list(pool.map(mixed, range(240)))
server_errors = [s for s in mixed_status if s == 0 or s >= 500]
check("240 mixed requests without any 5xx", not server_errors, f"errors={server_errors[:10]}")

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


# Optional time-boxed soak (EDGE_SOAK_SECONDS) with error-rate and latency reporting.
soak_seconds = float(os.getenv("EDGE_SOAK_SECONDS", "0"))
if soak_seconds > 0:
    latencies: list[float] = []
    soak_errors = 0
    deadline = time.time() + soak_seconds

    def timed_chat(i):
        began = time.time()
        status, _ = request(CHAT + "/v1/chat", {
            "message": f"timed soak {i}", "session_id": f"timed-{i % 17}", "auto_spawn": False, "use_tool_protocol": False,
        }, timeout=30)
        return status, time.time() - began

    counter = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        while time.time() < deadline:
            batch = list(pool.map(timed_chat, range(counter, counter + 64)))
            counter += 64
            for status, elapsed in batch:
                latencies.append(elapsed)
                soak_errors += status != 200
    latencies.sort()
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0.0
    check(f"{soak_seconds:.0f}s timed soak ({len(latencies)} requests)", soak_errors == 0 and p95 < 5.0,
          f"errors={soak_errors} p95={p95:.3f}s max={latencies[-1] if latencies else 0:.3f}s")

failures = 0
for name, ok, details in RESULTS:
    print(f"{'PASS' if ok else 'FAIL'} {name}: {details}")
    failures += not ok
print(f"RESULT {len(RESULTS)-failures}/{len(RESULTS)} passed")
sys.exit(1 if failures else 0)
