"""批量操作 + 同步操控（demo 验收 §7：一键让全部设备打开同一网页并同步执行一组操作）。

D11 批量开 URL / 批量点击·滑动·输入 / 批量装 APK；
D12 同步操控（1 控 N）：主控动作广播到选中从机，跨分辨率坐标适配。
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..rbac import require_operator
from ..database import get_db
from ..models import Device
from ..schemas import (
    BatchInstall,
    BatchKey,
    BatchOpenUrl,
    BatchResult,
    BatchSwipe,
    BatchTap,
    BatchText,
)
from .. import services
from ..config import settings
from ..ws_manager import manager

router = APIRouter(prefix="/batch", tags=["batch"], dependencies=[Depends(get_current_user)])

logger = logging.getLogger(__name__)

# 进度广播最小间隔：500 台逐台广播会刷屏，节流后再推（最后一台仍保证送达）
_PROGRESS_INTERVAL = 0.15


async def _fetch(db: AsyncSession, ids: list[int]) -> list[Device]:
    return list((await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all())


async def _run_all(db: AsyncSession, ids: list[int], action_name: str, fn) -> BatchResult:
    """对目标设备限并发执行 fn(device)，节流广播进度，汇总结果。

    并发上限由 CLOUD_BATCH_CONCURRENCY 控制：无上限直接 gather 在 500 台规模下
    会瞬间拉起数百个 adb/docker 子进程，反而拖垮整机。
    """
    devices = await _fetch(db, ids)
    details: list[dict] = []
    total = len(devices)
    done = 0
    sem = asyncio.Semaphore(max(1, settings.batch_concurrency))
    last_emit = 0.0
    emit_lock = asyncio.Lock()

    async def _emit(final: bool = False) -> None:
        nonlocal last_emit
        async with emit_lock:
            now = time.monotonic()
            if not final and now - last_emit < _PROGRESS_INTERVAL:
                return
            last_emit = now
            await manager.broadcast(
                {"type": "batch_progress", "action": action_name, "done": done, "total": total}
            )

    async def _one(device: Device) -> None:
        nonlocal done
        try:
            async with sem:
                await fn(device)
            details.append({"device_id": device.id, "name": device.name, "ok": True})
        except Exception as e:  # noqa: BLE001
            details.append({"device_id": device.id, "name": device.name, "ok": False, "error": str(e)})
        finally:
            done += 1
            await _emit(final=done >= total)

    await asyncio.gather(*[_one(d) for d in devices])
    await db.commit()
    ok = sum(1 for d in details if d["ok"])
    return BatchResult(total=total, ok=ok, failed=total - ok, details=details)


def _scale(
    device: Device,
    x: int,
    y: int,
    ref_w: int = 1080,
    ref_h: int = 1920,
) -> tuple[int, int]:
    """跨分辨率坐标适配：主控坐标按「主控设备实际分辨率」折算到目标设备。

    ref_w/ref_h 由调用方传入主控真实分辨率；调用方取不到时回落到 1080×1920 基准，
    并在日志里留痕，避免不同分辨率下点击偏移却无从排查。
    """
    return int(x * device.width / ref_w), int(y * device.height / ref_h)


def _source_dims(body: BatchTap | BatchSwipe) -> tuple[int, int]:
    sw, sh = body.source_width, body.source_height
    if sw and sh:
        return sw, sh
    logger.info(
        "batch 坐标缺少主控分辨率，回落 1080x1920 基准（action 目标 %s 台）",
        len(body.device_ids),
    )
    return 1080, 1920


@router.post("/open_url", response_model=BatchResult, dependencies=[Depends(require_operator)])
async def batch_open_url(body: BatchOpenUrl, db: AsyncSession = Depends(get_db)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.open_url(d, body.url)
        await services.broadcast_device(d)

    return await _run_all(db, body.device_ids, "open_url", fn)


@router.post("/tap", response_model=BatchResult, dependencies=[Depends(require_operator)])
async def batch_tap(body: BatchTap, db: AsyncSession = Depends(get_db)) -> BatchResult:
    ref_w, ref_h = _source_dims(body)

    async def fn(d: Device) -> None:
        x, y = _scale(d, body.x, body.y, ref_w, ref_h)
        await services.backend.tap(d, x, y)

    return await _run_all(db, body.device_ids, "tap", fn)


@router.post("/swipe", response_model=BatchResult, dependencies=[Depends(require_operator)])
async def batch_swipe(body: BatchSwipe, db: AsyncSession = Depends(get_db)) -> BatchResult:
    ref_w, ref_h = _source_dims(body)

    async def fn(d: Device) -> None:
        x1, y1 = _scale(d, body.x1, body.y1, ref_w, ref_h)
        x2, y2 = _scale(d, body.x2, body.y2, ref_w, ref_h)
        await services.backend.swipe(d, x1, y1, x2, y2, body.duration_ms)

    return await _run_all(db, body.device_ids, "swipe", fn)


@router.post("/text", response_model=BatchResult, dependencies=[Depends(require_operator)])
async def batch_text(body: BatchText, db: AsyncSession = Depends(get_db)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.input_text(d, body.text)

    return await _run_all(db, body.device_ids, "text", fn)


@router.post("/key", response_model=BatchResult, dependencies=[Depends(require_operator)])
async def batch_key(body: BatchKey, db: AsyncSession = Depends(get_db)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.key(d, body.key)

    return await _run_all(db, body.device_ids, "key", fn)


@router.post("/install", response_model=BatchResult, dependencies=[Depends(require_operator)])
async def batch_install(body: BatchInstall, db: AsyncSession = Depends(get_db)) -> BatchResult:
    async def fn(d: Device) -> None:
        await services.backend.install(d, body.apk_url)

    return await _run_all(db, body.device_ids, "install", fn)
