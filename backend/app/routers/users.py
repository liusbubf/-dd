"""用户管理（RBAC：管理员及以上可管理用户与角色）。

安全加固：
- 密码复杂度校验（最少 6 位 + 字母数字混合）
- 角色创建限制：superadmin 可创建任意角色；admin 仅可创建 viewer/operator
- 自己修改密码端点 /users/me/password（需旧密码校验）
- 用户名格式校验（字母数字下划线，3-32 位）
- 不能删除/降级自己
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import auth
from ..config import settings
from ..database import get_db
from ..models import User
from ..rbac import ROLE_LEVELS, ROLE_LABELS, record_audit, require_role
from ..schemas import BanUserRequest, UnbanUserRequest

router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_role("admin"))],
)

VALID_ROLES = set(ROLE_LEVELS)

# 用户名格式：字母 / 数字 / 下划线 / 中文，3-32 位
_USERNAME_RE = re.compile(r"^[\w一-鿿]{3,32}$")


class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "viewer"


class UserPatch(BaseModel):
    role: str | None = None
    password: str | None = None


class SelfPasswordChange(BaseModel):
    old_password: str
    new_password: str


def _validate_password(pw: str) -> str | None:
    """校验密码复杂度，返回错误信息或 None。"""
    if len(pw) < 6:
        return "密码至少 6 位"
    if not re.search(r"[a-zA-Z]", pw):
        return "密码需包含至少一个字母"
    if not re.search(r"\d", pw):
        return "密码需包含至少一个数字"
    return None


def _validate_username(name: str) -> str | None:
    """校验用户名格式，返回错误信息或 None。"""
    if not _USERNAME_RE.match(name):
        return "用户名需 3-32 位，仅允许字母、数字、下划线、中文"
    return None


def _to_out(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "role_label": ROLE_LABELS.get(u.role, u.role),
        "is_banned": u.is_banned,
        "banned_at": u.banned_at,
        "banned_reason": u.banned_reason,
        "created_at": u.created_at,
    }


async def _count_superadmin(db: AsyncSession) -> int:
    return (
        await db.execute(select(func.count(User.id)).where(User.role == "superadmin"))
    ).scalar_one()


# ---- 自助端点：任何已登录用户可用 ----
#
# 坑：FastAPI 的 dependencies 是「叠加」语义，路由级 dependencies=[] 并不能覆盖
# router 级 dependencies=[Depends(require_role("admin"))]，所以之前挂在上面的
# /me/password 实际仍被 admin 拦截。这里改为独立的 me_router（不带 admin 依赖），
# 在 main.py 里单独 include，路径仍是 /api/users/me 与 /api/users/me/password。
me_router = APIRouter(prefix="/users", tags=["users"])


@me_router.get("/me")
async def read_me(actor: User = Depends(auth.get_current_user)) -> dict:
    """当前登录用户自己的信息（含角色，供前端收敛按钮）。"""
    return _to_out(actor)


@me_router.patch("/me/password")
async def change_self_password(
    body: SelfPasswordChange,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    """当前登录用户修改自己的密码（需验证旧密码）。"""
    if not auth.verify_password(body.old_password, actor.password_hash):
        raise HTTPException(400, "旧密码不正确")

    err = _validate_password(body.new_password)
    if err:
        raise HTTPException(400, err)

    actor.password_hash = auth.hash_password(body.new_password)
    await db.commit()
    await record_audit(db, actor.username, "修改密码", actor.username)
    return {"ok": True}


# ---- 管理员及以上端点 ----


@router.get("")
async def list_users(db: AsyncSession = Depends(get_db)) -> list[dict]:
    users = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return [_to_out(u) for u in users]


@router.post("")
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    username = body.username.strip()
    err = _validate_username(username)
    if err:
        raise HTTPException(400, err)
    if body.role not in VALID_ROLES:
        raise HTTPException(400, "非法角色")
    err = _validate_password(body.password)
    if err:
        raise HTTPException(400, err)

    # 角色创建权限：操作员只能由 superadmin 创建；admin 只能创建 viewer/operator
    actor_level = ROLE_LEVELS.get(actor.role, 0)
    target_level = ROLE_LEVELS.get(body.role, 0)
    if target_level >= actor_level:
        min_role_name = ROLE_LABELS.get(body.role, body.role)
        raise HTTPException(400, f"无权创建「{min_role_name}」角色用户")
    if actor_level < 4 and target_level >= 3:
        raise HTTPException(400, "仅超级管理员可创建管理员及以上角色")

    exists = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(400, "用户名已存在")

    user = User(
        username=username,
        password_hash=auth.hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await record_audit(db, actor.username, "创建用户", user.username, {"role": user.role})
    return _to_out(user)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    body: UserPatch,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")

    changes: dict = {}

    if body.role is not None and body.role != user.role:
        if body.role not in VALID_ROLES:
            raise HTTPException(400, "非法角色")

        # 权限校验：不能提权到 >= 自己的级别
        actor_level = ROLE_LEVELS.get(actor.role, 0)
        target_level = ROLE_LEVELS.get(body.role, 0)
        if target_level >= actor_level:
            raise HTTPException(400, "无权分配该角色")
        # 禁止非 superadmin 把别人设为 admin
        if actor_level < 4 and target_level >= 3:
            raise HTTPException(400, "仅超级管理员可分配管理员及以上角色")

        # 保护：不能把最后一个超级管理员降级
        if user.role == "superadmin" and await _count_superadmin(db) <= 1:
            raise HTTPException(400, "不能降级最后一个超级管理员")

        # 不能修改自己的角色
        if user.id == actor.id:
            raise HTTPException(400, "不能修改自己的角色")

        changes["role"] = {"from": user.role, "to": body.role}
        user.role = body.role

    if body.password:
        err = _validate_password(body.password)
        if err:
            raise HTTPException(400, err)
        user.password_hash = auth.hash_password(body.password)
        changes["password"] = "已重置"

    if not changes:
        return _to_out(user)

    await db.commit()
    await db.refresh(user)
    await record_audit(db, actor.username, "修改用户", user.username, changes)
    return _to_out(user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")

    # 不能删除自己
    if user.id == actor.id:
        raise HTTPException(400, "不能删除自己的账号")

    # 保护：不能删除最后一个超级管理员
    if user.role == "superadmin" and await _count_superadmin(db) <= 1:
        raise HTTPException(400, "不能删除最后一个超级管理员")

    # admin 不能删除同级别或更高级别用户
    actor_level = ROLE_LEVELS.get(actor.role, 0)
    target_level = ROLE_LEVELS.get(user.role, 0)
    if target_level >= actor_level:
        raise HTTPException(400, "无权删除该用户")

    username = user.username
    role = user.role
    await db.delete(user)
    await db.commit()
    await record_audit(db, actor.username, "删除用户", username, {"role": role})
    return {"ok": True}


@router.post("/{user_id}/ban")
async def ban_user(
    user_id: int,
    body: BanUserRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    """封禁用户账号（需管理员权限）。"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")

    # 不能封禁自己
    if user.id == actor.id:
        raise HTTPException(400, "不能封禁自己的账号")

    # admin 不能封禁同级别或更高级别用户
    actor_level = ROLE_LEVELS.get(actor.role, 0)
    target_level = ROLE_LEVELS.get(user.role, 0)
    if target_level >= actor_level:
        raise HTTPException(400, "无权封禁该用户")

    # 保护：不能封禁最后一个超级管理员
    if user.role == "superadmin" and await _count_superadmin(db) <= 1:
        raise HTTPException(400, "不能封禁最后一个超级管理员")

    if user.is_banned:
        raise HTTPException(400, "用户已被封禁")

    user.is_banned = True
    user.banned_at = datetime.now(timezone.utc)
    user.banned_reason = body.reason
    await db.commit()
    await db.refresh(user)
    await record_audit(db, actor.username, "封禁用户", user.username, {"reason": body.reason})
    return {"ok": True}


@router.post("/{user_id}/unban")
async def unban_user(
    user_id: int,
    body: UnbanUserRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(auth.get_current_user),
) -> dict:
    """解封用户账号（需管理员权限）。"""
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")

    # admin 不能解封同级别或更高级别用户
    actor_level = ROLE_LEVELS.get(actor.role, 0)
    target_level = ROLE_LEVELS.get(user.role, 0)
    if target_level >= actor_level:
        raise HTTPException(400, "无权解封该用户")

    if not user.is_banned:
        raise HTTPException(400, "用户未被封禁")

    user.is_banned = False
    user.banned_at = None
    user.banned_reason = None
    await db.commit()
    await db.refresh(user)
    await record_audit(db, actor.username, "解封用户", user.username)
    return {"ok": True}
