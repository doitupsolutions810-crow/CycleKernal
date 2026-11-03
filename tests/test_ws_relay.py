"""ws-relay fan-out: bounded slow consumers, and a publish that reaches bridge mood."""

from __future__ import annotations

import asyncio
import json
import socket
import tempfile
import threading
import time
import urllib.request

import httpx
import pytest
import uvicorn
import websockets
from fastapi.testclient import TestClient

import main
import relay.main as relay
from traits import map_metrics_to_traits

DIVERGENT = {"Core": 0.55, "U2": 0.5, "L2": 0.0, "L5": 0.91, "entropy": 0.91, "coupling": 0.0}


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class RelayServer:
    def __init__(self, port: int):
        config = uvicorn.Config(relay.app, host="127.0.0.1", port=port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.port = port

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 5
        url = f"http://127.0.0.1:{self.port}/health"
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=0.2) as response:
                    if response.status == 200:
                        return self
            except Exception:
                time.sleep(0.05)
        raise RuntimeError("ws-relay did not start")

    def __exit__(self, exc_type, exc, tb):
        self.server.should_exit = True
        self.thread.join(5)
        return False


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_slow_consumer_drop_count_before_reset():
    relay.hub.reset()
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=2)
    relay.hub.queues[1] = queue
    try:
        for i in range(5):
            relay.hub.publish(str(i))
        assert relay.hub.dropped == 3
        assert queue.qsize() == 2
        assert queue.get_nowait() == "3"
        assert queue.get_nowait() == "4"
    finally:
        relay.hub.reset()


@pytest.mark.anyio
async def test_slow_send_loop_keeps_latest_frame(monkeypatch):
    monkeypatch.setenv("CK_RELAY_QUEUE_MAX", "1")
    monkeypatch.setenv("CK_RELAY_SEND_DELAY", "0.05")
    relay.hub.reset()
    port = _free_port()
    with RelayServer(port):
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/out", compression=None) as sub:
            async with websockets.connect(f"ws://127.0.0.1:{port}/ws/in", compression=None) as pub:
                await asyncio.sleep(0.05)
                for i in range(8):
                    await pub.send(json.dumps({"n": i}))
                deadline = time.monotonic() + 2
                latest = None
                while time.monotonic() < deadline:
                    try:
                        latest = json.loads(await asyncio.wait_for(sub.recv(), timeout=0.3))
                    except TimeoutError:
                        break
                    if latest.get("n") == 7:
                        break
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
            health = json.loads(response.read().decode())
    assert latest == {"n": 7}
    assert health["dropped"] > 0
    assert health["published"] == 8
    relay.hub.reset()


def test_publish_reaches_bridge_mood(monkeypatch):
    monkeypatch.setenv("CK_SYNTHETIC", "0")
    monkeypatch.setenv("CK_RELAY_BACKOFF_INITIAL", "0.05")
    monkeypatch.setenv("CK_RELAY_BACKOFF_MAX", "0.2")
    monkeypatch.setenv("CK_RELAY_OPEN_TIMEOUT", "1")
    monkeypatch.setenv("CK_RELAY_SEND_DELAY", "0")
    monkeypatch.delenv("RELAY_URL", raising=False)
    relay.hub.reset()
    monkeypatch.setenv("CK_EVENTS_PATH", str(tempfile.mkdtemp(prefix="ck-events-") + "/events.json"))
    main.reset_runtime_state()
    port = _free_port()
    monkeypatch.setenv("WS_RELAY_URL", f"ws://127.0.0.1:{port}/ws/out")
    expected = map_metrics_to_traits(DIVERGENT).mood
    with RelayServer(port):
        with TestClient(main.app) as client:
            deadline = time.monotonic() + 4
            delivered = False
            while time.monotonic() < deadline:
                response = httpx.post(
                    f"http://127.0.0.1:{port}/publish",
                    content=json.dumps(DIVERGENT),
                )
                if response.status_code == 200 and response.json()["delivered"] >= 1:
                    delivered = True
                    break
                time.sleep(0.05)
            assert delivered

            def mood_applied():
                return client.get("/v1/current_mood").json()["mood"] == expected

            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                if mood_applied():
                    break
                time.sleep(0.02)
            else:
                raise AssertionError(client.get("/health").json())
            health = client.get("/health").json()
    assert health["mode"] == "relay"
    assert health["mood"] == expected
    assert health["relay"]["connected"] is True
    assert health["relay"]["frames_accepted"] >= 1
    relay.hub.reset()
    main.reset_runtime_state()
