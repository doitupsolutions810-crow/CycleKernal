"""
CognitiveBridge Service — CycleKernel Master v4.0
Shared mood engine for all sub-agents and the orchestrator.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import logging
from typing import Dict
from datetime import datetime
from traits import map_metrics_to_traits, CognitiveState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cognitive-bridge")

app = FastAPI(title="CycleKernel CognitiveBridge", version="4.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

current_state = CognitiveState()
ws_clients: list = []


@app.on_event("startup")
async def startup():
    logger.info("CognitiveBridge v4.0 online")
    asyncio.create_task(_synthetic_heartbeat())


async def _synthetic_heartbeat():
    """Drives a continuous LoopMem stream when no external WS Relay is present."""
    import math
    t = 0.0
    while True:
        t += 0.08
        metrics = {
            "Core": 0.25 + 0.55 * (0.5 + 0.5 * math.sin(t * 0.35)),
            "U2": 0.3 + 0.4 * (0.5 + 0.5 * math.sin(t * 0.6 + 1)),
            "L2": 0.01 + 0.09 * (0.5 + 0.5 * math.sin(t * 0.9 + 2)),
            "L5": 0.3 + 0.6 * (0.5 + 0.5 * math.sin(t * 0.5)),
            "entropy": 0.3 + 0.6 * (0.5 + 0.5 * math.sin(t * 0.5)),
            "coupling": 0.01 + 0.09 * (0.5 + 0.5 * math.sin(t * 0.9 + 2)),
        }
        await sync_state(metrics)
        await asyncio.sleep(1.5)


async def sync_state(metrics: Dict):
    global current_state
    current_state = map_metrics_to_traits(metrics)
    for ws in ws_clients[:]:
        try:
            await ws.send_json(current_state.to_dict())
        except Exception:
            if ws in ws_clients:
                ws_clients.remove(ws)


@app.get("/v1/current_mood")
async def get_current_mood():
    return current_state.to_dict()


@app.post("/v1/feedback")
async def ingest_feedback(payload: Dict):
    """Closed-loop entry point: conversation outcomes feed back into LoopMem."""
    logger.info(f"Feedback received: {payload}")
    return {"status": "ingested", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health")
async def health():
    return {"status": "ghost-online", "version": "4.0.0", "mood": current_state.mood}


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
