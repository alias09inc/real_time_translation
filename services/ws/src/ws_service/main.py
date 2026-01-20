"""WebSocket caption broadcast service."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict


class PublishMessage(BaseModel):
    """Message payload broadcasted to connected WebSocket clients."""

    model_config = ConfigDict(extra="allow")

    type: str
    ts: float | None = None


class ConnectionManager:
    """Manage WebSocket client connections and broadcasts."""

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self._connections:
            return

        stale: list[WebSocket] = []
        for websocket in list(self._connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                stale.append(websocket)

        if stale:
            async with self._lock:
                for websocket in stale:
                    self._connections.discard(websocket)


manager = ConnectionManager()
app = FastAPI()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/publish")
async def publish(message: PublishMessage) -> dict[str, Any]:
    payload = message.model_dump(exclude_none=True)
    payload.setdefault("ts", time.time())
    await manager.broadcast(payload)
    return {"status": "ok", "connections": manager.connection_count}


@app.websocket("/ws/caption")
async def caption_ws(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
    except Exception:
        await manager.disconnect(websocket)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
