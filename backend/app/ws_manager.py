"""WebSocket 连接管理：向所有前端广播设备状态变化、批量进度、预览帧。"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

# 单个连接发送超时：慢客户端不能拖住其他人的广播
_SEND_TIMEOUT = 3.0


class WSManager:
    def __init__(self) -> None:
        self._conns: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        conns = list(self._conns)
        if not conns:
            return
        data = json.dumps(message, default=str)

        async def _send(ws: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=_SEND_TIMEOUT)
                return None
            except Exception:  # noqa: BLE001  连接已断 / 发送超时
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in conns))
        dead = [ws for ws in results if ws is not None]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._conns.discard(ws)

    @property
    def count(self) -> int:
        return len(self._conns)


manager = WSManager()
