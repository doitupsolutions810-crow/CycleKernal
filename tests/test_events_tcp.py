"""HTTP refusal must remain readable on an actual TCP connection."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx


def test_event_size_refusal_does_not_reset_client_connection(tmp_path):
    env = dict(os.environ, CK_EVENTS_PATH=str(tmp_path / "events.json"),
               CK_FUSION_TOKEN="tcp-test-token", CK_SYNTHETIC="0",
               WS_RELAY_URL="ws://127.0.0.1:1/ws/out")
    with socket.socket() as listener, (tmp_path / "server.log").open("w") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        base = "http://127.0.0.1:" + str(listener.getsockname()[1])
        process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "main:app", "--fd", str(listener.fileno()),
             "--no-access-log", "--log-level", "warning"],
            cwd=Path(__file__).resolve().parents[1] / "src/bridge", env=env,
            pass_fds=(listener.fileno(),), stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            with httpx.Client(timeout=3, trust_env=False) as http:
                deadline = time.monotonic() + 15
                while True:
                    try:
                        if http.get(base + "/health").status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    assert process.poll() is None, (tmp_path / "server.log").read_text()
                    assert time.monotonic() < deadline
                    time.sleep(.05)
                for size in (4097, 65537, 4097):
                    response = http.post(base + "/v1/events", content=b"x" * size)
                    assert response.status_code == 413
                    assert response.json()["detail"] == "request body too large (max 4096 bytes)"
                    assert http.get(base + "/health").status_code == 200
                response = http.post(base + "/v1/events", content=iter((b"a" * 2000, b"b" * 3000)))
                assert response.status_code == 413 and response.json()["detail"]
                assert http.get(base + "/health").status_code == 200
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
