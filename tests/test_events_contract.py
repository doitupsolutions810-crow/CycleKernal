"""POST /v1/events conformance with the Fusion Bridge CONTRACT.md.

The relay sends X-Admin-Token to /v1/events, refuses bodies over 4096 bytes
before it will treat a 401 as auth failure, and relies on duplicate: true.
"""

from __future__ import annotations

import json
import socket

import pytest
from fastapi.testclient import TestClient

import main
from test_bridge_relay import _fusion_event


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def bridge_env(monkeypatch):
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
    monkeypatch.delenv("WS_RELAY_URL", raising=False)
    monkeypatch.setenv("RELAY_URL", f"ws://127.0.0.1:{_closed_port()}/ws/out")
    main.reset_runtime_state()
    yield
    main.reset_runtime_state()

CAP = 4096
TOO_LARGE = {"detail": "request body too large (max 4096 bytes)"}


def _admin(token: str = "test-token") -> dict:
    return {"X-Admin-Token": token}


def _sized_event(size: int) -> bytes:
    skeleton = {
        "id": "cap-0001",
        "source": "avrone",
        "kind": "finding",
        "run_id": "run-1",
        "payload": {"text": ""},
        "ts": 1700000000.0,
    }
    encoded = json.dumps(skeleton, separators=(",", ":")).encode("utf-8")
    pad = size - len(encoded)
    if pad < 0:
        raise ValueError(f"skeleton is already {len(encoded)} bytes")
    return encoded.replace(b'"text":""', b'"text":"' + (b"p" * pad) + b'"', 1)


def test_v1_events_accepts_admin_token_and_events_alias(bridge_env):
    with TestClient(main.app) as client:
        created = client.post("/v1/events", json=_fusion_event("find0000001"), headers=_admin())
        alias = client.post("/events", json=_fusion_event("find0000002"), headers=_admin())
        listed = client.get("/v1/events", headers=_admin())
        mood_before = client.get("/v1/current_mood").json()["mood"]
        client.post(
            "/v1/events",
            json=_fusion_event("find0000003", source="greatscale", kind="evidence"),
            headers=_admin(),
        )
        mood_after = client.get("/v1/current_mood").json()["mood"]
    assert created.status_code == 200
    assert created.json() == {"accepted": True, "duplicate": False, "id": "find0000001"}
    assert alias.status_code == 200
    assert alias.json()["duplicate"] is False
    assert [event["id"] for event in listed.json()["events"]] == ["find0000001", "find0000002"]
    assert mood_before == mood_after


def test_duplicate_id_does_not_store_or_replace(bridge_env):
    with TestClient(main.app) as client:
        first = client.post(
            "/v1/events",
            json=_fusion_event("find0000001", payload={"text": "original"}),
            headers=_admin(),
        )
        again = client.post(
            "/events",
            json=_fusion_event("find0000001", payload={"text": "replacement"}, kind="conclusion"),
            headers=_admin(),
        )
        listed = client.get("/events", headers=_admin()).json()
    assert first.json()["duplicate"] is False
    assert again.status_code == 200
    assert again.json() == {"accepted": True, "duplicate": True, "id": "find0000001"}
    assert listed["stored"] == 1
    assert listed["accepted"] == 1
    assert listed["events"][0]["payload"] == {"text": "original"}
    assert listed["events"][0]["kind"] == "finding"


