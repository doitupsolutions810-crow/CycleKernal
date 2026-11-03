"""
CycleKernel Ghost Sync v3.2 - CognitiveBridge Service
The biological link between LoopMem heartbeat and LLM Agent consciousness.
Ingests real-time simulation metrics via WS Relay and maps to Evo-Psych traits.

Relay mode connects to WS_RELAY_URL (fallback RELAY_URL). The fixed sample
heartbeat runs only when CK_SYNTHETIC=1. POST /v1/events (alias POST /events)
accepts Fusion Bridge events: X-Admin-Token or Bearer, 4096-byte cap before
auth, and duplicate: true for an id already seen.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import math
import os
import re
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

import websockets
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from websockets.exceptions import ConnectionClosed

from traits import CognitiveState, map_metrics_to_traits

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cognitive-bridge")

VERSION = "3.3.0"
FUSION_MAX_BODY_BYTES = 4096
_EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
EVENT_SOURCES = ("avrone", "cyclekernal", "greatscale")
EVENT_KINDS = (
    "finding",
    "question",
    "answer",
    "correction",
    "conclusion",
    "mood",
    "evidence",
    "health",
)
DEFAULT_RELAY_URL = "ws://ws-relay:8081/ws/out"
METRIC_KEYS = (
    "Core",
    "core",
    "U2",
    "u2",
    "L2",
    "l2",
    "L3",
    "l3",
    "L4",
    "l4",
    "L5",
    "l5",
    "entropy",
    "coupling",
)

# Preserved sample used only when CK_SYNTHETIC=1. Previously this was the
# unconditional 5s heartbeat inside subscribe_to_relay.
SYNTHETIC_METRICS: Dict[str, float] = {
    "Core": 0.42,
    "U2": 0.31,
    "L2": 0.07,
    "L3": 0.55,
    "L4": 0.28,
    "L5": 0.65,
    "entropy": 0.65,
    "coupling": 0.07,
}


class FrameError(Exception):
    """A relay frame or event body that must be skipped without dropping the socket."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def synthetic_enabled() -> bool:
    return _truthy("CK_SYNTHETIC")


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using %s", name, raw, default)
        return default


def configured_relay_url() -> str:
    return (
        os.environ.get("WS_RELAY_URL")
        or os.environ.get("RELAY_URL")
        or DEFAULT_RELAY_URL
    ).strip()


def backoff_params() -> tuple[float, float, float]:
    initial = max(0.0, _float_env("CK_RELAY_BACKOFF_INITIAL", 1.0))
    factor = _float_env("CK_RELAY_BACKOFF_FACTOR", 2.0)
    if factor < 1.0:
        factor = 1.0
    maximum = max(initial, _float_env("CK_RELAY_BACKOFF_MAX", 30.0))
    return initial, factor, maximum


def next_backoff(
    previous: float | None,
    *,
    initial: float,
    factor: float,
    maximum: float,
) -> float:
    """Delay before the next attempt. ``previous is None`` starts at ``initial``."""
    if previous is None or previous <= 0:
        delay = initial
    else:
        delay = previous * factor
    return min(maximum, delay)


def _open_timeout() -> float:
    return max(0.05, _float_env("CK_RELAY_OPEN_TIMEOUT", 5.0))


def _max_frame_bytes() -> int:
    return max(1, _int_env("CK_RELAY_MAX_FRAME_BYTES", 65536))


def _hud_send_timeout() -> float:
    return max(0.01, _float_env("CK_HUD_SEND_TIMEOUT", 0.5))


def _clean_token(raw: str | None) -> str:
    return (raw or "").strip()


def accepted_tokens() -> list[str]:
    """Secrets that may call POST /v1/events.

    CK_FUSION_TOKEN is the contract name and wins over FUSION_TOKEN.
    CK_EVENTS_TOKEN and CK_EVENTS_TOKEN_PREVIOUS stay valid so compose and
    rotation keep working beside the fusion header.
    """
    found: list[str] = []
    names = ["CK_FUSION_TOKEN", "CK_EVENTS_TOKEN", "CK_EVENTS_TOKEN_PREVIOUS"]
    if not _clean_token(os.environ.get("CK_FUSION_TOKEN")):
        names.append("FUSION_TOKEN")
    for name in names:
        token = _clean_token(os.environ.get(name))
        if token and token not in found:
            found.append(token)
    return found


def events_token() -> str:
    tokens = accepted_tokens()
    return tokens[0] if tokens else ""


def events_max_bytes() -> int:
    """Fusion body cap. Never above 4096; CK_EVENTS_MAX_BYTES may only tighten it."""
    configured = _int_env("CK_EVENTS_MAX_BYTES", FUSION_MAX_BODY_BYTES)
    return max(1, min(FUSION_MAX_BODY_BYTES, configured))


