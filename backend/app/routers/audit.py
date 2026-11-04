"""操作审计日志查询与导出（RBAC：管理员及以上可查看）。

优化内容：
- 分页（page / size），不再硬编码 limit(200)
- 按操作人 / 操作类型 / 目标 / 时间范围筛选
- 关键词搜索（匹配操作人、操作类型、目标、详情）
- CSV 导出（UTF-8 BOM，Excel 不乱码）
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit_models import AuditLog
from ..database import get_db
from ..rbac import require_role

router = APIRouter(
    prefix="/audit",
    tags=["audit"],
    dependencies=[Depends(require_role("admin"))],
)


@router.get("")
async def list_audit(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(50, ge=1, le=500, description="每页条数"),
    username: Optional[str] = Query(None, description="按操作人筛选"),
    action: Optional[str] = Query(None, description="按操作类型筛选"),
    target: Optional[str] = Query(None, description="按目标对象筛选"),
    q: Optional[str] = Query(None, description="关键词搜索（匹配操作人/操作类型/目标/详情）"),
    start: Optional[datetime] = Query(None, alias="start_date", description="起始时间（含）"),
    end: Optional[datetime] = Query(None, alias="end_date", description="结束时间（含）"),
) -> dict:
    """分页查询审计日志，支持多条件筛选与关键词搜索。"""
    stmt = select(AuditLog)

    if username:
        stmt = stmt.where(AuditLog.username == username)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target:
        stmt = stmt.where(AuditLog.target == target)
    if start:
        stmt = stmt.where(AuditLog.ts >= start)
    if end:
        stmt = stmt.where(AuditLog.ts <= end)
    if q:
        like = f"%{q}%"
        from sqlalchemy import or_
        stmt = stmt.where(or_(
            AuditLog.username.ilike(like),
            AuditLog.action.ilike(like),
            AuditLog.target.ilike(like),
            AuditLog.detail.cast(str).ilike(like),
        ))

    # 总数
    from sqlalchemy import func
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # 分页
    stmt = stmt.order_by(AuditLog.id.desc())
    offset = (page - 1) * size
    rows = (await db.execute(stmt.offset(offset).limit(size))).scalars().all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": r.id,
                "username": r.username,
                "action": r.action,
                "target": r.target,
                "detail": r.detail,
                "ts": r.ts,
            }
            for r in rows
        ],
    }


@router.get("/actions")
async def list_actions(db: AsyncSession = Depends(get_db)) -> dict:
    """返回所有已记录的 action 类型（供筛选下拉框）。"""
    from sqlalchemy import func
    rows = (
        await db.execute(
            select(AuditLog.action, func.count(AuditLog.id))
            .group_by(AuditLog.action)
            .order_by(func.count(AuditLog.id).desc())
        )
    ).all()
    return {"actions": [{"action": a, "count": c} for a, c in rows]}


@router.get("/users")
async def list_audited_users(db: AsyncSession = Depends(get_db)) -> dict:
    """返回所有出现在审计日志中的用户名（供筛选下拉框）。"""
    from sqlalchemy import func
    rows = (
        await db.execute(
            select(AuditLog.username, func.count(AuditLog.id))
            .group_by(AuditLog.username)
            .order_by(func.count(AuditLog.id).desc())
        )
    ).all()
    return {"users": [{"username": u, "count": c} for u, c in rows]}


@router.get("/export.csv")
async def export_csv(
    db: AsyncSession = Depends(get_db),
    start: Optional[datetime] = Query(None, alias="start_date", description="起始时间（含）"),
    end: Optional[datetime] = Query(None, alias="end_date", description="结束时间（含）"),
) -> Response:
    """导出审计日志为 CSV（UTF-8 BOM，Excel 不乱码），最多 10000 条。"""
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(10000)
    if start:
        stmt = stmt.where(AuditLog.ts >= start)
    if end:
        stmt = stmt.where(AuditLog.ts <= end)

    rows = (await db.execute(stmt)).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "操作人", "操作类型", "目标", "详情", "时间"])
    for r in rows:
        writer.writerow([
            r.id, r.username, r.action, r.target or "",
            str(r.detail) if r.detail else "", r.ts.isoformat() if r.ts else "",
        ])

    content = "﻿" + buf.getvalue()  # UTF-8 BOM
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=audit_logs.csv"},
    )
