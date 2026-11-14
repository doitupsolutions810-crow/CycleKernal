#!/usr/bin/env python3
"""CI-only: reject untrusted pipeline execution before dispatching any agents."""
import json
import os
import urllib.error
import urllib.request

URL = "http://orchestrator:8100"
execution = os.environ["CK_TOOL_EXECUTION_TOKEN"]
service = os.environ["CK_TERMINAL_SERVICE_TOKEN"]
approval = os.environ["CK_TOOL_APPROVAL_TOKEN"]
assert len({execution, service, approval}) == 3

def request(path, payload=None, token=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(URL + path, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

status, info = request("/health")
assert status == 200 and info["status"] == "orchestrator-online", (status, info)
for token,label in [(None,"missing"),("wrong","incorrect"),
                    (service,"terminal"),(approval,"approval")]:
    status, info = request("/v1/run", {"goal": "must not launch", "auto_execute": False}, token=token)
    assert status == 403, (label, status, info)
    print("PASS orchestrator rejects " + label + " credential")
# Schema rejection with correct credential proves an invalid pipeline cannot be queued.
status, info = request("/v1/run", {"goal": 123}, token=execution)
assert status == 422, (status, info)
print("PASS authorized orchestrator uses request validation")
