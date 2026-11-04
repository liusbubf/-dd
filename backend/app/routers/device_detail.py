"""设备详情聚合（GM-003）：IP / 运行时长 / 已装应用 / 设备标识。

把「设备基础信息 + 一机一码指纹 + 运行时长 + 已装应用数量」聚合到一个接口，
供前端「设备详情聚合页」一次拉齐；已装应用清单单独走 /apps（可能较慢）。

与既有 devices 路由共用 /devices 前缀：FastAPI 允许多个路由挂同一前缀，
只要子路径不同即可。这里使用 /{id}/detail 与 /{id}/apps，不与 devices 冲突。
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..deps import get_device_or_404 as _get_or_404
from ..models import Device, DeviceStatus, User
from .. import services

router = APIRouter(
    prefix="/devices",
    tags=["device-detail"],
    dependencies=[Depends(get_current_user)],
)


def _uptime_seconds(device: Device) -> int | None:
    """运行中的设备返回自创建以来的秒数，否则 None。"""
    if device.status != DeviceStatus.running or device.created_at is None:
        return None
    created = device.created_at
    if created.tzinfo is None:  # SQLite 回读可能是 naive，按 UTC 处理
        created = created.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - created
    return max(0, int(delta.total_seconds()))


@router.get("/{device_id}/detail")
async def device_detail(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    device = await _get_or_404(db, device_id)
    apps = await services.backend.list_apps(device)
    owner = await db.get(User, device.owner_id) if device.owner_id else None
    return {
        "id": device.id,
        "name": device.name,
        "status": device.status.value if hasattr(device.status, "value") else device.status,
        "group_id": device.group_id,
        "owner_id": device.owner_id,
        "owner_name": owner.username if owner else None,
        "width": device.width,
        "height": device.height,
        "dpi": device.dpi,
        "orig_width": device.orig_width,
        "orig_height": device.orig_height,
        "orig_dpi": device.orig_dpi,
        "render_quality": device.render_quality,
        "adb_port": device.adb_port,
        "skin": getattr(device, "skin", "ios"),
        "current_url": device.current_url,
        "created_at": device.created_at,
        "updated_at": device.updated_at,
        "fingerprint": device.fingerprint or {},
        "uptime_seconds": _uptime_seconds(device),
        "installed_app_count": len(apps),
    }


@router.get("/{device_id}/apps")
async def device_apps(device_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    device = await _get_or_404(db, device_id)
    apps = await services.backend.list_apps(device)
    return {"device_id": device.id, "count": len(apps), "apps": apps}
