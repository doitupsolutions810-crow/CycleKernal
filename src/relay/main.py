"""WebSocket relay for LoopMem frames.

Subscribers connect to ``/ws/out`` (the cognitive bridge). Publishers connect to
``/ws/in`` or ``POST /publish``. A subscriber that falls behind is bounded by
``CK_RELAY_QUEUE_MAX``; the oldest queued frame is dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse


def queue_max() -> int:
    raw = os.environ.get("CK_RELAY_QUEUE_MAX", "32")
    try:
        return max(1, int(raw))
    except ValueError:
        return 32


def send_delay() -> float:
    raw = os.environ.get("CK_RELAY_SEND_DELAY", "0")
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


class RelayHub:
    def __init__(self) -> None:
        self.queues: dict[int, asyncio.Queue[str]] = {}
        self.published = 0
        self.dropped = 0

    def reset(self) -> None:
        self.queues.clear()
        self.published = 0
        self.dropped = 0

    def publish(self, message: str) -> int:
        """Enqueue ``message`` for every subscriber. Drop the oldest when full."""
        self.published += 1
        delivered = 0
        for queue in list(self.queues.values()):
            while queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                self.dropped += 1
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self.dropped += 1
                continue
            delivered += 1
        return delivered


hub = RelayHub()
app = FastAPI(title="CycleKernel WS Relay", version="1.0.0")


async def _send_loop(websocket: WebSocket, queue: asyncio.Queue[str]) -> None:
    while True:
        message = await queue.get()
        delay = send_delay()
        if delay:
            await asyncio.sleep(delay)
        await websocket.send_text(message)


@app.get("/health")
async def health():
    return {
        "status": "relay-online",
        "subscribers": len(hub.queues),
        "published": hub.published,
        "dropped": hub.dropped,
    }


@app.post("/publish")
async def publish(request: Request):
    body = await request.body()
    if not body:
        return JSONResponse(status_code=400, content={"error": "empty body"})
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse(status_code=400, content={"error": "undecodable body"})
    delivered = hub.publish(text)
    return {"delivered": delivered, "subscribers": len(hub.queues), "dropped": hub.dropped}


@app.websocket("/ws/out")
async def subscribe(websocket: WebSocket):
    await websocket.accept()
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=queue_max())
    key = id(websocket)
    hub.queues[key] = queue
    sender = asyncio.create_task(_send_loop(websocket, queue))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.queues.pop(key, None)
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sender


@app.websocket("/ws/in")
async def ingest(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            hub.publish(await websocket.receive_text())
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