def events_max_recent() -> int:
    return max(1, _int_env("CK_EVENTS_MAX_RECENT", 100))


def parse_metrics_frame(raw: Any) -> Dict[str, float]:
    """Accept a JSON object of LoopMem metrics, or ``{"metrics": {...}}``.

    Non-JSON, non-objects, missing metric fields, booleans, and non-finite
    numbers are rejected. The caller keeps the socket open.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FrameError("undecodable frame") from exc
    if not isinstance(raw, str):
        raise FrameError("frame is not text")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FrameError("malformed json") from exc
    if isinstance(data, dict) and isinstance(data.get("metrics"), dict):
        data = data["metrics"]
    if not isinstance(data, dict):
        raise FrameError("frame is not an object")
    present = [key for key in METRIC_KEYS if key in data]
    if not present:
        raise FrameError("no metric fields")
    metrics: Dict[str, float] = {}
    for key in present:
        value = data[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FrameError(f"non-numeric {key}")
        number = float(value)
        if not math.isfinite(number):
            raise FrameError(f"non-finite {key}")
        metrics[key] = number
    return metrics


class RelayStatus:
    def __init__(self) -> None:
        self.mode = "relay"
        self.url = ""
        self.connected = False
        self.attempts = 0
        self.frames_accepted = 0
        self.frames_rejected = 0
        self.backoff_seconds = 0.0
        self.backoff_trace: list[float] = []
        self.attempt_times: list[float] = []
        self.last_error: str | None = None

    def public(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "connected": self.connected,
            "attempts": self.attempts,
            "frames_accepted": self.frames_accepted,
            "frames_rejected": self.frames_rejected,
            "backoff_seconds": self.backoff_seconds,
            "last_error": self.last_error,
        }


def _finite_ts(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return time.time()
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return time.time()
    return number


def normalize_event(data: Any) -> tuple[Dict[str, Any] | None, str | None]:
    """Validate a POST /v1/events body. Returns (event, None) or (None, detail)."""
    if not isinstance(data, dict):
        return None, "body must be a JSON object"
    for field in ("id", "source", "kind", "run_id"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None, f"{field} is required"
    if not _EVENT_ID_RE.match(data["id"]):
        return None, "bad event id"
    if data["source"] not in EVENT_SOURCES:
        return None, "source must be one of " + ", ".join(EVENT_SOURCES)
    if data["kind"] not in EVENT_KINDS:
        return None, "kind must be one of " + ", ".join(EVENT_KINDS)
    if "payload" not in data:
        return None, "payload is required"
    if not isinstance(data["payload"], dict):
        return None, "payload must be a JSON object"
    event = {
        "id": data["id"],
        "source": data["source"],
        "kind": data["kind"],
        "run_id": data["run_id"][:80],
        "payload": data["payload"],
        "ts": _finite_ts(data.get("ts")),
    }
    return event, None


class EventLog:
    def __init__(self) -> None:
        self.accepted = 0
        self.rejected = 0
        self.rejected_auth = 0
        self.rejected_size = 0
        self.rejected_body = 0
        self.by_id: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.tombstones: OrderedDict[str, None] = OrderedDict()

    def public(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "rejected": self.rejected,
            "rejected_auth": self.rejected_auth,
            "rejected_size": self.rejected_size,
            "rejected_body": self.rejected_body,
            "stored": len(self.by_id),
            "auth_configured": bool(accepted_tokens()),
        }


_relay_guard = threading.Lock()
_events_guard = threading.Lock()
relay_status = RelayStatus()
event_log = EventLog()
current_state: CognitiveState = CognitiveState()
ws_clients: list = []


def reset_runtime_state() -> None:
    """Test helper. Safe only when the intake task is not running."""
    global current_state
    current_state = CognitiveState()
    ws_clients.clear()
    with _relay_guard:
        relay_status.mode = "synthetic" if synthetic_enabled() else "relay"
        relay_status.url = ""
        relay_status.connected = False
        relay_status.attempts = 0
        relay_status.frames_accepted = 0
        relay_status.frames_rejected = 0
        relay_status.backoff_seconds = 0.0
        relay_status.backoff_trace.clear()
        relay_status.attempt_times.clear()
        relay_status.last_error = None
    with _events_guard:
        event_log.accepted = 0
        event_log.rejected = 0
        event_log.rejected_auth = 0
        event_log.rejected_size = 0
        event_log.rejected_body = 0
        event_log.by_id.clear()
        event_log.tombstones.clear()


def _reject_event(reason: str) -> None:
    with _events_guard:
        event_log.rejected += 1
        if reason == "auth":
            event_log.rejected_auth += 1
        elif reason == "size":
            event_log.rejected_size += 1
        else:
            event_log.rejected_body += 1


def _presented_token(request: Request) -> str:
    admin = request.headers.get("x-admin-token", "").strip()
    if admin:
        return admin
    authorization = request.headers.get("authorization", "")
    if authorization:
        scheme, _, rest = authorization.partition(" ")
        if scheme.lower() != "bearer":
            return ""
        return rest.strip()
    return request.headers.get("x-events-token", "").strip()


def _authorized(request: Request) -> bool:
    supplied = _presented_token(request)
    tokens = accepted_tokens()
    if not supplied or not tokens:
        return False
    supplied_b = supplied.encode("utf-8")
    ok = False
    for token in tokens:
        # Compare every configured token so a rotation doesn't leak which one matched.
        ok = hmac.compare_digest(supplied_b, token.encode("utf-8")) or ok
    return ok


async def _read_capped(request: Request, max_bytes: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_len = int(declared)
        except ValueError:
            raise FrameError("invalid content-length") from None
        if declared_len > max_bytes:
            raise FrameError("payload too large")
    buf = bytearray()
    async for chunk in request.stream():
        if len(chunk) > max_bytes - len(buf):
            raise FrameError("payload too large")
        buf.extend(chunk)
    return bytes(buf)


async def _push_hud(payload: Dict[str, Any]) -> None:
    """Push state to HUD sockets. A slow client is dropped instead of stalling intake."""
    timeout = _hud_send_timeout()
    stale = []
    for ws in ws_clients[:]:
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=timeout)
        except Exception:
            stale.append(ws)
    for ws in stale:
        if ws in ws_clients:
            ws_clients.remove(ws)
        close = getattr(ws, "close", None)
        if close is None:
            continue
        with contextlib.suppress(Exception):
            result = close()
            if asyncio.iscoroutine(result):
                await result


async def sync_state(metrics: Dict):
    """
    The Ghost Function: maps simulation metrics to cognitive traits.
    High Entropy (L5 > 0.8) -> Creative/Divergent
    High Coupling (L2 > 0.05) -> Analytical/Convergent
    Low Core (Core < 0.1) -> Survival/Conservation
    """
    global current_state
    current_state = map_metrics_to_traits(metrics)
    logger.info("Ghost state updated: %s | traits=%s", current_state.mood, current_state.traits)
    await _push_hud(current_state.to_dict())


async def _handle_frame(raw: Any) -> None:
    try:
        metrics = parse_metrics_frame(raw)
    except FrameError as exc:
        with _relay_guard:
            relay_status.frames_rejected += 1
            relay_status.last_error = str(exc)
        logger.warning("Skipping relay frame: %s", exc)
        return
    await sync_state(metrics)
    with _relay_guard:
        relay_status.frames_accepted += 1
        relay_status.last_error = None


async def _synthetic_loop() -> None:
    logger.info("CK_SYNTHETIC=1; emitting fixed LoopMem metrics and not connecting")
    while True:
        await sync_state(dict(SYNTHETIC_METRICS))
        with _relay_guard:
            relay_status.connected = False
            relay_status.frames_accepted += 1
        interval = max(0.0, _float_env("CK_SYNTHETIC_INTERVAL", 5.0))
        await asyncio.sleep(interval)


async def _relay_loop() -> None:
    """Connect to the WS relay. Failures sleep with exponential backoff."""
    delay: float | None = None
    while True:
        url = configured_relay_url()
        initial, factor, maximum = backoff_params()
        with _relay_guard:
            relay_status.url = url
            relay_status.connected = False
            relay_status.attempts += 1
            relay_status.attempt_times.append(time.monotonic())
            if len(relay_status.attempt_times) > 32:
                del relay_status.attempt_times[:-32]
        try:
            async with websockets.connect(
                url,
                open_timeout=_open_timeout(),
                close_timeout=2,
                max_size=_max_frame_bytes(),
                compression=None,
                proxy=os.environ.get("CK_RELAY_PROXY") or None,
                ping_interval=_float_env("CK_RELAY_PING_INTERVAL", 20.0) or None,
            ) as ws:
                with _relay_guard:
                    relay_status.connected = True
                    relay_status.last_error = None
                # A live socket earns a fresh backoff curve for the next drop.
                delay = None
                while True:
                    await _handle_frame(await ws.recv())
        except asyncio.CancelledError:
            with _relay_guard:
                relay_status.connected = False
            raise
        except ConnectionClosed as exc:
            with _relay_guard:
                relay_status.connected = False
                relay_status.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Relay connection closed: %s", exc)
        except Exception as exc:
            with _relay_guard:
                relay_status.connected = False
                relay_status.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("Relay reconnect: %s", exc)
        initial, factor, maximum = backoff_params()
        delay = next_backoff(delay, initial=initial, factor=factor, maximum=maximum)
        with _relay_guard:
            relay_status.backoff_seconds = delay
            relay_status.backoff_trace.append(delay)
            if len(relay_status.backoff_trace) > 32:
                del relay_status.backoff_trace[:-32]
        await asyncio.sleep(delay)


async def subscribe_to_relay() -> None:
    """Subscribe to /ws/out on the WS Relay, unless CK_SYNTHETIC=1."""
    with _relay_guard:
        mode = relay_status.mode
    if mode == "synthetic":
        await _synthetic_loop()
    else:
        await _relay_loop()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with _relay_guard:
        relay_status.mode = "synthetic" if synthetic_enabled() else "relay"
        relay_status.url = configured_relay_url()
    logger.info(
        "CognitiveBridge v%s online. mode=%s relay=%s",
        VERSION,
        relay_status.mode,
        relay_status.url,
    )
    task = asyncio.create_task(subscribe_to_relay(), name="relay-subscribe")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="CycleKernel CognitiveBridge",
    description="Ghost Shell Integration - sync_state maps LoopMem to Evo-Psych traits",
    version=VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/v1/current_mood")
async def get_current_mood():
    """Polled by Chat Interface to dynamically update System Prompt."""
    return current_state.to_dict()


@app.post("/v1/feedback")
async def ingest_feedback(payload: Dict[str, Any]):
    """Closed-loop entry point: conversation outcomes feed back into LoopMem."""
    logger.info("Feedback received: %s", payload)
    return {"status": "ingested", "timestamp": _now()}


@app.get("/health")
async def health():
    with _relay_guard:
        mode = relay_status.mode
        relay = relay_status.public()
    with _events_guard:
        events = event_log.public()
    return {
        "status": "ghost-online",
        "version": VERSION,
        "timestamp": _now(),
        "mode": mode,
        "mood": current_state.mood,
        "relay": relay,
        "events": events,
    }


def _events_auth_failure() -> JSONResponse:
    _reject_event("auth")
    if not accepted_tokens():
        return JSONResponse(
            status_code=403,
            content={"detail": "Admin access is off. Set CK_FUSION_TOKEN or CK_EVENTS_TOKEN to enable it."},
        )
    return JSONResponse(status_code=401, content={"detail": "Bad admin token"})


def _too_large(max_bytes: int) -> JSONResponse:
    _reject_event("size")
    return JSONResponse(
        status_code=413,
        content={"detail": f"request body too large (max {max_bytes} bytes)"},
        headers={"Connection": "close"},
    )


def _store_event(event: Dict[str, Any]) -> bool:
    """Return True when the id was already seen. Do not overwrite or re-append."""
    eid = event["id"]
    if eid in event_log.by_id or eid in event_log.tombstones:
        return True
    event_log.by_id[eid] = event
    cap = events_max_recent()
    while len(event_log.by_id) > cap:
        old, _ = event_log.by_id.popitem(last=False)
        event_log.tombstones[old] = None
        seen_cap = max(cap * 10, 1000)
        while len(event_log.tombstones) > seen_cap:
            event_log.tombstones.popitem(last=False)
    event_log.accepted += 1
    return False


@app.post("/v1/events")
@app.post("/events")
async def post_event(request: Request):
    """Fusion Bridge intake. /events is the same handler as /v1/events."""
    max_bytes = events_max_bytes()
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            declared_len = int(declared)
        except ValueError:
            _reject_event("body")
            return JSONResponse(status_code=400, content={"detail": "bad content-length"})
        if declared_len > max_bytes:
            return _too_large(max_bytes)
    try:
        body = await _read_capped(request, max_bytes)
    except FrameError as exc:
        if "large" in str(exc):
            return _too_large(max_bytes)
        _reject_event("body")
        return JSONResponse(status_code=400, content={"detail": str(exc)})
    if not _authorized(request):
        return _events_auth_failure()
    if not body:
        _reject_event("body")
        return JSONResponse(status_code=400, content={"detail": "body must be JSON"})
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        _reject_event("body")
        return JSONResponse(status_code=400, content={"detail": "body must be JSON"})
    event, detail = normalize_event(payload)
    if detail or event is None:
        _reject_event("body")
        return JSONResponse(status_code=400, content={"detail": detail or "body must be a JSON object"})
    with _events_guard:
        duplicate = _store_event(event)
    return {"accepted": True, "duplicate": duplicate, "id": event["id"]}


@app.get("/v1/events")
@app.get("/events")
async def get_events(request: Request):
    if not _authorized(request):
        return _events_auth_failure()
    with _events_guard:
        return {
            "events": list(event_log.by_id.values()),
            "accepted": event_log.accepted,
            "stored": len(event_log.by_id),
        }


@app.websocket("/ws/hud")
async def hud_stream(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        await websocket.send_json(current_state.to_dict())
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8090)
