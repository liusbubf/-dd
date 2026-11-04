"""首次启动播种：管理员账号 + 预置用户 + 默认分组。

用户来源（按优先级）：
1. settings.admin_username / admin_password（固定超管）
2. settings.seed_users（团队共享预置用户，JSON 列表）

只有用户名不存在时才创建，已存在的跳过——支持重复启动与增量添加。
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from .auth import hash_password
from .config import settings
from .database import SessionLocal
from .models import Group, User

_log = logging.getLogger("app.seed")


async def seed() -> None:
    async with SessionLocal() as db:
        # ---- 管理员 ----
        exists = (
            await db.execute(select(User).where(User.username == settings.admin_username))
        ).scalar_one_or_none()
        if exists is None:
            # 弱口令只允许在演示模式出现：debug=False 时 enforce_security() 已在启动阶段拒绝。
            if settings.admin_password == "admin123":
                _log.warning(
                    "正在用演示默认口令创建管理员 %s（仅限本地演示）；"
                    "生产请设置 CLOUD_ADMIN_PASSWORD，或用 tools/seed_rbac.py 初始化正式账号",
                    settings.admin_username,
                )
            db.add(User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role="superadmin",
            ))

        # ---- 预置团队用户 ----
        for u in settings.seed_users:
            name = (u.get("username") or "").strip()
            if not name:
                continue
            already = (
                await db.execute(select(User).where(User.username == name))
            ).scalar_one_or_none()
            if already is not None:
                continue
            role = u.get("role", "viewer")
            if role not in ("superadmin", "admin", "operator", "viewer"):
                role = "viewer"
            db.add(User(
                username=name,
                password_hash=hash_password(u.get("password", "")),
                role=role,
            ))

        # ---- 默认分组 ----
        has_group = (await db.execute(select(Group.id))).first()
        if not has_group:
            db.add(Group(name="默认分组"))

        await db.commit()
