"""任务调度（plan §7.3）：即时 / 定时 / 循环任务，批量指令下发。

- 定时（once）：到点触发一次，之后自动停用。
- 循环（interval）：每 interval_seconds 秒触发一次，触发后重排 next_run。
- 立即执行（run-now）：手动触发一次，不影响既有排期。

后端为全异步（AsyncSession + async backend）。调度循环 scheduler_loop 由 main.py 的
lifespan 启动；本模块只暴露它，不自行开跑。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..rbac import require_operator
from ..database import SessionLocal, get_db
from ..models import Device
from ..scheduler_models import ScheduledTask
from .. import services
from ..ws_manager import manager

router = APIRouter(prefix="/tasks", tags=["tasks"], dependencies=[Depends(get_current_user)])

ACTIONS = {"open_url", "tap", "swipe", "key", "text", "install"}


# --------- Pydantic 契约（就地定义，避免改动 schemas.py）---------
class TaskCreate(BaseModel):
    name: str
    action: str
    params: dict = {}
    device_ids: list[int] = []
    schedule_type: str = "once"  # once | interval
    run_at: datetime | None = None
    interval_seconds: int | None = None
    enabled: bool = True


class TaskUpdate(BaseModel):
    name: str | None = None
    action: str | None = None
    params: dict | None = None
    device_ids: list[int] | None = None
    schedule_type: str | None = None
    run_at: datetime | None = None
    interval_seconds: int | None = None
    enabled: bool | None = None


class TaskOut(BaseModel):
    id: int
    name: str
    action: str
    params: dict
    device_ids: list[int]
    schedule_type: str
    run_at: datetime | None
    interval_seconds: int | None
    enabled: bool
    last_run: datetime | None
    next_run: datetime | None
    last_result: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------- 时间/排期辅助 ---------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """SQLite 读回可能是 naive；统一按 UTC 补齐时区，便于比较。"""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _compute_next_run(task: ScheduledTask) -> datetime | None:
    if not task.enabled:
        return None
    if task.schedule_type == "interval" and task.interval_seconds:
        return _now() + timedelta(seconds=int(task.interval_seconds))
    if task.schedule_type == "once":
        return _as_aware(task.run_at)
    return None


# --------- 动作下发（对齐 batch.py 的坐标折算与广播）---------
def _scale(device: Device, x: int, y: int, ref_w: int = 1080, ref_h: int = 1920) -> tuple[int, int]:
    return int(x * device.width / ref_w), int(y * device.height / ref_h)


async def _dispatch(device: Device, action: str, p: dict) -> None:
    if action == "open_url":
        await services.backend.open_url(device, p["url"])
        await services.broadcast_device(device)
    elif action == "tap":
        x, y = _scale(device, int(p["x"]), int(p["y"]))
        await services.backend.tap(device, x, y)
    elif action == "swipe":
        x1, y1 = _scale(device, int(p["x1"]), int(p["y1"]))
        x2, y2 = _scale(device, int(p["x2"]), int(p["y2"]))
        await services.backend.swipe(device, x1, y1, x2, y2, int(p.get("duration_ms", 300)))
    elif action == "text":
        await services.backend.input_text(device, p["text"])
    elif action == "key":
        await services.backend.key(device, p["key"])
    elif action == "install":
        await services.backend.install(device, p["apk_url"])
    else:
        raise ValueError(f"未知动作: {action}")


async def execute_task(db: AsyncSession, task: ScheduledTask) -> dict:
    """在任务目标设备上下发一次动作，记录 last_run / last_result 并提交。

    只负责「执行 + 记结果」；是否重排 next_run / 停用由调用方决定
    （调度循环负责重排，run-now 不动排期）。
    """
    ids = list(task.device_ids or [])
    devices: list[Device] = []
    if ids:
        devices = list((await db.execute(select(Device).where(Device.id.in_(ids)))).scalars().all())

    details: list[dict] = []
    for d in devices:
        try:
            await _dispatch(d, task.action, dict(task.params or {}))
            details.append({"device_id": d.id, "name": d.name, "ok": True})
        except Exception as e:  # noqa: BLE001  单机失败不影响整体
            details.append({"device_id": d.id, "name": d.name, "ok": False, "error": str(e)})

    ok = sum(1 for x in details if x["ok"])
    result = {
        "ran_at": _now().isoformat(),
        "total": len(devices),
        "ok": ok,
        "failed": len(devices) - ok,
        "details": details,
    }
    task.last_run = _now()
    task.last_result = result
    await db.commit()
    await db.refresh(task)
    await manager.broadcast(
        {"type": "task_done", "task_id": task.id, "name": task.name, "ok": ok, "total": len(devices)}
    )
    return result


# --------- 调度循环（main.py lifespan 里启动）---------
async def scheduler_loop() -> None:
    """每 ~5s 扫一遍：启用且 next_run <= now 的任务执行；interval 重排，once 停用。

    每轮开独立 Session；逐任务 try/except，循环永不因单任务异常而崩溃。
    """
    while True:
        try:
            async with SessionLocal() as db:
                now = _now()
                rows = list(
                    (
                        await db.execute(
                            select(ScheduledTask).where(
                                ScheduledTask.enabled.is_(True),
                                ScheduledTask.next_run.isnot(None),
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for task in rows:
                    nr = _as_aware(task.next_run)
                    if nr is None or nr > now:
                        continue
                    try:
                        await execute_task(db, task)
                        if task.schedule_type == "interval" and task.interval_seconds:
                            task.next_run = _now() + timedelta(seconds=int(task.interval_seconds))
                        else:  # once：执行后自动停用
                            task.enabled = False
                            task.next_run = None
                        await db.commit()
                    except Exception:  # noqa: BLE001  单任务失败：回滚并跳过
                        try:
                            await db.rollback()
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001  整轮异常（如 DB 短暂不可用）不得中断循环
            pass
        await asyncio.sleep(5)


# --------- REST 端点 ---------
@router.get("", response_model=list[TaskOut])
async def list_tasks(db: AsyncSession = Depends(get_db)) -> list[ScheduledTask]:
    return list((await db.execute(select(ScheduledTask).order_by(ScheduledTask.id.desc()))).scalars().all())


@router.post("", response_model=TaskOut, dependencies=[Depends(require_operator)])
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)) -> ScheduledTask:
    if body.action not in ACTIONS:
        raise HTTPException(400, f"不支持的动作: {body.action}")
    if body.schedule_type not in ("once", "interval"):
        raise HTTPException(400, "调度类型必须为 once 或 interval")

    if body.schedule_type == "interval":
        if not body.interval_seconds or body.interval_seconds <= 0:
            raise HTTPException(400, "循环任务需要正的间隔秒数")
        next_run = _now() + timedelta(seconds=int(body.interval_seconds))
    else:  # once
        if body.run_at is None:
            raise HTTPException(400, "定时任务需要设置运行时间")
        next_run = _as_aware(body.run_at)

    task = ScheduledTask(
        name=body.name,
        action=body.action,
        params=body.params or {},
        device_ids=body.device_ids or [],
        schedule_type=body.schedule_type,
        run_at=_as_aware(body.run_at),
        interval_seconds=body.interval_seconds,
        enabled=body.enabled,
        next_run=next_run if body.enabled else None,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, db: AsyncSession = Depends(get_db)) -> ScheduledTask:
    task = await db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


@router.patch("/{task_id}", response_model=TaskOut, dependencies=[Depends(require_operator)])
async def update_task(task_id: int, body: TaskUpdate, db: AsyncSession = Depends(get_db)) -> ScheduledTask:
    task = await db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")

    data = body.model_dump(exclude_unset=True)
    if "action" in data and data["action"] not in ACTIONS:
        raise HTTPException(400, f"不支持的动作: {data['action']}")

    for k, v in data.items():
        setattr(task, k, _as_aware(v) if k == "run_at" else v)

    # 排期相关字段变化或重新启用时，重算 next_run
    if any(k in data for k in ("schedule_type", "run_at", "interval_seconds", "enabled")):
        task.next_run = _compute_next_run(task)

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/{task_id}", dependencies=[Depends(require_operator)])
async def delete_task(task_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    task = await db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    await db.delete(task)
    await db.commit()
    return {"ok": True}


@router.post("/{task_id}/run-now", response_model=TaskOut, dependencies=[Depends(require_operator)])
async def run_now(task_id: int, db: AsyncSession = Depends(get_db)) -> ScheduledTask:
    task = await db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    await execute_task(db, task)  # 立即执行，不改动排期
    return task
