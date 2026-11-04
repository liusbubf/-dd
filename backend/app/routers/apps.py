"""应用管理（GM-101/102/103/106，demo 验收 §7.2）：卸载 / 启动 / 强停 / 清数据 + 批量。

单机应用动作挂在 /devices/{id}/apps/{action} 子路径下（与既有 devices / device_detail
路由共用 /devices 前缀，子路径不同故不冲突）；批量动作挂在 /apps 前缀下。

编排后端方法均已存在（redroid 真机 adb、simulator 内存 mock）：
  list_apps / uninstall_app / launch_app / stop_app / clear_app / install。
本路由只做「取设备 → 调编排 → 汇总/广播」，不改设备行，无需 db.commit。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..rbac import require_operator
from ..database import get_db
from ..deps import get_device_or_404 as _get_or_404
from ..models import Device
from .. import services
from ..ws_manager import manager

router = APIRouter(tags=["应用"], dependencies=[Depends(get_current_user)])


# --------- 请求模型（局部定义，不改 schemas.py） ---------
class AppAction(BaseModel):
    package: str


class BatchAppAction(BaseModel):
    device_ids: list[int]
    package: str


class BatchAppInstall(BaseModel):
    device_ids: list[int]
    apk_url: str


async def _fetch(db: AsyncSession, ids: list[int]) -> list[Device]:
    return list((await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all())


async def _run_all(db: AsyncSession, ids: list[int], action_name: str, fn) -> dict:
    """对目标设备并发执行 fn(device)，实时广播进度，汇总结果（镜像 batch.py）。"""
    devices = await _fetch(db, ids)
    details: list[dict] = []
    done = 0

    async def _one(device: Device) -> None:
        nonlocal done
        try:
            await fn(device)
            details.append({"device_id": device.id, "name": device.name, "ok": True})
        except Exception as e:  # noqa: BLE001  单机失败不影响其它设备
            details.append({"device_id": device.id, "name": device.name, "ok": False, "error": str(e)})
        finally:
            done += 1
            await manager.broadcast(
                {"type": "batch_progress", "action": action_name, "done": done, "total": len(devices)}
            )

    await asyncio.gather(*[_one(d) for d in devices])
    ok = sum(1 for d in details if d["ok"])
    return {"total": len(devices), "ok": ok, "failed": len(devices) - ok, "details": details}


# --------- 单机应用动作 ---------
@router.post("/devices/{device_id}/apps/uninstall", dependencies=[Depends(require_operator)])
async def uninstall(device_id: int, body: AppAction, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.uninstall_app(await _get_or_404(db, device_id), body.package)
    return {"ok": True}


@router.post("/devices/{device_id}/apps/launch", dependencies=[Depends(require_operator)])
async def launch(device_id: int, body: AppAction, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.launch_app(await _get_or_404(db, device_id), body.package)
    return {"ok": True}


@router.post("/devices/{device_id}/apps/stop", dependencies=[Depends(require_operator)])
async def stop(device_id: int, body: AppAction, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.stop_app(await _get_or_404(db, device_id), body.package)
    return {"ok": True}


@router.post("/devices/{device_id}/apps/clear", dependencies=[Depends(require_operator)])
async def clear(device_id: int, body: AppAction, db: AsyncSession = Depends(get_db)) -> dict:
    await services.backend.clear_app(await _get_or_404(db, device_id), body.package)
    return {"ok": True}


# --------- 批量应用动作 ---------
@router.post("/apps/batch/uninstall", dependencies=[Depends(require_operator)])
async def batch_uninstall(body: BatchAppAction, db: AsyncSession = Depends(get_db)) -> dict:
    async def fn(d: Device) -> None:
        await services.backend.uninstall_app(d, body.package)

    return await _run_all(db, body.device_ids, "app_uninstall", fn)


@router.post("/apps/batch/launch", dependencies=[Depends(require_operator)])
async def batch_launch(body: BatchAppAction, db: AsyncSession = Depends(get_db)) -> dict:
    async def fn(d: Device) -> None:
        await services.backend.launch_app(d, body.package)

    return await _run_all(db, body.device_ids, "app_launch", fn)


@router.post("/apps/batch/stop", dependencies=[Depends(require_operator)])
async def batch_stop(body: BatchAppAction, db: AsyncSession = Depends(get_db)) -> dict:
    async def fn(d: Device) -> None:
        await services.backend.stop_app(d, body.package)

    return await _run_all(db, body.device_ids, "app_stop", fn)


@router.post("/apps/batch/clear", dependencies=[Depends(require_operator)])
async def batch_clear(body: BatchAppAction, db: AsyncSession = Depends(get_db)) -> dict:
    async def fn(d: Device) -> None:
        await services.backend.clear_app(d, body.package)

    return await _run_all(db, body.device_ids, "app_clear", fn)


@router.post("/apps/batch/install", dependencies=[Depends(require_operator)])
async def batch_install(body: BatchAppInstall, db: AsyncSession = Depends(get_db)) -> dict:
    async def fn(d: Device) -> None:
        await services.backend.install(d, body.apk_url)

    return await _run_all(db, body.device_ids, "app_install", fn)
