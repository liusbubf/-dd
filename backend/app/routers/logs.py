"""设备日志（§7.5.3 日志查看）：拉取单台设备的 logcat。

与既有 devices / device_detail 路由共用 /devices 前缀：FastAPI 允许多个路由挂同一前缀，
只要子路径不同即可。这里使用 /{id}/logcat，不与 devices（/{id}、/{id}/start...）
或 device_detail（/{id}/detail、/{id}/apps）冲突。

日志由编排后端提供：services.backend.list_logcat(device, lines)
  - redroid  ：容器内执行 logcat -d -t N，取最近 N 行。
  - simulator：返回一段模拟日志，便于无真机环境演示。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..deps import get_device_or_404 as _get_or_404
from .. import services

router = APIRouter(prefix="/devices", tags=["logs"], dependencies=[Depends(get_current_user)])

# 单次拉取行数上限，防止一次拉太多拖慢后端 / 前端渲染。
_MAX_LINES = 1000


@router.get("/{device_id}/logcat")
async def device_logcat(
    device_id: int,
    lines: int = Query(200, ge=1, le=_MAX_LINES, description="拉取最近 N 行日志"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = await _get_or_404(db, device_id)
    log_lines = await services.backend.list_logcat(device, lines)
    return {"device_id": device.id, "lines": log_lines}
