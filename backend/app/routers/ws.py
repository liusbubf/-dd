"""WebSocket：实时推送设备状态/批量进度（广播）+ 按订阅推送预览帧。

前端消息协议：
  客户端 → 服务端: {"type":"subscribe","device_ids":[1,2,3],"fps":1}
  服务端 → 客户端:
    {"type":"device_status","device":{...}}
    {"type":"batch_progress","action":"open_url","done":3,"total":10}
    {"type":"preview","device_id":1,"frame":"data:image/svg+xml;base64,..."}
    {"type":"device_unreachable","device_id":1,"name":"真机-001","detail":"device offline"}
    {"type":"script_done","run_id":1,"status":"success"}

连接必须在握手阶段携带 ?token=<JWT>：浏览器 WebSocket 无法自定义 Authorization 头，
且未鉴权的连接既不能接收状态广播，也不能订阅设备画面。
"""
from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..auth import authenticate_ws_token
from ..database import SessionLocal
from ..preview_hub import hub
from ..ws_manager import manager

router = APIRouter()

_WS_UNAUTHORIZED = 4401


@router.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    async with SessionLocal() as db:
        user = await authenticate_ws_token(ws.query_params.get("token"), db)
    if user is None:
        # 未 accept 直接关闭 → 握手阶段返回 403，连接不会进入广播集合
        await ws.close(code=_WS_UNAUTHORIZED)
        return

    await manager.connect(ws)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "subscribe":
                continue
            ids: list[int] = []
            for raw in msg.get("device_ids", []) or []:
                try:
                    ids.append(int(raw))
                except (TypeError, ValueError):
                    continue
            try:
                fps = int(msg.get("fps", 1) or 1)
            except (TypeError, ValueError):
                fps = 1
            await hub.subscribe(ws, ids, fps)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001  客户端异常断开
        pass
    finally:
        await hub.unsubscribe(ws)
        await manager.disconnect(ws)
