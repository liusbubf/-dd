"""iOS 皮肤查看器 + 一键换肤接口。

- 查看：按设备指纹渲染 7 套「iOS 设计语言」原创皮肤界面（主屏/今天/资源库/搜索/锁屏/控制中心/Safari）。
- 换肤：为设备切换皮肤主题（ios / sunset / glass），主题写入 device.skin，
  下一帧预览与皮肤查看器即按新主题渲染。支持单台与批量。

皮肤为 100% 原创矢量设计，仅还原设计语言，不使用 Apple 实际图标/壁纸/字体素材。
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import SessionLocal, get_db
from ..models import Device, User
from ..preview import THEME_LIST, THEMES, render_frame
from ..rbac import record_audit, require_operator
from ..services import backend
from ..ws_manager import manager

router = APIRouter(prefix="/skin", tags=["skin"], dependencies=[Depends(get_current_user)])

_SCREENS = {"home", "lock", "control", "browser", "applibrary", "spotlight", "today"}
_log = logging.getLogger("skin")
_bg_tasks: set[asyncio.Task] = set()

# 真机落地进度：device_id -> {device_id, phase, theme}
# phase: queued/launcher/grid/wallpaper/reboot/prefs（done/failed 广播后即移除）
_progress: dict[int, dict] = {}


async def _report_progress(device_id: int, theme: str, phase: str) -> None:
    info = {"device_id": device_id, "phase": phase, "theme": theme}
    if phase in ("done", "failed"):
        _progress.pop(device_id, None)
    else:
        _progress[device_id] = info
    await manager.broadcast({"type": "skin_progress", **info})


class SkinApply(BaseModel):
    theme: str = Field(..., description="皮肤主题：ios | sunset | glass")
    apply_device: bool = Field(True, description="是否后台落地到真机（换系统壁纸并重启，真机生效）")


class SkinBatch(BaseModel):
    device_ids: list[int] = Field(default_factory=list)
    theme: str = Field(..., description="皮肤主题：ios | sunset | glass")
    apply_device: bool = Field(True, description="是否后台落地到真机（换系统壁纸并重启，真机生效）")


async def _apply_to_device(device_id: int, theme: str) -> None:
    """后台：把主题真正落到真机（redroid 装启动器/布置桌面/换壁纸+重启；simulator 空操作）。"""

    async def _cb(phase: str) -> None:
        await _report_progress(device_id, theme, phase)

    try:
        async with SessionLocal() as db:
            dev = await db.get(Device, device_id)
            if dev is not None:
                await backend.apply_skin(dev, theme, progress=_cb)
        await _report_progress(device_id, theme, "done")
    except Exception:  # noqa: BLE001  后台任务不影响接口返回
        _log.exception("真机换肤后台任务失败 device=%s", device_id)
        await _report_progress(device_id, theme, "failed")


def _spawn_apply(device_ids: list[int], theme: str) -> None:
    """顺序落地多台（避免同时重启多容器），fire-and-forget；先整批标记排队让前端立即可见。"""

    async def _seq() -> None:
        for did in device_ids:
            await _report_progress(did, theme, "queued")
        for did in device_ids:
            await _apply_to_device(did, theme)

    task = asyncio.create_task(_seq())
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


def _check_theme(theme: str) -> None:
    if theme not in THEMES:
        raise HTTPException(400, f"theme 取值：{list(THEMES.keys())}")


@router.get("/themes")
async def list_themes() -> dict:
    """可选皮肤主题清单（供前端「换肤」下拉）。"""
    return {"themes": THEME_LIST}


@router.get("/applying")
async def skin_applying() -> dict:
    """真机换肤进行中的设备及其阶段（页面加载时补齐状态；后续增量走 WS skin_progress）。

    注意：本路由须声明在 /{device_id} 之前，否则 "applying" 会被当作 device_id 解析。
    """
    return {"applying": list(_progress.values())}


@router.post("/batch", dependencies=[Depends(require_operator)])
async def apply_skin_batch(
    body: SkinBatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """一键换肤（批量）：为多台设备统一切换主题。device_ids 为空则应用到全部设备。

    注意：本路由须声明在 /{device_id} 之前，否则 "batch" 会被当作 device_id 解析。
    """
    _check_theme(body.theme)
    q = select(Device)
    if body.device_ids:
        q = q.where(Device.id.in_(body.device_ids))
    devices = list((await db.execute(q)).scalars().all())
    ids = [d.id for d in devices]
    for d in devices:
        d.skin = body.theme
    await db.commit()
    await record_audit(
        db, user.username, "skin.apply_batch",
        target=f"{len(devices)} 台", detail={"theme": body.theme, "count": len(devices)},
    )
    if body.apply_device and ids:
        _spawn_apply(ids, body.theme)  # 后台顺序落地真机
    return {"ok": True, "count": len(devices), "theme": body.theme, "applying_device": body.apply_device}


@router.get("/{device_id}")
async def device_skin(
    device_id: int,
    screen: str = Query("home"),
    theme: str | None = Query(None, description="覆盖主题；缺省用设备当前皮肤"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if screen not in _SCREENS:
        raise HTTPException(400, f"screen 取值：{sorted(_SCREENS)}")
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    use_theme = theme or getattr(device, "skin", "ios") or "ios"
    _check_theme(use_theme)
    frame = render_frame(
        device.name, device.current_url, device.fingerprint or {}, screen=screen, theme=use_theme
    )
    return {"device_id": device_id, "screen": screen, "theme": use_theme, "frame": frame}


@router.post("/{device_id}", dependencies=[Depends(require_operator)])
async def apply_skin(
    device_id: int,
    body: SkinApply,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """一键换肤（单台）：切换设备皮肤主题。"""
    _check_theme(body.theme)
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    device.skin = body.theme
    await db.commit()
    await record_audit(db, user.username, "skin.apply", target=device.name, detail={"theme": body.theme})
    if body.apply_device:
        _spawn_apply([device_id], body.theme)  # 后台落地真机（换系统壁纸+重启）
    return {"ok": True, "device_id": device_id, "theme": body.theme, "applying_device": body.apply_device}
