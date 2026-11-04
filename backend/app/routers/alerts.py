"""告警监控（计划 §7.5.2 离线 / 资源 / 异常告警）。

设计要点：
- 不落库、不起后台任务、不新增模型。
- 每次请求按「当前设备状态」实时计算告警。
- 机型 / 出口 IP / Android ID 存放在 Device.fingerprint（JSON 列），
  无法在 SQL 层聚合，设备行一次取回后在 Python 内遍历生成告警。
- GET /alerts/current   — 实时告警列表，可选分页（page / size）。
- GET /alerts/rules     — 静态规则描述。

告警对象结构：{level, type, device_id, device_name, message, ts}
    level ∈ {critical, warning, info}
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..fingerprint_utils import android_id_of, exit_ip_of
from ..models import Device, DeviceStatus

router = APIRouter(prefix="/alerts", tags=["告警"], dependencies=[Depends(get_current_user)])

_LEVEL_ORDER = {"critical": 0, "warning": 1, "info": 2}

_RULES = [
    {
        "type": "device_error",
        "name": "设备异常",
        "level": "critical",
        "description": "设备处于 error 状态（后端拉起 / 运行失败），需人工介入。",
    },
    {
        "type": "device_stopped",
        "name": "设备已停止",
        "level": "info",
        "description": "设备处于 stopped 状态，当前不在线，可按需启动。",
    },
    {
        "type": "no_exit_ip",
        "name": "无独立出口 IP",
        "level": "warning",
        "description": "运行中的设备缺少独立出口 IP，可能与「一机一码」独立身份要求不符。",
    },
    {
        "type": "ip_collision",
        "name": "出口 IP 重复",
        "level": "warning",
        "description": "多台设备共用同一出口 IP（指纹碰撞），存在关联封号风险。",
    },
    {
        "type": "no_android_id",
        "name": "缺失设备标识",
        "level": "warning",
        "description": "运行中的设备指纹缺少 Android ID，设备标识不完整。",
    },
]


def _ts_of(device: Device) -> datetime:
    return device.updated_at or datetime.now(timezone.utc)


@router.get("/current")
async def current_alerts(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(100, ge=1, le=1000, description="每页条数"),
    level: Optional[str] = Query(None, description="按级别筛选：critical / warning / info"),
) -> dict:
    """按当前设备状态实时计算告警（不落库），支持分页与级别筛选。"""
    devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())

    alerts: list[dict] = []
    ip_to_devices: dict[str, list[Device]] = defaultdict(list)

    for d in devices:
        ts = _ts_of(d)
        ip = exit_ip_of(d)
        aid = android_id_of(d)

        # 规则：设备异常 → critical
        if d.status == DeviceStatus.error:
            alerts.append({
                "level": "critical", "type": "device_error",
                "device_id": d.id, "device_name": d.name,
                "message": "设备异常：后端拉起或运行失败，请检查编排后端", "ts": ts,
            })

        # 规则：设备已停止 → info
        if d.status == DeviceStatus.stopped:
            alerts.append({
                "level": "info", "type": "device_stopped",
                "device_id": d.id, "device_name": d.name,
                "message": "设备已停止，当前不在线", "ts": ts,
            })

        # 规则：运行中但无独立出口 IP → warning
        if d.status == DeviceStatus.running and not ip:
            alerts.append({
                "level": "warning", "type": "no_exit_ip",
                "device_id": d.id, "device_name": d.name,
                "message": "无独立出口 IP：运行中设备缺少独立出口，独立身份不完整", "ts": ts,
            })

        # 规则：运行中但缺失 Android ID → warning（修复：仅对 running 设备检此规则）
        if d.status == DeviceStatus.running and not aid:
            alerts.append({
                "level": "warning", "type": "no_android_id",
                "device_id": d.id, "device_name": d.name,
                "message": "缺失设备标识：运行中设备的指纹中未找到 Android ID", "ts": ts,
            })

        if ip:
            ip_to_devices[ip].append(d)

    # 规则：出口 IP 重复（指纹碰撞）→ warning
    for ip, group in ip_to_devices.items():
        if len(group) < 2:
            continue
        other_names = "、".join(g.name for g in group if g is not group[0])
        for d in group:
            alerts.append({
                "level": "warning", "type": "ip_collision",
                "device_id": d.id, "device_name": d.name,
                "message": f"出口 IP {ip} 与其他 {len(group) - 1} 台设备重复（{other_names}）",
                "ts": _ts_of(d),
            })

    # 排序：严重 → 警告 → 提示，同级按设备 ID
    alerts.sort(key=lambda a: (_LEVEL_ORDER.get(a["level"], 9), a["device_id"]))

    # 级别统计（基于全量告警，不随分页变化）
    by_level = {"critical": 0, "warning": 0, "info": 0}
    for a in alerts:
        by_level[a["level"]] = by_level.get(a["level"], 0) + 1

    # 级别筛选
    if level:
        alerts = [a for a in alerts if a["level"] == level]

    # 分页
    total = len(alerts)
    start = (page - 1) * size
    page_alerts = alerts[start:start + size]

    return {
        "generated_at": datetime.now(timezone.utc),
        "total": total,
        "page": page,
        "size": size,
        "by_level": by_level,
        "alerts": page_alerts,
    }


@router.get("/rules")
async def alert_rules() -> dict:
    """静态告警规则描述，供前端展示。"""
    return {"rules": _RULES}
