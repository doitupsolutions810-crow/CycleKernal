"""Longer edge pass for /v1/events, /events, /health, dedup, and the store.

Safety deadlines stay on. Anomalies are printed with an ISO timestamp and a traceback.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from test_bridge_relay import _fusion_event


def _anomaly(message: str, exc: BaseException | None = None) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    print(f"{stamp} ANOMALY {message}", file=sys.stderr)
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def bridge_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CK_SYNTHETIC", "0")
    monkeypatch.setenv("CK_RELAY_BACKOFF_INITIAL", "0.05")
    monkeypatch.setenv("CK_RELAY_BACKOFF_MAX", "0.2")
    monkeypatch.setenv("CK_RELAY_OPEN_TIMEOUT", "0.4")
    monkeypatch.setenv("CK_EVENTS_TOKEN", "test-token")
    monkeypatch.delenv("CK_FUSION_TOKEN", raising=False)
    monkeypatch.delenv("FUSION_TOKEN", raising=False)
    monkeypatch.delenv("CK_EVENTS_TOKEN_PREVIOUS", raising=False)
    monkeypatch.setenv("CK_EVENTS_MAX_BYTES", "4096")
    monkeypatch.setenv("CK_EVENTS_MAX_RECENT", "100")
    monkeypatch.setenv("CK_EVENTS_PATH", str(tmp_path / "events.json"))
    monkeypatch.delenv("WS_RELAY_URL", raising=False)
    monkeypatch.setenv("RELAY_URL", f"ws://127.0.0.1:{_closed_port()}/ws/out")
    main.reset_runtime_state()
    yield
    main.reset_runtime_state()


def _admin(token: str = "test-token") -> dict:
    return {"X-Admin-Token": token}


def test_large_payload_integer_does_not_500(bridge_env):
    raw = (
        '{"id":"evt-big","source":"avrone","kind":"finding","run_id":"run-1","payload":{"n":'
        + ("9" * 3000)
        + '},"ts":1}'
    ).encode()
    assert len(raw) <= 4096
    with TestClient(main.app) as client:
        response = client.post("/v1/events", content=raw, headers={**_admin(), "Content-Type": "application/json"})
        listed = client.get("/v1/events", headers=_admin())
    assert response.status_code == 200, response.text
    assert listed.status_code == 200
    assert listed.json()["events"][0]["payload"]["n"] == int("9" * 3000)


def test_malformed_bodies_stay_below_500(bridge_env):
    eighty = "a" * 80
    samples = [
        b"\xff\xfe",
        b"\x00",
        b"{",
        b"null",
        b"[]",
        b'{"id":',
        b'{"id":"a","id":"b","source":"avrone","kind":"finding","run_id":"r","payload":{}}',
        ("[" * 400 + "]" * 400).encode(),
        json.dumps(_fusion_event(eighty)).encode(),
        json.dumps(_fusion_event(eighty + "a")).encode(),
        json.dumps(_fusion_event("evt-blank", run_id="   ")).encode(),
        json.dumps(_fusion_event("evt-src", source=" avrone")).encode(),
        json.dumps(_fusion_event("evt-kind", kind="Finding")).encode(),
        json.dumps(_fusion_event("evt-pay", payload=None)).encode(),
        json.dumps(_fusion_event("evt-ts0", ts=0)).encode(),
        json.dumps(_fusion_event("evt-tsneg", ts=-5)).encode(),
        json.dumps(_fusion_event("evt-tsbool", ts=True)).encode(),
        b'{"id":"evt-inf","source":"avrone","kind":"finding","run_id":"r","payload":{},"ts":1e999}',
    ]
    with TestClient(main.app) as client:
        for sample in samples:
            for path in ("/v1/events", "/events"):
                try:
                    response = client.post(path, content=sample, headers={**_admin(), "Content-Type": "application/json"})
                except Exception as exc:
                    _anomaly(f"{path} raised on {sample[:60]!r}", exc)
                    raise
                if response.status_code >= 500:
                    _anomaly(f"{path} status {response.status_code} body {response.text} sample {sample[:80]!r}")
                assert response.status_code < 500, (path, response.status_code, response.text, sample[:80])
        health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["boot"] == main.BOOT_ID


def test_overflowing_timestamp_uses_server_clock(bridge_env):
    body = _fusion_event("evt-ts", ts=int("9" * 400))
    before = time.time()
    with TestClient(main.app) as client:
        response = client.post("/events", json=body, headers=_admin())
        stored = client.get("/v1/events", headers=_admin()).json()
    after = time.time()
    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    ts = stored["events"][0]["ts"]
    assert before - 1 <= ts <= after + 1


def test_cross_source_dedup_survives_eviction_and_reload(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_EVENTS_MAX_RECENT", "1")
    with TestClient(main.app) as client:
        assert client.post(
            "/v1/events",
            json=_fusion_event("shared", source="greatscale", kind="evidence", payload={"text": "gs"}),
            headers=_admin(),
        ).json()["duplicate"] is False
        assert client.post(
            "/events",
            json=_fusion_event("shared", source="avrone", payload={"text": "av"}),
            headers=_admin(),
        ).json()["duplicate"] is False
    main.reset_runtime_state()
    with TestClient(main.app) as client:
        replay_gs = client.post(
            "/v1/events",
            json=_fusion_event("shared", source="greatscale", kind="evidence", payload={"text": "nope"}),
            headers=_admin(),
        )
        replay_av = client.post(
            "/events",
            json=_fusion_event("shared", source="avrone", payload={"text": "nope"}),
            headers=_admin(),
        )
        third = client.post(
            "/v1/events",
            json=_fusion_event("shared", source="cyclekernal", payload={"text": "ck"}),
            headers=_admin(),
        )
        listed = client.get("/events", headers=_admin()).json()
    assert replay_gs.json()["duplicate"] is True
    assert replay_av.json()["duplicate"] is True
    assert third.json()["duplicate"] is False
    by_source = {event["source"]: event["payload"]["text"] for event in listed["events"]}
    assert by_source.get("avrone") == "av" or by_source.get("cyclekernal") == "ck"
    assert "nope" not in by_source.values()


def test_tombstone_cap_refuses_instead_of_forgetting(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_EVENTS_MAX_RECENT", "1")
    monkeypatch.setenv("CK_EVENTS_TOMBSTONE_MAX", "2")
    with TestClient(main.app) as client:
        for name in ("a", "b", "c"):
            response = client.post("/v1/events", json=_fusion_event(f"id-{name}"), headers=_admin())
            assert response.status_code == 200, response.text
            assert response.json()["duplicate"] is False
        overflow = client.post("/v1/events", json=_fusion_event("id-d"), headers=_admin())
        replay = client.post("/v1/events", json=_fusion_event("id-a", payload={"text": "rewritten"}), headers=_admin())
        health = client.get("/health").json()
        listed = client.get("/v1/events", headers=_admin()).json()
    assert overflow.status_code == 503
    assert overflow.json()["detail"] == "event store unavailable"
    assert replay.json()["duplicate"] is True
    assert [event["id"] for event in listed["events"]] == ["id-c"]
    assert health["events"]["stored"] == 1
    assert health["boot"] == main.BOOT_ID
    main.reset_runtime_state()
    with TestClient(main.app) as client:
        assert client.get("/health").json()["boot"] == main.BOOT_ID
        again = client.post("/events", json=_fusion_event("id-a"), headers=_admin())
    assert again.json()["duplicate"] is True


@pytest.mark.anyio
async def test_concurrent_posts_across_paths_and_sources(bridge_env):
    headers = {"X-Admin-Token": "test-token"}
    async with main.app.router.lifespan_context(main.app):
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://bridge") as client:
            async def one(n: int):
                source = ("avrone", "greatscale", "cyclekernal")[n % 3]
                kind = "evidence" if source == "greatscale" else "finding"
                path = "/v1/events" if n % 2 == 0 else "/events"
                body = _fusion_event(
                    f"id-{n % 17}",
                    source=source,
                    kind=kind,
                    payload={"n": n, "source": source},
                )
                try:
                    return await client.post(path, json=body, headers=headers)
                except Exception as exc:
                    _anomaly(f"concurrent post {n} failed", exc)
                    raise

            first_wave = await asyncio.gather(*[one(n) for n in range(51)])
            second_wave = await asyncio.gather(*[one(n) for n in range(51)])
            listing = await client.get("/v1/events", headers=headers)
            health = await client.get("/health")

    assert [response.status_code for response in first_wave + second_wave] == [200] * 102
    accepted = []
    for n, response in enumerate(first_wave):
        assert response.json()["duplicate"] is False
        source = ("avrone", "greatscale", "cyclekernal")[n % 3]
        accepted.append((source, f"id-{n % 17}"))
    assert len(accepted) == len(set(accepted)) == 51
    assert all(response.json()["duplicate"] is True for response in second_wave)
    stored = {(event["source"], event["id"]) for event in listing.json()["events"]}
    assert stored == set(accepted)
    assert health.json()["events"]["stored"] == 51
    assert health.json()["events"]["accepted"] == 51
    assert health.json()["boot"] == main.BOOT_ID


def test_process_restart_keeps_dedup_and_changes_boot(tmp_path):
    env = os.environ.copy()
    env.update(
        {
            "CK_EVENTS_PATH": str(tmp_path / "events.json"),
            "CK_FUSION_TOKEN": "tcp-test-token",
            "CK_SYNTHETIC": "0",
            "WS_RELAY_URL": "ws://127.0.0.1:1/ws/out",
            "CK_RELAY_BACKOFF_INITIAL": "0.2",
            "CK_RELAY_BACKOFF_MAX": "0.5",
            "CK_EVENTS_MAX_RECENT": "1",
        }
    )
    bridge = Path(__file__).resolve().parents[1] / "src" / "bridge"
    log_path = tmp_path / "server.log"

    def start(listener: socket.socket) -> subprocess.Popen:
        log = log_path.open("a")
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--fd",
                str(listener.fileno()),
                "--no-access-log",
                "--log-level",
                "warning",
            ],
            cwd=bridge,
            env=env,
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        log.close()
        return process

    def wait_ready(base: str, process: subprocess.Popen) -> str:
        deadline = time.monotonic() + 20
        with httpx.Client(timeout=3, trust_env=False) as http:
            while True:
                if process.poll() is not None:
                    text = log_path.read_text(errors="replace")
                    _anomaly(f"server exited early\n{text}")
                    raise AssertionError(text)
                try:
                    response = http.get(base + "/health")
                    if response.status_code == 200 and response.json().get("boot"):
                        return response.json()["boot"]
                except httpx.HTTPError as exc:
                    if time.monotonic() > deadline:
                        _anomaly("health wait exhausted", exc)
                        raise
                if time.monotonic() > deadline:
                    text = log_path.read_text(errors="replace")
                    _anomaly(f"health deadline\n{text}")
                    raise AssertionError(text)
                time.sleep(0.05)

    body_gs = _fusion_event("shared", source="greatscale", kind="evidence", payload={"text": "gs"})
    body_av = _fusion_event("shared", source="avrone", payload={"text": "av"})
    headers = {"X-Admin-Token": "tcp-test-token"}
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        base = "http://127.0.0.1:" + str(listener.getsockname()[1])
        first = start(listener)
        try:
            boot_1 = wait_ready(base, first)
            with httpx.Client(timeout=5, trust_env=False) as http:
                assert http.post(base + "/v1/events", json=body_gs, headers=headers).json()["duplicate"] is False
                assert http.post(base + "/events", json=body_av, headers=headers).json()["duplicate"] is False
                oversized = http.post(base + "/v1/events", content=b"x" * 4097, headers=headers)
                assert oversized.status_code == 413
                assert oversized.json()["detail"] == "request body too large (max 4096 bytes)"
                chunked = http.post(base + "/v1/events", content=iter((b"a" * 2000, b"b" * 3000)), headers=headers)
                assert chunked.status_code == 413
                assert http.get(base + "/health").status_code == 200
        finally:
            first.terminate()
            try:
                first.wait(timeout=8)
            except subprocess.TimeoutExpired as exc:
                _anomaly("first server did not exit", exc)
                first.kill()
                first.wait(timeout=3)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        base = "http://127.0.0.1:" + str(listener.getsockname()[1])
        second = start(listener)
        try:
            boot_2 = wait_ready(base, second)
            with httpx.Client(timeout=5, trust_env=False) as http:
                replay_gs = http.post(base + "/v1/events", json=body_gs, headers=headers)
                replay_av = http.post(base + "/events", json=body_av, headers=headers)
                listed = http.get(base + "/v1/events", headers=headers).json()
        finally:
            second.terminate()
            try:
                second.wait(timeout=8)
            except subprocess.TimeoutExpired as exc:
                _anomaly("second server did not exit", exc)
                second.kill()
                second.wait(timeout=3)
    assert boot_1 != boot_2
    assert replay_gs.json()["duplicate"] is True
    assert replay_av.json()["duplicate"] is True
    texts = {event["source"]: event["payload"]["text"] for event in listed["events"]}
    assert texts.get("avrone") == "av" or "greatscale" in texts
    assert "gs" in texts.values() or "av" in texts.values()
