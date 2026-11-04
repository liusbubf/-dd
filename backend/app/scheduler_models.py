"""任务调度数据模型：定时 / 循环任务（plan §7.3 批量指令下发）。

单独成模块，避免改动 models.py。因为 routers/tasks.py 会在 main.py 加载时被 import，
而 tasks.py 又 import 本模块，于是 ScheduledTask 会在 init_db() 的 create_all 之前
注册到共享的 Base.metadata 上 —— 建表随之自动完成，无需额外迁移。
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ScheduledTask(Base):
    """一条调度任务：把某个批量动作在选中设备上按计划下发。

    schedule_type:
      - once     ：定时单次，到 run_at 触发，触发后自动停用。
      - interval ：循环任务，每 interval_seconds 秒触发一次，触发后重排 next_run。
    """

    __tablename__ = "scheduled_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)

    # 动作：open_url / tap / swipe / key / text / install
    action: Mapped[str] = mapped_column(String(32))
    # 动作参数（随 action 不同）：{"url": ...} / {"x":..,"y":..} / {"text":..} ...
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    # 目标设备 id 列表
    device_ids: Mapped[list] = mapped_column(JSON, default=list)

    # 调度类型：once | interval
    schedule_type: Mapped[str] = mapped_column(String(16), default="once")
    run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # 最近一次执行结果：{ran_at,total,ok,failed,details:[{device_id,name,ok,error?}]}
    last_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
