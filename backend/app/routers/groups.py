"""设备分组（demo 验收：设备管理 + 分组）。

支持多级（嵌套）分组：≤3 级、分组树、设备移动。
GM-002 / 7.1.2。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..rbac import require_operator
from ..database import get_db
from ..models import Device, Group
from ..schemas import GroupCreate, GroupOut

router = APIRouter(prefix="/groups", tags=["groups"], dependencies=[Depends(get_current_user)])

MAX_DEPTH = 3


# --------- 请求模型（局部，不改动全局 schemas.py） ---------
class GroupPatch(BaseModel):
    name: str | None = None
    parent_id: int | None = None


class MoveDevices(BaseModel):
    device_ids: list[int] = []


# --------- 工具函数 ---------
async def _to_out(db: AsyncSession, group: Group) -> GroupOut:
    count = (
        await db.execute(select(func.count(Device.id)).where(Device.group_id == group.id))
    ).scalar_one()
    return GroupOut(id=group.id, name=group.name, parent_id=group.parent_id, device_count=count)


async def _load_maps(db: AsyncSession) -> tuple[dict[int, Group], dict[int | None, list[Group]]]:
    """一次性载入全部分组，返回 (id->Group, parent_id->[Group])。"""
    groups = (await db.execute(select(Group).order_by(Group.id))).scalars().all()
    by_id: dict[int, Group] = {g.id: g for g in groups}
    children: dict[int | None, list[Group]] = {}
    for g in groups:
        children.setdefault(g.parent_id, []).append(g)
    return by_id, children


def _depth(gid: int, by_id: dict[int, Group]) -> int:
    """节点层级：根节点为 1，防环。"""
    depth = 1
    seen: set[int] = set()
    cur = by_id.get(gid)
    while cur is not None and cur.parent_id is not None:
        if cur.id in seen:  # 环，终止
            break
        seen.add(cur.id)
        parent = by_id.get(cur.parent_id)
        if parent is None:
            break
        depth += 1
        cur = parent
    return depth


def _subtree_height(gid: int, children: dict[int | None, list[Group]]) -> int:
    """以 gid 为根的子树高度：仅自身为 1，防环。"""
    def walk(node_id: int, seen: set[int]) -> int:
        if node_id in seen:
            return 1
        seen = seen | {node_id}
        kids = children.get(node_id, [])
        if not kids:
            return 1
        return 1 + max(walk(k.id, seen) for k in kids)

    return walk(gid, set())


def _is_descendant(candidate: int, ancestor: int, children: dict[int | None, list[Group]]) -> bool:
    """candidate 是否在 ancestor 的子树内（含 ancestor 自身）。"""
    stack = [ancestor]
    seen: set[int] = set()
    while stack:
        nid = stack.pop()
        if nid == candidate:
            return True
        if nid in seen:
            continue
        seen.add(nid)
        stack.extend(k.id for k in children.get(nid, []))
    return False


# --------- 现有接口（保持返回契约不变，Devices.vue 依赖 device_count） ---------
@router.get("", response_model=list[GroupOut])
async def list_groups(db: AsyncSession = Depends(get_db)) -> list[GroupOut]:
    groups = (await db.execute(select(Group).order_by(Group.id))).scalars().all()
    rows = (
        await db.execute(select(Device.group_id, func.count(Device.id)).group_by(Device.group_id))
    ).all()
    counts = {gid: n for gid, n in rows}
    return [
        GroupOut(id=g.id, name=g.name, parent_id=g.parent_id, device_count=counts.get(g.id, 0))
        for g in groups
    ]


@router.post("", response_model=GroupOut, dependencies=[Depends(require_operator)])
async def create_group(body: GroupCreate, db: AsyncSession = Depends(get_db)) -> GroupOut:
    if body.parent_id is not None:
        by_id, _ = await _load_maps(db)
        parent = by_id.get(body.parent_id)
        if parent is None:
            raise HTTPException(404, "父分组不存在")
        if _depth(parent.id, by_id) >= MAX_DEPTH:
            raise HTTPException(400, f"分组层级最多 {MAX_DEPTH} 级")
    group = Group(name=body.name, parent_id=body.parent_id)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return await _to_out(db, group)


@router.delete("/{group_id}", dependencies=[Depends(require_operator)])
async def delete_group(group_id: int, db: AsyncSession = Depends(get_db)) -> dict:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "分组不存在")
    # 解绑该组下设备
    for d in (await db.execute(select(Device).where(Device.group_id == group_id))).scalars():
        d.group_id = None
    # 子分组上提为顶级，避免悬挂外键
    for c in (await db.execute(select(Group).where(Group.parent_id == group_id))).scalars():
        c.parent_id = None
    await db.delete(group)
    await db.commit()
    return {"ok": True}


# --------- 新增接口：分组树 / 改名·移动分组 / 移动设备 ---------
@router.get("/tree")
async def group_tree(db: AsyncSession = Depends(get_db)) -> dict:
    """嵌套分组树。

    返回 {roots:[{id,name,parent_id,device_count,total_count,children:[...]}],
          ungrouped_count:n, max_depth:3}
    device_count = 直接成员；total_count = 含全部后代成员。
    """
    _, children = await _load_maps(db)
    rows = (
        await db.execute(select(Device.group_id, func.count(Device.id)).group_by(Device.group_id))
    ).all()
    counts: dict[int | None, int] = {gid: n for gid, n in rows}

    def build(group: Group, seen: set[int]) -> dict:
        if group.id in seen:  # 防环
            direct = counts.get(group.id, 0)
            return {
                "id": group.id,
                "name": group.name,
                "parent_id": group.parent_id,
                "device_count": direct,
                "total_count": direct,
                "children": [],
            }
        seen = seen | {group.id}
        kids = [build(c, seen) for c in children.get(group.id, [])]
        direct = counts.get(group.id, 0)
        total = direct + sum(k["total_count"] for k in kids)
        return {
            "id": group.id,
            "name": group.name,
            "parent_id": group.parent_id,
            "device_count": direct,
            "total_count": total,
            "children": kids,
        }

    roots = [build(g, set()) for g in children.get(None, [])]
    return {
        "roots": roots,
        "ungrouped_count": counts.get(None, 0),
        "max_depth": MAX_DEPTH,
    }


@router.patch("/{group_id}", response_model=GroupOut, dependencies=[Depends(require_operator)])
async def update_group(
    group_id: int, body: GroupPatch, db: AsyncSession = Depends(get_db)
) -> GroupOut:
    """重命名 / 重新指定父分组（防环 + 层级 ≤ 3）。"""
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(404, "分组不存在")

    fields = body.model_fields_set

    if "parent_id" in fields:
        by_id, children = await _load_maps(db)
        new_parent = body.parent_id
        height = _subtree_height(group_id, children)  # 该子树高度（含自身）
        if new_parent is None:
            deepest = height  # 变为顶级：最深后代层级 = height
        else:
            if new_parent == group_id:
                raise HTTPException(400, "不能将分组挂到自身下")
            parent = by_id.get(new_parent)
            if parent is None:
                raise HTTPException(404, "父分组不存在")
            if _is_descendant(new_parent, group_id, children):
                raise HTTPException(400, "不能挂到自己的子分组下（会形成环）")
            deepest = _depth(new_parent, by_id) + height  # 父层级 + 子树高度
        if deepest > MAX_DEPTH:
            raise HTTPException(400, f"分组层级最多 {MAX_DEPTH} 级")
        group.parent_id = new_parent

    if "name" in fields and body.name is not None:
        group.name = body.name

    await db.commit()
    await db.refresh(group)
    return await _to_out(db, group)


@router.post("/{group_id}/move-devices", dependencies=[Depends(require_operator)])
async def move_devices(
    group_id: int, body: MoveDevices, db: AsyncSession = Depends(get_db)
) -> dict:
    """把指定设备移动到分组 group_id；group_id==0 表示取消分组。"""
    target: int | None
    if group_id == 0:
        target = None
    else:
        group = await db.get(Group, group_id)
        if group is None:
            raise HTTPException(404, "分组不存在")
        target = group_id

    if not body.device_ids:
        return {"moved": 0}

    devices = (
        await db.execute(select(Device).where(Device.id.in_(body.device_ids)))
    ).scalars().all()
    for d in devices:
        d.group_id = target
    await db.commit()
    return {"moved": len(devices)}
