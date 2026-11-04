"""预览分发中枢：每台设备只采集一次，按订阅者分发同一帧。

原实现每个 WebSocket 客户端各跑一条预览循环、逐台串行截图：
N 个观众会对同一台设备重复截图 N 次，而且一台设备慢会拖住整条循环。
现在改为「设备 → 一个采集协程」：帧推给所有订阅者，慢客户端直接丢帧。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket

from .database import SessionLocal
from .models import Device
from .orchestrator.base import DeviceUnreachable
from .services import backend

_log = logging.getLogger("preview")

_SEND_TIMEOUT = 2.0  # 单帧发送超时：超过即视为慢客户端，本轮丢帧
_MIN_INTERVAL = 0.3  # 采集间隔下限，避免截图把 adb 打爆（约 3fps）
_MAX_FPS = 15
FRAME_TTL = 5.0  # 截图接口复用帧的窗口期：同一设备 5s 内只真截一次
MAX_FRAME_ENTRIES = 500  # 帧缓存条数上限，防止设备很多时内存无界增长


class PreviewHub:
    def __init__(self) -> None:
        self._subs: dict[int, dict[WebSocket, int]] = {}  # device_id -> {ws: fps}
        self._tasks: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._frames: dict[int, tuple[float, str]] = {}  # device_id -> (ts, frame)

    # ---- 帧缓存：截图接口 / 缩略图复用，避免一屏 N 张卡重复打 adb ----
    def cached_frame(self, dev_id: int, ttl: float | None = None) -> str | None:
        item = self._frames.get(dev_id)
        if not item:
            return None
        ts, frame = item
        if time.time() - ts > (FRAME_TTL if ttl is None else ttl):
            return None
        return frame

    def store_frame(self, dev_id: int, frame: str) -> None:
        if not frame:
            return
        self._frames[dev_id] = (time.time(), frame)
        self._sweep_frames()

    def _sweep_frames(self) -> None:
        now = time.time()
        for dev_id, (ts, _) in list(self._frames.items()):
            if now - ts > FRAME_TTL:
                self._frames.pop(dev_id, None)
        if len(self._frames) > MAX_FRAME_ENTRIES:
            # 超上限时优先淘汰最旧的帧
            keep = sorted(self._frames.items(), key=lambda kv: kv[1][0], reverse=True)[
                :MAX_FRAME_ENTRIES
            ]
            self._frames = dict(keep)

    @property
    def task_count(self) -> int:
        """当前正在采集的设备数（测试/观测用）。"""
        return len(self._tasks)

    @property
    def frame_cache_size(self) -> int:
        return len(self._frames)

    async def subscribe(self, ws: WebSocket, device_ids: list[int], fps: int) -> None:
        fps = max(1, min(_MAX_FPS, int(fps or 1)))
        wanted = set(device_ids)
        async with self._lock:
            # 退订不再关注的设备
            for dev_id in list(self._subs):
                if dev_id not in wanted:
                    subs = self._subs[dev_id]
                    subs.pop(ws, None)
                    if not subs:
                        self._drop(dev_id)

            for dev_id in wanted:
                self._subs.setdefault(dev_id, {})[ws] = fps
                task = self._tasks.get(dev_id)
                if task is None or task.done():
                    self._tasks[dev_id] = asyncio.create_task(self._collect(dev_id))

    async def unsubscribe(self, ws: WebSocket) -> None:
        async with self._lock:
            for dev_id in list(self._subs):
                subs = self._subs[dev_id]
                subs.pop(ws, None)
                if not subs:
                    self._drop(dev_id)

    def _drop(self, dev_id: int) -> None:
        """移除设备订阅并停止采集协程。调用方需持有 _lock。"""
        self._subs.pop(dev_id, None)
        task = self._tasks.pop(dev_id, None)
        if task is not None and not task.done():
            task.cancel()

    async def _collect(self, dev_id: int) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                subs = self._subs.get(dev_id)
                if not subs:
                    return
                interval = max(_MIN_INTERVAL, 1.0 / max(1, max(subs.values())))
                started = loop.time()
                await self._tick(dev_id, subs)
                await asyncio.sleep(max(0.0, interval - (loop.time() - started)))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  采集协程不能因单次异常退出
            _log.exception("预览采集异常 device=%s", dev_id)

    async def _tick(self, dev_id: int, subs: dict[WebSocket, int]) -> None:
        async with SessionLocal() as db:
            device = await db.get(Device, dev_id)
        if device is None:
            return

        try:
            frame = await backend.screenshot(device)
        except DeviceUnreachable as e:
            # 失联必须如实告知，不能用旧帧/皮肤图假装正常
            await self._fanout(subs, {
                "type": "device_unreachable",
                "device_id": dev_id,
                "name": device.name,
                "detail": e.detail,
            })
            return
        except Exception:  # noqa: BLE001  单台失败不影响其它设备
            return

        await self._fanout(subs, {"type": "preview", "device_id": dev_id, "frame": frame})
        self.store_frame(dev_id, frame)

    async def _fanout(self, subs: dict[WebSocket, int], message: dict) -> None:
        if not subs:
            return
        data = json.dumps(message, default=str)

        async def _send(ws: WebSocket) -> WebSocket | None:
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=_SEND_TIMEOUT)
                return None
            except Exception:  # noqa: BLE001  慢/断开的连接直接淘汰
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in list(subs)))
        dead = [ws for ws in results if ws is not None]
        if not dead:
            return

        async with self._lock:
            for dev_id, current in list(self._subs.items()):
                for ws in dead:
                    current.pop(ws, None)
                if not current:
                    self._drop(dev_id)


hub = PreviewHub()
