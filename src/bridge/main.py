"""
CycleKernel CognitiveBridge: explicit live-versus-synthetic LoopMem provenance.
A configured RELAY_URL means live-only ingestion: disconnects never silently
fall back to generated values that look like live telemetry.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from websockets import connect
from traits import map_metrics_to_traits, CognitiveState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cognitive-bridge")

app = FastAPI(
    title="CycleKernel CognitiveBridge",
    description="LoopMem metrics mapped to traits with explicit input provenance and fusion evidence",
    version="3.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXPECTED_DESCENT_SCHEMA = "great-scale.descent/v0.4.2"
current_state: CognitiveState = CognitiveState(metric_source="unavailable")
ws_clients: list = []


def normalize_relay_metrics(payload: Any) -> Dict[str, Any]:
    """Parse a WS relay frame and validate the minimum required metric vector."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError("relay message must be valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("relay message must be a JSON object")
    raw_metrics = payload.get("metrics", payload)
    if not isinstance(raw_metrics, Mapping):
        raise ValueError("relay 'metrics' field must be a JSON object")

    aliases = {
        "Core": ("Core", "core"),
        "U2": ("U2", "u2"),
        "L2": ("L2", "l2", "coupling"),
        "L5": ("L5", "l5", "entropy"),
    }
    normalized: Dict[str, Any] = {}
    for canonical, names in aliases.items():
        raw = next((raw_metrics[name] for name in names if name in raw_metrics), None)
        if raw is None:
            raise ValueError(f"relay metric {canonical} is required")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"relay metric {canonical} must be numeric") from exc
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"relay metric {canonical} must be finite and in [0, 1]")
        normalized[canonical] = value

    # Keep legacy names consumed by the trait mapper and NS fusion synchronized.
    normalized["entropy"] = normalized["L5"]
    normalized["coupling"] = normalized["L2"]

    # Optional companion fields remain distinct from LoopMem mood metrics. They
    # are never synthesized from Core/L2/L5; the Great Scale adapter validates
    # the configured [0, 7] scheduler residual domain separately.
    if "stress_residual" in raw_metrics:
        try:
            residual = float(raw_metrics["stress_residual"])
        except (TypeError, ValueError) as exc:
            raise ValueError("relay stress_residual must be numeric") from exc
        if not math.isfinite(residual) or not 0.0 <= residual <= 7.0:
            raise ValueError("relay stress_residual must be finite and in [0, 7]")
        if raw_metrics.get("descent_schema") != EXPECTED_DESCENT_SCHEMA:
            raise ValueError(f"relay stress_residual requires descent_schema={EXPECTED_DESCENT_SCHEMA}")
        normalized["stress_residual"] = residual
    for field in ("belief", "resources"):
        if field in raw_metrics:
            if not isinstance(raw_metrics[field], Mapping):
                raise ValueError(f"relay {field} must be a JSON object")
            normalized[field] = dict(raw_metrics[field])
    if "descent_schema" in raw_metrics:
        if not isinstance(raw_metrics["descent_schema"], str):
            raise ValueError("relay descent_schema must be a string")
        if raw_metrics["descent_schema"] != EXPECTED_DESCENT_SCHEMA:
            raise ValueError(f"unsupported relay descent_schema: {raw_metrics['descent_schema']}")
        normalized["descent_schema"] = raw_metrics["descent_schema"]
    return normalized


async def sync_state(metrics: Dict, metric_source: str = "unknown"):
    """Map current telemetry while preserving the source in the public state."""
    global current_state
    current_state = map_metrics_to_traits(metrics, metric_source=metric_source)
    logger.info(
        "Bridge state updated: mood=%s source=%s",
        current_state.mood,
        current_state.metric_source,
    )
    for ws in ws_clients[:]:
        try:
            await ws.send_json(current_state.to_dict())
        except Exception:
            if ws in ws_clients:
                ws_clients.remove(ws)


async def _synthetic_metrics_stream():
    while True:
        yield {
            "Core": 0.42,
            "U2": 0.31,
            "L2": 0.07,
            "L3": 0.55,
            "L4": 0.28,
            "L5": 0.65,
            "entropy": 0.65,
            "coupling": 0.07,
        }
        await asyncio.sleep(5)



async def _synthetic_heartbeat():
    """Development-only synthetic stream; every emitted state says synthetic."""
    async for metrics in _synthetic_metrics_stream():
        await sync_state(metrics, metric_source="synthetic")


@app.on_event("startup")
async def startup():
    logger.info("CognitiveBridge %s online; configuring metric source", "3.1.0")
    asyncio.create_task(subscribe_to_relay())


async def subscribe_to_relay():
    relay_url = os.environ.get("RELAY_URL", "").strip()
    allow_synthetic = os.environ.get("ALLOW_SYNTHETIC_RELAY", "1").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if not relay_url:
        if not allow_synthetic:
            current_state.metric_source = "unavailable"
            logger.error("RELAY_URL is unset and synthetic metrics are disabled")
            while True:
                await asyncio.sleep(5)
        logger.warning("RELAY_URL is unset; starting an explicitly labelled synthetic stream")
        await _synthetic_heartbeat()
        return

    # A configured relay is the source of truth. Never substitute synthetic
    # metrics on connect, schema, or stream failures.
    while True:
        try:
            logger.info("Connecting to configured WS Relay: %s", relay_url)
            async with connect(
                relay_url,
                open_timeout=5,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=3,
                max_size=1_048_576,
            ) as websocket:
                logger.info("Connected to WS Relay")
                async for raw_message in websocket:
                    metrics = normalize_relay_metrics(raw_message)
                    await sync_state(metrics, metric_source="relay")
                raise ConnectionError("WS Relay stream ended")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if current_state.metric_source == "relay":
                current_state.metric_source = "relay_stale"
            logger.warning("WS Relay failed; retrying without synthetic substitution: %s", exc)
            await asyncio.sleep(3)


@app.get("/v1/current_mood")
async def get_current_mood():
    """Read-only view with metric source, channel scores, and Great Scale diagnostics."""
    return current_state.to_dict()


@app.post("/v1/feedback")
async def ingest_feedback(payload: Dict):
    logger.info("Feedback received")
    return {"status": "ingested", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health")
async def health():
    source = current_state.metric_source
    healthy = source in ("relay", "synthetic")
    return {
        "status": "ghost-online" if healthy else "degraded",
        "version": "3.1.0",
        "metric_source": source,
        "state_timestamp": current_state.timestamp,
        "mood": current_state.mood,
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
