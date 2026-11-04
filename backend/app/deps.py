"""路由层公共依赖 / 小工具。

只做低风险收敛：把各 router 里重复的「按 id 取设备，不存在报 404」抽到这里。
不改变任何行为（异常类型、状态码、提示文案与原实现一致）。
"""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Device


async def get_device_or_404(db: AsyncSession, device_id: int) -> Device:
    """按主键取设备，不存在抛 404「设备不存在」；被封禁抛 403。"""
    device = await db.get(Device, device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    if device.is_banned:
        reason = device.banned_reason or "违反平台服务条款"
        raise HTTPException(403, f"设备已被封禁：{reason}")
    return device
