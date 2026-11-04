"""到期自动回收：扫描 expires_at 已到的设备 → 停机、释放 IP、写审计。

默认关闭（CLOUD_EXPIRE_SWEEP_ENABLED=False），避免误伤演示环境；
打开后由 main.py 的后台循环按 CLOUD_EXPIRE_SWEEP_INTERVAL 秒执行。

回收语义：
- 运行中的设备调用后端 stop，失败则本轮跳过（保留 expires_at，下轮重试）；
- 无论是否运行，都解绑 IP；IP 没有其它设备占用时置回 available；
- 清空 expires_at，避免同一设备被反复扫描；
- 每次回收写一条 device.expire_reclaim 审计。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import services
from .models import Device, DeviceStatus, IpResource
from .rbac import record_audit

_log = logging.getLogger("app.expiry")


async def sweep_expired(db: AsyncSession, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rows = list(
        (
            await db.execute(
                select(Device)
                .where(Device.expires_at.is_not(None))
                .where(Device.expires_at <= now)
                .order_by(Device.expires_at)
            )
        )
        .scalars()
        .all()
    )

    reclaimed: list[dict] = []
    failed: list[dict] = []
    for device in rows:
        detail = {"expires_at": device.expires_at.isoformat() if device.expires_at else None}
        if device.status == DeviceStatus.running:
            try:
                await services.stop_device(db, device)
            except Exception as exc:
                # 停机失败不改任何状态，下一轮继续重试
                _log.warning("expire.reclaim stop failed device=%s err=%s", device.id, exc)
                failed.append({"device_id": device.id, "error": str(exc)[:200]})
                continue

        ip_id = device.ip_id
        device.ip_id = None
        if ip_id is not None:
            record = await db.get(IpResource, ip_id)
            if record is not None:
                still_bound = list(
                    (await db.execute(select(Device).where(Device.ip_id == ip_id))).scalars().all()
                )
                if not still_bound:
                    record.status = "available"
                detail["released_ip"] = record.ip
        device.expires_at = None
        await db.commit()
        await record_audit(
            db,
            "system",
            "device.expire_reclaim",
            target=device.name,
            detail={"device_id": device.id, **detail},
        )
        reclaimed.append({"device_id": device.id, "name": device.name, **detail})

    _log.info("expire.sweep reclaimed=%s failed=%s", len(reclaimed), len(failed))
    return {"count": len(reclaimed), "reclaimed": reclaimed, "failed": failed}


async def expire_sweep_loop(interval: int) -> None:
    """后台循环：配置关闭时只 sleep，不查库。"""
    import asyncio

    from .database import SessionLocal

    while True:
        await asyncio.sleep(max(10, int(interval)))
        from .config import settings

        if not settings.expire_sweep_enabled:
            continue
        try:
            async with SessionLocal() as db:
                await sweep_expired(db)
        except Exception:
            _log.exception("expire.sweep 执行失败")
