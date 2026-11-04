"""数据看板（监控大盘）：总览统计 + 轻量设备列表。

对齐前端「数据看板」页：
- GET /metrics/overview  -> 设备/分组/在线连接的聚合指标（含机型、分组分布），带 5s 内存缓存。
- GET /metrics/devices   -> 每台设备的精简监控行（含机型、出口 IP、当前页面）。

统计口径：机型 / 出口 IP 存放在 Device.fingerprint（JSON 列），无法在 SQL 层聚合，
因此把设备行一次取回后在 Python 内单次遍历完成计数。
"""
from __future__ import annotations

import time
from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..fingerprint_utils import exit_ip_of, model_of
from ..models import Device, DeviceStatus, Group
from ..ws_manager import manager

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(get_current_user)])

# 简单的内存缓存：5 秒内重复请求直接返回已有结果
_cache: dict = {"data": None, "ts": 0.0}
_CACHE_TTL = 5.0


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db)) -> dict:
    """看板总览：KPI + 状态分布 + 机型/分组分布 + 最近设备（5 秒缓存）。"""
    now = time.time()
    if _cache["data"] is not None and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["data"]

    devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())
    groups = list((await db.execute(select(Group).order_by(Group.id))).scalars().all())

    # 空数据友好返回
    if not devices:
        empty = {
            "total_devices": 0,
            "running": 0, "stopped": 0, "error": 0, "creating": 0,
            "total_groups": len(groups),
            "ws_clients": manager.count,
            "unique_exit_ips": 0,
            "by_group": [{"group_id": g.id, "name": g.name, "count": 0} for g in groups],
            "model_distribution": [],
            "recent_devices": [],
            "cached": False,
        }
        _cache["data"] = empty
        _cache["ts"] = now
        return empty

    status_counter: Counter[str] = Counter()
    model_counter: Counter[str] = Counter()
    group_counter: Counter[int | None] = Counter()
    exit_ips: set[str] = set()
    for d in devices:
        status_counter[d.status.value] += 1
        model_counter[model_of(d)] += 1
        group_counter[d.group_id] += 1
        ip = exit_ip_of(d)
        if ip:
            exit_ips.add(ip)

    by_group = [
        {"group_id": g.id, "name": g.name, "count": group_counter.get(g.id, 0)}
        for g in groups
    ]
    ungrouped = group_counter.get(None, 0)
    if ungrouped:
        by_group.append({"group_id": None, "name": "未分组", "count": ungrouped})

    model_distribution = [
        {"model": m, "count": c}
        for m, c in sorted(model_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    recent = sorted(devices, key=lambda d: d.created_at or "", reverse=True)[:8]
    recent_devices = [
        {"id": d.id, "name": d.name, "status": d.status.value, "created_at": d.created_at}
        for d in recent
    ]

    result = {
        "total_devices": len(devices),
        "running": status_counter.get(DeviceStatus.running.value, 0),
        "stopped": status_counter.get(DeviceStatus.stopped.value, 0),
        "error": status_counter.get(DeviceStatus.error.value, 0),
        "creating": status_counter.get(DeviceStatus.creating.value, 0),
        "total_groups": len(groups),
        "ws_clients": manager.count,
        "unique_exit_ips": len(exit_ips),
        "by_group": by_group,
        "model_distribution": model_distribution,
        "recent_devices": recent_devices,
        "cached": False,
    }
    _cache["data"] = result
    _cache["ts"] = now
    return result


@router.get("/devices")
async def device_rows(db: AsyncSession = Depends(get_db)) -> list[dict]:
    """每台设备的精简监控行。"""
    devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())
    return [
        {
            "id": d.id,
            "name": d.name,
            "status": d.status.value,
            "group_id": d.group_id,
            "model": model_of(d),
            "exit_ip": exit_ip_of(d),
            "current_url": d.current_url,
            "created_at": d.created_at,
        }
        for d in devices
    ]
