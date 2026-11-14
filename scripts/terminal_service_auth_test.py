#!/usr/bin/env python3
"""Service-to-service authorization regression from the chat runner-network container."""
import json
import os
import urllib.error
import urllib.request
import uuid

BASE = "http://terminal-runtime:8200"
TOKEN = os.environ["CK_TERMINAL_SERVICE_TOKEN"]
OTHER = [os.environ["CK_TOOL_EXECUTION_TOKEN"], os.environ["CK_TOOL_APPROVAL_TOKEN"]]
assert len({TOKEN, *OTHER}) == 3, "service, execution and approval tokens must be distinct"


def call(path, body=None, token=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token is not None:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as failure:
        return failure.code, json.loads(failure.read())


payload = {"filename": "terminal-auth-" + uuid.uuid4().hex + ".py",
           "content": "import os; print('valid-service-credential'); print('token-leak:', os.getenv('CK_TERMINAL_SERVICE_TOKEN', 'absent'))\n",
           "timeout_sec": 5}
for token, label in [(None, "missing"), ("wrong-secret", "incorrect"),
                     (OTHER[0], "execution-token"), (OTHER[1], "approval-token")]:
    for route, content in [("/v1/execute", payload), ("/v1/artifacts", None)]:
        status, _ = call(route, body=content, token=token)
        assert status == 403, (label, route, status)
    print("PASS no access with " + label)
status, health = call("/health")
assert status == 200 and health["status"] == "terminal-online"
status, result = call("/v1/execute", body=payload, token=TOKEN)
assert status == 200 and result["exit_code"] == 0, (status, result)
assert "valid-service-credential" in result["stdout"] and "token-leak: absent" in result["stdout"], result
status, result = call("/v1/artifacts", token=TOKEN)
assert status == 200 and "artifacts" in result
print("PASS valid internal service credential and sanitized child environment")
