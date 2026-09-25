"""
WebSocket connection manager.

The ingestion pipeline runs in a worker thread (FastAPI BackgroundTasks run
sync functions in the threadpool). WebSocket objects belong to the server's
main event loop, so a worker thread must NOT await on them from its own loop
(the first prototype did `asyncio.run(...)` in the worker, which created a
second loop, failed on send, and silently disconnected every client).

Fix: the main loop is captured at startup and worker threads call
`ws_manager.notify(...)`, which schedules the broadcast on that loop with
asyncio.run_coroutine_threadsafe.
"""
from __future__ import annotations

import asyncio

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    async def connect(self, case_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(case_id, []).append(websocket)

    def disconnect(self, case_id: str, websocket: WebSocket) -> None:
        conns = self._connections.get(case_id, [])
        if websocket in conns:
            conns.remove(websocket)

    async def broadcast(self, case_id: str, payload: dict) -> None:
        """Sends to subscribers of this case_id and to '*' subscribers."""
        for key in (case_id, "*"):
            for ws in list(self._connections.get(key, [])):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.disconnect(key, ws)

    def notify(self, case_id: str, payload: dict) -> None:
        """Thread-safe, fire-and-forget broadcast (usable from sync code)."""
        loop = self.loop
        if loop is None or loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(case_id, payload), loop)
        except RuntimeError:
            pass


ws_manager = ConnectionManager()
