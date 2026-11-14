"""Phát trạng thái và cảnh báo mới tới các web app đang mở qua WebSocket.

Chạy 1 tiến trình uvicorn (đủ cho đồ án). Nếu chạy nhiều worker thì cần
Redis pub/sub hoặc LISTEN/NOTIFY của PostgreSQL để các worker thấy nhau.
"""
import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, kind: str, data) -> None:
        text = json.dumps({"type": kind, "data": data}, default=str)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(text)
            except Exception:  # client đã đóng
                log.debug("drop websocket client")
                await self.disconnect(ws)


manager = ConnectionManager()
