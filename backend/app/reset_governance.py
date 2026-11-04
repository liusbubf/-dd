"""测试环境重置治理（V3.1）。

只做平台侧的防误操作与防滥用：
- 设备归属校验由路由层负责（复用 `_can_manage_device`）；
- 同一设备两次重置之间的冷却；
- 同一用户每日重置配额；
- 成功重置写 `device_reset_events` 流水，配合 `record_audit` 留痕。

本模块不生成、不修改、不推断任何设备指纹，也不参与第三方应用的风控判断。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Device, DeviceResetEvent, User

# 计入冷却与配额的“重置类”动作。接口动作名保持稳定，便于审计检索。
RESET_ACTIONS = (
    "device.renew",
    "device.renew_batch",
    "device.reset.restore_snapshot",
    "device.reset.wipe_data",
    "device.snapshot.restore",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """SQLite 读出的时间可能不带 tzinfo，统一按 UTC 解释。"""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


async def _last_reset_at(db: AsyncSession, device_id: int) -> datetime | None:
    value = await db.scalar(
        select(func.max(DeviceResetEvent.created_at)).where(
            DeviceResetEvent.device_id == device_id,
            DeviceResetEvent.action.in_(RESET_ACTIONS),
        )
    )
    return _aware(value)


async def _used_today(db: AsyncSession, user_id: int) -> int:
    now = _now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    value = await db.scalar(
        select(func.count())
        .select_from(DeviceResetEvent)
        .where(
            DeviceResetEvent.user_id == user_id,
            DeviceResetEvent.created_at >= day_start,
            DeviceResetEvent.action.in_(RESET_ACTIONS),
        )
    )
    return int(value or 0)


async def ensure_reset_allowed(
    db: AsyncSession,
    devices: list[Device],
    user: User,
) -> None:
    """在破坏性重置前检查冷却与每日配额；不通过时返回 429。"""
    if not settings.reset_governance_enabled or not devices:
        return

    now = _now()
    cooldown = max(0, settings.reset_cooldown_seconds)
    if cooldown:
        for device in devices:
            last = await _last_reset_at(db, device.id)
            if last is None:
                continue
            next_at = last + timedelta(seconds=cooldown)
            if now < next_at:
                retry_after = max(1, int((next_at - now).total_seconds()) + 1)
                raise HTTPException(
                    429,
                    f"设备「{device.name}」重置冷却中，请 {retry_after} 秒后再试",
                    headers={"Retry-After": str(retry_after)},
                )

    quota = max(0, settings.reset_daily_quota)
    if quota:
        used = await _used_today(db, user.id)
        if used + len(devices) > quota:
            raise HTTPException(
                429,
                f"今日测试环境重置配额不足：已用 {used}/{quota}，本次需要 {len(devices)} 次",
            )


async def record_reset_events(
    db: AsyncSession,
    devices: list[Device],
    user: User,
    action: str,
    detail: dict | None = None,
) -> None:
    """成功（或已入队）后写重置流水；失败的重置不计数。"""
    if not settings.reset_governance_enabled or not devices:
        return
    for device in devices:
        db.add(
            DeviceResetEvent(
                device_id=device.id,
                user_id=user.id,
                username=user.username,
                action=action,
                detail=detail or {},
            )
        )
    await db.commit()


async def policy_snapshot(db: AsyncSession, device: Device, user: User) -> dict:
    """给前端展示的当前策略与剩余额度。"""
    enabled = settings.reset_governance_enabled
    cooldown = max(0, settings.reset_cooldown_seconds)
    quota = max(0, settings.reset_daily_quota)
    last = await _last_reset_at(db, device.id)
    used = await _used_today(db, user.id) if enabled else 0
    next_allowed_at = None
    if last is not None and cooldown:
        next_allowed_at = (last + timedelta(seconds=cooldown)).isoformat()
    return {
        "enabled": enabled,
        "cooldown_seconds": cooldown,
        "next_allowed_at": next_allowed_at,
        "daily_quota": quota,
        "used_today": used,
        "remaining_today": max(0, quota - used) if quota else None,
    }
