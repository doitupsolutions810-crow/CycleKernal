"""Relay intake and Fusion Bridge event intake for src/bridge/main.py.

The previous subscribe_to_relay pushed one fixed metric dict every 5 seconds
and never opened a socket. These tests cover a live websocket, garbage frames,
reconnect, mood changes, and the authenticated POST /events path.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time

import httpx
import pytest
import websockets
from fastapi.testclient import TestClient

import main
from traits import map_metrics_to_traits

SURVIVAL = {"Core": 0.05, "U2": 0.5, "L2": 0.0, "L5": 0.1, "entropy": 0.1, "coupling": 0.0}
DIVERGENT = {"Core": 0.55, "U2": 0.5, "L2": 0.0, "L5": 0.91, "entropy": 0.91, "coupling": 0.0}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class ScriptedRelay:
    """Local asyncio websocket server running beside the TestClient loop."""

    def __init__(self, handler):
        self.handler = handler
        self.loop = asyncio.new_event_loop()
        self.started = threading.Event()
        self.port = None
        self.server = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._serve())

    async def _serve(self):
        self.server = await websockets.serve(
            self.handler,
            "127.0.0.1",
            0,
            ping_interval=None,
            compression=None,
        )
        self.port = self.server.sockets[0].getsockname()[1]
        self.started.set()
        await self.server.wait_closed()

    def __enter__(self):
        self.thread.start()
        if not self.started.wait(5):
            raise RuntimeError("relay test server did not start")
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.server is not None:
            self.loop.call_soon_threadsafe(self.server.close)
            future = asyncio.run_coroutine_threadsafe(self.server.wait_closed(), self.loop)
            try:
                future.result(3)
            except Exception:
                pass
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)
        return False

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/out"


@pytest.fixture
def bridge_env(monkeypatch):
    monkeypatch.setenv("CK_SYNTHETIC", "0")
    monkeypatch.setenv("CK_RELAY_BACKOFF_INITIAL", "0.05")
    monkeypatch.setenv("CK_RELAY_BACKOFF_FACTOR", "2")
    monkeypatch.setenv("CK_RELAY_BACKOFF_MAX", "0.4")
    monkeypatch.setenv("CK_RELAY_OPEN_TIMEOUT", "0.4")
    monkeypatch.setenv("CK_EVENTS_TOKEN", "test-token")
    monkeypatch.setenv("CK_EVENTS_MAX_BYTES", "65536")
    monkeypatch.setenv("CK_EVENTS_MAX_RECENT", "100")
    monkeypatch.delenv("WS_RELAY_URL", raising=False)
    monkeypatch.setenv("RELAY_URL", f"ws://127.0.0.1:{_closed_port()}/ws/out")
    main.reset_runtime_state()
    yield
    main.reset_runtime_state()


def _auth(token: str = "test-token") -> dict:
    return {"Authorization": f"Bearer {token}"}


def _fusion_event(event_id: str = "evt-1", **overrides) -> dict:
    body = {
        "id": event_id,
        "source": "avrone",
        "kind": "finding",
        "run_id": "run-1",
        "payload": {"text": "heat"},
        "ts": 1700000000.0,
    }
    body.update(overrides)
    return body


def _wait_until(predicate, timeout: float = 4.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"condition not met; last={last!r} health={_health_dump()}")


def _health_dump() -> dict:
    with main._relay_guard:
        relay = main.relay_status.public()
        relay["mode"] = main.relay_status.mode
        relay["trace"] = list(main.relay_status.backoff_trace)
    return {"mood": main.current_state.mood, "relay": relay}


def test_backoff_grows_then_caps():
    assert main.next_backoff(None, initial=0.05, factor=2, maximum=0.2) == 0.05
    assert main.next_backoff(0.05, initial=0.05, factor=2, maximum=0.2) == 0.1
    assert main.next_backoff(0.1, initial=0.05, factor=2, maximum=0.2) == 0.2
    assert main.next_backoff(0.2, initial=0.05, factor=2, maximum=0.2) == 0.2


def test_relay_url_precedence(monkeypatch):
    monkeypatch.delenv("WS_RELAY_URL", raising=False)
    monkeypatch.delenv("RELAY_URL", raising=False)
    assert main.configured_relay_url() == main.DEFAULT_RELAY_URL
    monkeypatch.setenv("RELAY_URL", "ws://legacy:8081/ws/out")
    assert main.configured_relay_url() == "ws://legacy:8081/ws/out"
    monkeypatch.setenv("WS_RELAY_URL", "ws://primary:8081/ws/out")
    assert main.configured_relay_url() == "ws://primary:8081/ws/out"


def test_parse_metrics_frame_rejects_garbage_and_accepts_envelope():
    with pytest.raises(main.FrameError):
        main.parse_metrics_frame("not-json")
    with pytest.raises(main.FrameError):
        main.parse_metrics_frame("[]")
    with pytest.raises(main.FrameError):
        main.parse_metrics_frame('{"Core": "high"}')
    with pytest.raises(main.FrameError):
        main.parse_metrics_frame(b"\xff\xfe")
    parsed = main.parse_metrics_frame(json.dumps({"metrics": {"Core": 0.2, "L5": 1}}))
    assert parsed == {"Core": 0.2, "L5": 1.0}


def test_relay_offline_does_not_invent_mood(bridge_env):
    """A down relay must not replay the old fixed heartbeat."""
    with TestClient(main.app) as client:
        def ready():
            with main._relay_guard:
                return len(main.relay_status.backoff_trace) >= 3

        _wait_until(ready)
        health = client.get("/health").json()
        with main._relay_guard:
            trace = list(main.relay_status.backoff_trace)
            times = list(main.relay_status.attempt_times)

    assert health["mode"] == "relay"
    assert health["mood"] == "neutral"
    assert health["relay"]["connected"] is False
    assert health["relay"]["frames_accepted"] == 0
    assert health["relay"]["attempts"] >= 3
    assert health["relay"]["last_error"]
    initial, factor, maximum = main.backoff_params()
    expected = []
    previous = None
    for _ in range(3):
        previous = main.next_backoff(previous, initial=initial, factor=factor, maximum=maximum)
        expected.append(previous)
    assert trace[:3] == expected
    # Gaps between attempts are the sleeps. Recording the formula without
    # sleeping would leave both gaps near the connect-failure cost.
    gaps = [times[1] - times[0], times[2] - times[1]]
    assert gaps[0] >= expected[0] * 0.7
    assert gaps[1] >= expected[1] * 0.7


def test_garbage_frames_are_skipped_and_mood_follows_valid_metrics(bridge_env, monkeypatch):
    expected = map_metrics_to_traits(DIVERGENT).mood
    assert expected != "neutral"

    async def handler(ws):
        await ws.send("this is not json")
        await ws.send("[]")
        await ws.send('"nope"')
        await ws.send(json.dumps({"Core": "high", "L5": 0.9}))
        await ws.send(json.dumps({"unrelated": True}))
        await ws.send(b"\xff\xfe")
        await ws.send(json.dumps({"metrics": DIVERGENT}))
        try:
            await ws.recv()
        except Exception:
            return

    with ScriptedRelay(handler) as relay:
        monkeypatch.setenv("WS_RELAY_URL", relay.url)
        main.reset_runtime_state()
        with TestClient(main.app) as client:
            def applied():
                health = client.get("/health").json()
                return (
                    health["mood"] == expected
                    and health["relay"]["frames_rejected"] >= 6
                    and health["relay"]["frames_accepted"] >= 1
                    and health["relay"]["connected"] is True
                )

            _wait_until(applied)
            health = client.get("/health").json()

    assert health["mode"] == "relay"
    assert health["mood"] == expected
    assert health["relay"]["attempts"] == 1


def test_reconnects_after_drop_and_mood_changes(bridge_env, monkeypatch):
    first = map_metrics_to_traits(SURVIVAL).mood
    second = map_metrics_to_traits(DIVERGENT).mood
    assert first != second
    seen = {"n": 0}

    async def handler(ws):
        n = seen["n"]
        seen["n"] += 1
        if n == 0:
            await ws.send(json.dumps(SURVIVAL))
            await ws.close()
            return
        await ws.send(json.dumps(DIVERGENT))
        try:
            await ws.recv()
        except Exception:
            return

    monkeypatch.setenv("CK_RELAY_BACKOFF_INITIAL", "0.25")
    monkeypatch.setenv("CK_RELAY_BACKOFF_MAX", "0.25")
    with ScriptedRelay(handler) as relay:
        monkeypatch.setenv("WS_RELAY_URL", relay.url)
        main.reset_runtime_state()
        moods = []
        with TestClient(main.app) as client:
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                mood = client.get("/v1/current_mood").json()["mood"]
                if not moods or moods[-1] != mood:
                    moods.append(mood)
                if first in moods and mood == second:
                    break
                time.sleep(0.02)
            else:
                raise AssertionError(f"moods={moods} connections={seen['n']} dump={_health_dump()}")
            health = client.get("/health").json()

    assert moods.index(first) < moods.index(second)
    assert moods[-1] == second
    assert health["relay"]["connected"] is True
    assert health["relay"]["attempts"] >= 2
    assert seen["n"] >= 2


def test_synthetic_flag_is_explicit_and_reported(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_SYNTHETIC", "1")
    monkeypatch.setenv("CK_SYNTHETIC_INTERVAL", "0.05")
    monkeypatch.setenv("WS_RELAY_URL", "ws://127.0.0.1:1/ws/out")
    main.reset_runtime_state()
    expected = map_metrics_to_traits(main.SYNTHETIC_METRICS).mood
    with TestClient(main.app) as client:
        def ready():
            body = client.get("/health").json()
            return body["mode"] == "synthetic" and body["mood"] == expected

        _wait_until(ready)
        health = client.get("/health").json()

    assert health["mode"] == "synthetic"
    assert health["mood"] == expected
    assert health["relay"]["connected"] is False
    assert health["relay"]["attempts"] == 0
    assert health["relay"]["frames_accepted"] >= 1


def test_events_bad_auth_and_unconfigured_token(bridge_env, monkeypatch):
    with TestClient(main.app) as client:
        missing = client.post("/events", json=_fusion_event("auth-missing"))
        wrong = client.post("/events", json=_fusion_event("auth-wrong"), headers=_auth("nope"))
        basic = client.post(
            "/events",
            json=_fusion_event("auth-basic"),
            headers={"Authorization": "Basic dGVzdA=="},
        )
        ok_header = client.post(
            "/events",
            json=_fusion_event("auth-ok"),
            headers={"X-Events-Token": "test-token"},
        )
        hidden = client.get("/events")
        health = client.get("/health").json()

    assert missing.status_code == 401
    assert missing.json()["detail"] == "Bad admin token"
    assert wrong.status_code == 401
    assert basic.status_code == 401
    assert hidden.status_code == 401
    assert ok_header.status_code == 200
    assert health["events"]["accepted"] == 1
    assert health["events"]["rejected_auth"] == 4
    assert health["events"]["stored"] == 1

    monkeypatch.delenv("CK_EVENTS_TOKEN", raising=False)
    main.reset_runtime_state()
    with TestClient(main.app) as client:
        blocked = client.post("/events", json=_fusion_event("auth-off"), headers=_auth())
        health = client.get("/health").json()
    assert blocked.status_code == 403
    assert "CK_FUSION_TOKEN" in blocked.json()["detail"]
    assert health["events"]["auth_configured"] is False
    assert health["events"]["stored"] == 0


def test_events_malformed_are_rejected(bridge_env):
    with TestClient(main.app) as client:
        garbage = client.post(
            "/events",
            content=b"not-json",
            headers={**_auth(), "Content-Type": "application/json"},
        )
        array = client.post("/events", json=[1, 2], headers=_auth())
        empty = client.post(
            "/events",
            content=b"",
            headers={**_auth(), "Content-Type": "application/json"},
        )
        health = client.get("/health").json()

    assert garbage.status_code == 400
    assert garbage.json()["detail"] == "body must be JSON"
    assert array.status_code == 400
    assert empty.status_code == 400
    assert health["events"]["accepted"] == 0
    assert health["events"]["rejected_body"] == 3
    assert health["events"]["stored"] == 0


@pytest.mark.anyio
async def test_concurrent_event_posts(bridge_env, monkeypatch):
    monkeypatch.setenv("WS_RELAY_URL", f"ws://127.0.0.1:{_closed_port()}/ws/out")
    main.reset_runtime_state()
    count = 32
    async with main.app.router.lifespan_context(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as client:
            async def post(i: int):
                return await client.post("/events", json=_fusion_event(f"evt-{i}", payload={"i": i}), headers=_auth())

            responses = await asyncio.gather(*[post(i) for i in range(count)])
            listing = await client.get("/events", headers=_auth())
            health = await client.get("/health")

    assert [response.status_code for response in responses] == [200] * count
    body = listing.json()
    assert body["stored"] == count
    assert body["accepted"] == count
    assert {event["payload"]["i"] for event in body["events"]} == set(range(count))
    assert health.json()["events"]["accepted"] == count
    assert health.json()["events"]["stored"] == count
    assert health.json()["events"]["rejected"] == 0


def _metrics_frame(size: int, core: float) -> str:
    prefix = f'{{"Core":{core:.2f},"pad":"'
    suffix = '"}'
    filler = size - len(prefix.encode("utf-8")) - len(suffix.encode("utf-8"))
    if filler < 0:
        raise ValueError(f"size {size} is smaller than the metric envelope")
    return prefix + ("x" * filler) + suffix


def test_relay_flapping_resets_backoff_and_keeps_latest_mood(bridge_env, monkeypatch):
    first = map_metrics_to_traits(SURVIVAL).mood
    second = map_metrics_to_traits(DIVERGENT).mood
    assert first != second
    seen = {"n": 0}

    async def handler(ws):
        n = seen["n"]
        seen["n"] += 1
        if n < 4:
            await ws.send(json.dumps(SURVIVAL))
            await ws.close()
            return
        await ws.send(json.dumps(DIVERGENT))
        try:
            await ws.recv()
        except Exception:
            return

    monkeypatch.setenv("CK_RELAY_BACKOFF_INITIAL", "0.05")
    monkeypatch.setenv("CK_RELAY_BACKOFF_FACTOR", "2")
    monkeypatch.setenv("CK_RELAY_BACKOFF_MAX", "1")
    with ScriptedRelay(handler) as relay:
        monkeypatch.setenv("WS_RELAY_URL", relay.url)
        main.reset_runtime_state()
        with TestClient(main.app) as client:
            def settled():
                health = client.get("/health").json()
                with main._relay_guard:
                    trace = list(main.relay_status.backoff_trace)
                return (
                    health["mood"] == second
                    and health["relay"]["connected"] is True
                    and health["relay"]["attempts"] >= 5
                    and len(trace) >= 4
                )

            _wait_until(settled)
            with main._relay_guard:
                trace = list(main.relay_status.backoff_trace)

    initial, factor, maximum = main.backoff_params()
    fresh = main.next_backoff(None, initial=initial, factor=factor, maximum=maximum)
    # Each successful handshake resets the curve, so flaps do not climb to the cap.
    assert trace[:4] == [fresh, fresh, fresh, fresh]
    assert seen["n"] >= 5


def test_slow_hud_consumer_does_not_stall_mood(bridge_env, monkeypatch):
    expected = map_metrics_to_traits(DIVERGENT).mood
    monkeypatch.setenv("CK_HUD_SEND_TIMEOUT", "0.05")

    class SlowSocket:
        def __init__(self):
            self.calls = 0
            self.closed = False

        async def send_json(self, payload):
            self.calls += 1
            await asyncio.sleep(5)

        async def close(self):
            self.closed = True

    async def handler(ws):
        await ws.send(json.dumps(SURVIVAL))
        await asyncio.sleep(0.25)
        await ws.send(json.dumps(DIVERGENT))
        try:
            await ws.recv()
        except Exception:
            return

    with ScriptedRelay(handler) as relay:
        monkeypatch.setenv("WS_RELAY_URL", relay.url)
        main.reset_runtime_state()
        with TestClient(main.app) as client:
            def saw_first():
                return client.get("/v1/current_mood").json()["mood"] == map_metrics_to_traits(SURVIVAL).mood

            _wait_until(saw_first)
            slow = SlowSocket()
            main.ws_clients.append(slow)
            started = time.monotonic()

            def dropped_slow_client():
                mood = client.get("/v1/current_mood").json()["mood"]
                return mood == expected and slow not in main.ws_clients and slow.calls >= 1

            _wait_until(dropped_slow_client)
            elapsed = time.monotonic() - started

    assert elapsed < 2
    assert slow.closed is True


def test_token_rotation_accepts_previous_until_cleared(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_EVENTS_TOKEN", "alpha")
    monkeypatch.delenv("CK_EVENTS_TOKEN_PREVIOUS", raising=False)
    with TestClient(main.app) as client:
        assert client.post("/events", json=_fusion_event("rot-1"), headers=_auth("alpha")).status_code == 200
        assert client.post("/events", json=_fusion_event("rot-1b"), headers=_auth("beta")).status_code == 401
        monkeypatch.setenv("CK_EVENTS_TOKEN", "beta")
        monkeypatch.setenv("CK_EVENTS_TOKEN_PREVIOUS", "alpha")
        assert client.post("/events", json=_fusion_event("rot-2"), headers=_auth("alpha")).status_code == 200
        assert client.post("/events", json=_fusion_event("rot-3"), headers=_auth("beta")).status_code == 200
        assert client.post("/events", json=_fusion_event("rot-4"), headers=_auth("gamma")).status_code == 401
        monkeypatch.delenv("CK_EVENTS_TOKEN_PREVIOUS", raising=False)
        retired = client.post("/events", json=_fusion_event("rot-5"), headers=_auth("alpha"))
        current = client.post("/events", json=_fusion_event("rot-6"), headers=_auth("beta"))
        health = client.get("/health").json()
    assert retired.status_code == 401
    assert current.status_code == 200
    assert health["events"]["auth_configured"] is True
    assert health["events"]["accepted"] == 4


def test_frame_at_exact_size_cap_is_applied_and_one_over_reconnects(bridge_env, monkeypatch):
    cap = 128
    exact = _metrics_frame(cap, 0.05)
    over = _metrics_frame(cap + 1, 0.55)
    assert len(exact.encode("utf-8")) == cap
    assert len(over.encode("utf-8")) == cap + 1
    expected = map_metrics_to_traits({"Core": 0.05}).mood
    other = map_metrics_to_traits({"Core": 0.55}).mood
    assert expected != other
    seen = {"n": 0}

    async def handler(ws):
        n = seen["n"]
        seen["n"] += 1
        if n == 0:
            await ws.send(exact)
            try:
                await ws.send(over)
            except Exception:
                return
        try:
            await ws.recv()
        except Exception:
            return

    monkeypatch.setenv("CK_RELAY_MAX_FRAME_BYTES", str(cap))
    monkeypatch.setenv("CK_RELAY_BACKOFF_INITIAL", "0.05")
    with ScriptedRelay(handler) as relay:
        monkeypatch.setenv("WS_RELAY_URL", relay.url)
        main.reset_runtime_state()
        with TestClient(main.app) as client:
            def dropped_oversize():
                health = client.get("/health").json()
                # A successful reconnect clears last_error, so the durable signal
                # is a second attempt that did not apply the oversized frame.
                return (
                    health["mood"] == expected
                    and health["relay"]["frames_accepted"] == 1
                    and health["relay"]["attempts"] >= 2
                )

            _wait_until(dropped_oversize)
            health = client.get("/health").json()

    assert health["mood"] == expected
    assert health["relay"]["frames_accepted"] == 1


def test_event_ring_drops_oldest_when_full(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_EVENTS_MAX_RECENT", "3")
    with TestClient(main.app) as client:
        for i in range(5):
            response = client.post("/events", json=_fusion_event(f"evt-{i}", payload={"i": i}), headers=_auth())
            assert response.status_code == 200
            assert response.json()["duplicate"] is False
        stored = client.get("/events", headers=_auth()).json()
        health = client.get("/health").json()
    assert [event["id"] for event in stored["events"]] == ["evt-2", "evt-3", "evt-4"]
    assert stored["accepted"] == 5
    assert stored["stored"] == 3
    assert health["events"]["accepted"] == 5
    assert health["events"]["stored"] == 3


def test_master_tree_loads_canonical_bridge():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "master" / "src" / "bridge" / "main.py"
    spec = importlib.util.spec_from_file_location("master_bridge_shim", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    paths = {getattr(route, "path", None) for route in module.app.routes}
    assert {"/events", "/v1/events", "/health", "/v1/current_mood", "/v1/feedback", "/ws/hud"} <= paths


def test_feedback_endpoint_accepts_orchestrator_payload(bridge_env):
    with TestClient(main.app) as client:
        response = client.post(
            "/v1/feedback",
            json={"goal": "ship", "success": True, "stages": ["research"], "mood_at_start": "neutral"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ingested"