def test_evicted_id_stays_a_duplicate(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_EVENTS_MAX_RECENT", "1")
    with TestClient(main.app) as client:
        client.post("/v1/events", json=_fusion_event("evt-old"), headers=_admin())
        client.post("/v1/events", json=_fusion_event("evt-new"), headers=_admin())
        replay = client.post("/v1/events", json=_fusion_event("evt-old", payload={"text": "back"}), headers=_admin())
        listed = client.get("/v1/events", headers=_admin()).json()
    assert replay.json()["duplicate"] is True
    assert [event["id"] for event in listed["events"]] == ["evt-new"]
    assert listed["accepted"] == 2


def test_over_4096_is_413_before_auth(bridge_env, monkeypatch):
    over = b"x" * (CAP + 1)
    with TestClient(main.app) as client:
        wrong = client.post(
            "/v1/events",
            content=over,
            headers={"X-Admin-Token": "nope", "Content-Type": "application/json"},
        )
        missing = client.post("/v1/events", content=over, headers={"Content-Type": "application/json"})
        health = client.get("/health").json()
    assert wrong.status_code == 413
    assert wrong.json() == TOO_LARGE
    assert wrong.headers["connection"] == "close"
    assert missing.status_code == 413
    assert health["events"]["rejected_auth"] == 0
    assert health["events"]["rejected_size"] == 2
    assert health["events"]["stored"] == 0

    monkeypatch.delenv("CK_EVENTS_TOKEN", raising=False)
    main.reset_runtime_state()
    with TestClient(main.app) as client:
        closed = client.post("/v1/events", content=over, headers={"Content-Type": "application/json"})
        small = client.post("/v1/events", json=_fusion_event("evt-off"), headers=_admin())
    assert closed.status_code == 413
    assert closed.json() == TOO_LARGE
    assert small.status_code == 403


def test_exact_4096_byte_body_is_accepted(bridge_env):
    body = _sized_event(CAP)
    assert len(body) == CAP
    one_over = _sized_event(CAP + 1)
    assert len(one_over) == CAP + 1
    with TestClient(main.app) as client:
        exact = client.post(
            "/v1/events",
            content=body,
            headers={**_admin(), "Content-Type": "application/json"},
        )
        over = client.post(
            "/v1/events",
            content=one_over,
            headers={**_admin(), "Content-Type": "application/json"},
        )
        stored = client.get("/v1/events", headers=_admin()).json()
    assert exact.status_code == 200
    assert exact.json() == {"accepted": True, "duplicate": False, "id": "cap-0001"}
    assert over.status_code == 413
    assert stored["stored"] == 1
    assert stored["events"][0]["payload"]["text"].startswith("p")


def test_contract_field_rules(bridge_env):
    long_run = "r" * 100
    with TestClient(main.app) as client:
        missing = client.post("/v1/events", json={"id": "evt-1"}, headers=_admin())
        bad_id = client.post("/v1/events", json=_fusion_event("has space"), headers=_admin())
        bad_source = client.post("/v1/events", json=_fusion_event("evt-src", source="fusion"), headers=_admin())
        bad_kind = client.post("/v1/events", json=_fusion_event("evt-kind", kind="Mood"), headers=_admin())
        bad_payload = client.post(
            "/v1/events",
            json=_fusion_event("evt-pay", payload=["nope"]),
            headers=_admin(),
        )
        clipped = client.post(
            "/v1/events",
            json=_fusion_event("evt-run", run_id=long_run, ts="not-a-time"),
            headers=_admin(),
        )
        listed = client.get("/v1/events", headers=_admin()).json()
    assert missing.status_code == 400
    assert missing.json()["detail"] == "source is required"
    assert bad_id.json()["detail"] == "bad event id"
    assert "avrone" in bad_source.json()["detail"]
    assert "finding" in bad_kind.json()["detail"]
    assert bad_payload.json()["detail"] == "payload must be a JSON object"
    assert clipped.status_code == 200
    stored = listed["events"][0]
    assert stored["run_id"] == "r" * 80
    assert isinstance(stored["ts"], float) and stored["ts"] > 0


def test_fusion_token_wins_over_shared_token(bridge_env, monkeypatch):
    monkeypatch.setenv("CK_FUSION_TOKEN", "fusion-secret")
    monkeypatch.setenv("FUSION_TOKEN", "shared-secret")
    with TestClient(main.app) as client:
        shared = client.post("/v1/events", json=_fusion_event("evt-shared"), headers=_admin("shared-secret"))
        fusion = client.post("/v1/events", json=_fusion_event("evt-fusion"), headers=_admin("fusion-secret"))
        bearer = client.post("/v1/events", json=_fusion_event("evt-bearer"), headers={"Authorization": "Bearer test-token"})
    assert shared.status_code == 401
    assert shared.json()["detail"] == "Bad admin token"
    assert fusion.status_code == 200
    assert bearer.status_code == 200
