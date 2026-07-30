"""
CycleKernel Ghost Sync v3.1 - CognitiveBridge Service
The biological link between LoopMem heartbeat and LLM Agent consciousness.
Ingests real-time simulation metrics via WS Relay and maps to Evo-Psych traits.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import json
import logging
from typing import Dict
from datetime import datetime
from traits import map_metrics_to_traits, CognitiveState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cognitive-bridge")

app = FastAPI(
    title="CycleKernel CognitiveBridge",
    description="Ghost Shell Integration - sync_state maps LoopMem to Evo-Psych traits",
    version="3.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

current_state: CognitiveState = CognitiveState()
ws_clients: list = []

@app.on_event("startup")
async def startup():
    logger.info("CognitiveBridge v3.1-ghost-sync online. Subscribing to WS Relay...")
    asyncio.create_task(subscribe_to_relay())

async def subscribe_to_relay():
    """Subscribe to /ws/out on the WS Relay (Nervous System)."""
    while True:
        try:
            logger.info("Attempting relay connection / simulation heartbeat")
            # In full docker network this connects to ws://ws-relay:8081/ws/out
            # For standalone we drive a synthetic LoopMem stream
            await sync_state({
                "Core": 0.42,
                "U2": 0.31,
                "L2": 0.07,
                "L3": 0.55,
                "L4": 0.28,
                "L5": 0.65,
                "entropy": 0.65,
                "coupling": 0.07
            })
            await asyncio.sleep(5)
        except Exception as e:
            logger.warning(f"Relay reconnect: {e}")
            await asyncio.sleep(3)

async def sync_state(metrics: Dict):
    """
    The Ghost Function: maps simulation metrics to cognitive traits.
    High Entropy (L5 > 0.8) -> Creative/Divergent
    High Coupling (L2 > 0.05) -> Analytical/Convergent
    Low Core (Core < 0.1) -> Survival/Conservation
    """
    global current_state
    current_state = map_metrics_to_traits(metrics)
    logger.info(f"Ghost state updated: {current_state.mood} | traits={current_state.traits}")
    for ws in ws_clients[:]:
        try:
            await ws.send_json(current_state.to_dict())
        except Exception:
            if ws in ws_clients:
                ws_clients.remove(ws)

@app.get("/v1/current_mood")
async def get_current_mood():
    """Polled by Chat Interface to dynamically update System Prompt."""
    return current_state.to_dict()

@app.get("/health")
async def health():
    return {"status": "ghost-online", "version": "3.1.0", "timestamp": datetime.utcnow().isoformat()}

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
