"""单机实时操控（demo 验收 §6：点开任一台，实时操控浏览器）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..deps import get_device_or_404 as _get
from ..models import User
from ..rbac import record_audit, require_operator
from ..schemas import (
    DisplayCmd,
    InputMethodCmd,
    InstallCmd,
    KeyCmd,
    OpenUrlCmd,
    RenderQualityCmd,
    ScrcpyCmd,
    SwipeCmd,
    TapCmd,
    TextCmd,
)
from .. import services

router = APIRouter(
    prefix="/devices/{device_id}/control",
    tags=["control"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/open_url", dependencies=[Depends(require_operator)])
async def open_url(device_id: int, cmd: OpenUrlCmd, db: AsyncSession = Depends(get_db)) -> dict:
    device = await _get(db, device_id)
    await services.backend.open_url(device, cmd.url)
    await db.commit()
    await services.broadcast_device(device)
    return {"ok": True, "url": cmd.url}


@router.post("/tap", dependencies=[Depends(require_operator)])
async def tap(device_id: int, cmd: TapCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.tap(await _get(db, device_id), cmd.x, cmd.y)
    return {"ok": True}


@router.post("/swipe", dependencies=[Depends(require_operator)])
async def swipe(device_id: int, cmd: SwipeCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.swipe(await _get(db, device_id), cmd.x1, cmd.y1, cmd.x2, cmd.y2, cmd.duration_ms)
    return {"ok": True}


@router.post("/text", dependencies=[Depends(require_operator)])
async def text(device_id: int, cmd: TextCmd, db: AsyncSession = Depends(get_db)) -> dict:
    import logging
    log = logging.getLogger("control.text")
    log.info("device %d text: %s", device_id, repr(cmd.text))
    await services.backend.input_text(await _get(db, device_id), cmd.text, append=cmd.append)
    return {"ok": True}


@router.post("/key", dependencies=[Depends(require_operator)])
async def key(device_id: int, cmd: KeyCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.key(await _get(db, device_id), cmd.key)
    return {"ok": True}


@router.post("/install", dependencies=[Depends(require_operator)])
async def install(device_id: int, cmd: InstallCmd, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.install(await _get(db, device_id), cmd.apk_url)
    return {"ok": True}


@router.post("/display", dependencies=[Depends(require_operator)])
async def set_display(
    device_id: int,
    cmd: DisplayCmd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """运行时切换分辨率/DPI（V5）：失败自动回滚并返回 502，写审计。

    redroid 会重建容器（约 10–30s，期间设备不可操作）；physical 走
    `wm size`/`wm density` 即时生效；simulator 只改内存态。
    """
    device = await _get(db, device_id)
    before = {"width": device.width, "height": device.height, "dpi": device.dpi}
    try:
        device = await services.set_device_display(db, device, cmd.width, cmd.height, cmd.dpi)
    except services.DisplayChangeError as e:
        raise HTTPException(502, str(e)) from e
    await record_audit(
        db,
        user.username,
        "device.display.change",
        target=f"device:{device.id}",
        detail={"from": before, "to": {"width": device.width, "height": device.height, "dpi": device.dpi}},
    )
    return {
        "ok": True,
        "width": device.width,
        "height": device.height,
        "dpi": device.dpi,
        "backend": settings.device_backend,
        "restart_required": settings.device_backend == "redroid",
        "note": "部分后端需要重建容器/重启才能生效（约 10–30s）",
    }


@router.post("/display/reset", dependencies=[Depends(require_operator)])
async def reset_display(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """恢复设备创建时的原始分辨率/密度（V5 兜底入口）。"""
    device = await _get(db, device_id)
    before = {"width": device.width, "height": device.height, "dpi": device.dpi}
    try:
        device = await services.reset_device_display(db, device)
    except services.DisplayChangeError as e:
        raise HTTPException(502, str(e)) from e
    await record_audit(
        db,
        user.username,
        "device.display.reset",
        target=f"device:{device.id}",
        detail={"from": before, "to": {"width": device.width, "height": device.height, "dpi": device.dpi}},
    )
    return {
        "ok": True,
        "width": device.width,
        "height": device.height,
        "dpi": device.dpi,
        "orig_width": device.orig_width,
        "orig_height": device.orig_height,
        "orig_dpi": device.orig_dpi,
    }


@router.post("/render-quality", dependencies=[Depends(require_operator)])
async def set_render_quality(
    device_id: int,
    cmd: RenderQualityCmd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """设置投屏渲染质量（low/medium/high），下次准备 scrcpy 时生效。

    这不是「旧版/新版渲染器」切换：本项目没有该分支，按质量调整
    maxFps / bitrate，避免做空开关。
    """
    device = await _get(db, device_id)
    before = device.render_quality
    device = await services.set_device_render_quality(db, device, cmd.quality)
    await record_audit(
        db,
        user.username,
        "device.render_quality.change",
        target=f"device:{device.id}",
        detail={"from": before, "to": device.render_quality},
    )
    return {"ok": True, "quality": device.render_quality}


@router.post("/ime", dependencies=[Depends(require_operator)])
async def manage_input_method(
    device_id: int, cmd: InputMethodCmd, db: AsyncSession = Depends(get_db)
) -> dict:
    """输入法管理：list / get / set / enable / disable。"""
    device = await _get(db, device_id)
    action = cmd.action
    if action == "list":
        methods = await services.backend.list_input_methods(device)
        return {"ok": True, "methods": methods}
    elif action == "get":
        active_id = await services.backend.get_active_input_method(device)
        return {"ok": True, "active_ime": active_id}
    elif action == "set":
        if not cmd.ime_id:
            raise HTTPException(400, "set 需要 ime_id")
        await services.backend.set_input_method(device, cmd.ime_id)
        return {"ok": True, "action": "set", "ime_id": cmd.ime_id}
    elif action == "enable":
        if not cmd.ime_id:
            raise HTTPException(400, "enable 需要 ime_id")
        await services.backend.enable_input_method(device, cmd.ime_id)
        return {"ok": True, "action": "enable", "ime_id": cmd.ime_id}
    elif action == "disable":
        if not cmd.ime_id:
            raise HTTPException(400, "disable 需要 ime_id")
        await services.backend.disable_input_method(device, cmd.ime_id)
        return {"ok": True, "action": "disable", "ime_id": cmd.ime_id}
    else:
        raise HTTPException(400, f"未知 action: {action}")


@router.post("/scrcpy", dependencies=[Depends(require_operator)])
async def scrcpy_prepare(
    device_id: int, cmd: ScrcpyCmd, db: AsyncSession = Depends(get_db)
) -> dict:
    """准备 scrcpy 投屏参数。

    - action="prepare"（默认）：返回 { ready, ws_scrcpy_base, udid, iframe_url,
      proxy_ws_url, width, height }；iframe_url 可直接嵌入弹窗，ws-scrcpy
      的 Broadway 播放器自带实时触屏、键盘、拖拽滑动等交互。
    - action="health"：仅检查 ws-scrcpy 服务是否可达 + 设备是否在线，
      返回 { ready, reachable, device_ok, hint }。
    """
    device = await _get(db, device_id)
    action = (cmd.action or "prepare").lower()

    if action == "health":
        # 轻量检测：
        # - reachable：后端容器尝试 TCP 连接 ws-scrcpy（可能因容器网络隔离失败，但不代表用户浏览器不可达）
        # - device_ok：设备本身是否在线、ADB 可用
        # ready 策略：只要 device_ok 就视为可尝试（浏览器端直接连 host:8100，
        # 后端容器连不到 ws-scrcpy 不影响前端实际投屏体验）。
        from ..config import settings
        from urllib.parse import urlparse
        import socket

        base = settings.ws_scrcpy_base or f"http://{settings.redroid_host}:8100"
        reachable = False
        hint = ""
        try:
            parsed = urlparse(base)
            host = parsed.hostname or settings.redroid_host
            port = parsed.port or 8100
            with socket.create_connection((host, port), timeout=2.5):
                reachable = True
        except OSError as e:
            hint = f"后端容器无法直连 {base}（{e}），不影响浏览器端投屏"
        device_ok = False
        try:
            await services.backend._ensure_alive(device)
            device_ok = True
        except Exception as e:  # noqa: BLE001
            if not hint:
                hint = f"设备不可达：{e}"
        ready = device_ok  # 只要设备在线，就允许前端弹窗尝试
        return {"ok": True, "ready": ready, "reachable": reachable,
                "device_ok": device_ok, "hint": hint, "ws_scrcpy_base": base}

    # prepare
    info = await services.backend.prepare_scrcpy(device)
    return {"ok": True, **info}
