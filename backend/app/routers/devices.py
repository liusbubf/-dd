"""设备生命周期（D4 编排 API）：创建 / 批量建 N 台 / 启停 / 删除 / 列表 / 详情 / 截图。"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..deps import get_device_or_404 as _get_or_404
from ..models import Device, DeviceShare, DeviceSnapshot, DeviceStatus, User
from ..orchestrator.base import DeviceCommandError
from ..rbac import record_audit, require_operator
from ..schemas import (
    BanDeviceRequest,
    BatchRenew,
    DeviceAdopt,
    DeviceBatchCreate,
    DeviceCreate,
    DeviceOut,
    DeviceShareCreate,
    DeviceShareOut,
    DeviceUpdate,
    RenewCmd,
    ResetConfirm,
    ShareCandidateOut,
    SnapshotCreate,
    SnapshotOut,
    UnbanDeviceRequest,
)
from .. import reset_governance, services
from ..preview_hub import hub

_log = logging.getLogger("app.devices")

router = APIRouter(prefix="/devices", tags=["devices"], dependencies=[Depends(get_current_user)])


class BatchDeleteRequest(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=500)


def _is_admin_role(role: str) -> bool:
    return role in ("admin", "superadmin")


def _can_manage_device(device: Device, user: User) -> bool:
    """共享管理权限：设备归属者或 admin+。

    复用现有角色判定，不新造权限体系；历史平台设备 owner_id 为空，仅 admin+ 可管理。
    """
    return _is_admin_role(user.role) or (
        device.owner_id is not None and device.owner_id == user.id
    )


def _ensure_can_manage_device(device: Device, user: User) -> None:
    """破坏性/重置类操作的归属校验：设备归属者或 admin+。"""
    if not _can_manage_device(device, user):
        raise HTTPException(403, "仅设备归属者或管理员可执行该操作")


# --- fresh 截图限流（按 用户 + 设备）-----------------------------------------
# viewer 高频轮询 ?fresh=true 会绕过 preview_hub 帧缓存，直接打爆后端截图。
# 规则：10 秒窗口内最多 2 次，超限 429 + Retry-After。
_FRESH_LIMIT = 2
_FRESH_WINDOW_S = 10.0
_fresh_hits: dict[tuple[int, int], list[float]] = {}
_fresh_lock = asyncio.Lock()


async def _check_fresh_rate(user_id: int, device_id: int) -> None:
    now = time.monotonic()
    key = (user_id, device_id)
    async with _fresh_lock:
        hits = [t for t in _fresh_hits.get(key, []) if now - t < _FRESH_WINDOW_S]
        if len(hits) >= _FRESH_LIMIT:
            retry_after = max(1, int(_FRESH_WINDOW_S - (now - hits[0])) + 1)
            _fresh_hits[key] = hits
            raise HTTPException(
                429,
                f"刷新截图过于频繁，请 {retry_after} 秒后再试",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        _fresh_hits[key] = hits
        if len(_fresh_hits) > 2048:
            # 防止长时间运行后字典无限增长：清掉窗口外的旧键
            for k in [k for k, v in _fresh_hits.items() if not any(now - t < _FRESH_WINDOW_S for t in v)]:
                _fresh_hits.pop(k, None)


@router.get("", response_model=list[DeviceOut])
async def list_devices(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    group_id: int | None = None,
    status: DeviceStatus | None = None,
    q: str | None = Query(None, max_length=128, description="按名称模糊搜索"),
) -> list[Device]:
    stmt = select(Device).order_by(Device.id)
    if not _is_admin_role(user.role):
        # 同租户可见性：本人设备 + 共享给本人的设备 + 历史平台设备（owner 为空）。
        # 共享只授予 viewer 级可见性，不提升写权限。
        shared_ids = select(DeviceShare.device_id).where(
            DeviceShare.user_id == user.id,
            DeviceShare.revoked_at.is_(None),
        )
        stmt = stmt.where(
            or_(
                Device.owner_id == user.id,
                Device.owner_id.is_(None),
                Device.id.in_(shared_ids),
            )
        )
    if group_id is not None:
        stmt = stmt.where(Device.group_id == group_id)
    if status is not None:
        stmt = stmt.where(Device.status == status)
    if q:
        stmt = stmt.where(Device.name.ilike(f"%{q}%"))
    return list((await db.execute(stmt)).scalars().all())


@router.get("/fingerprint-policies")
async def list_fingerprint_policies() -> dict:
    """返回合法商业指纹策略清单，便于前端展示受控设备模板与地域隔离规则。"""
    from ..fingerprint import _FINGERPRINT_POLICIES

    return {
        "policies": [
            {
                "mode": mode,
                "label": cfg["label"],
                "description": cfg["description"],
                "allow_model_randomization": cfg.get("allow_model_randomization", False),
                "allow_proxy_binding": cfg.get("allow_proxy_binding", False),
                "allow_timezone_variant": cfg.get("allow_timezone_variant", False),
            }
            for mode, cfg in sorted(_FINGERPRINT_POLICIES.items())
        ]
    }


@router.post("", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def create_device(
    body: DeviceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    if settings.device_backend == "physical":
        raise HTTPException(400, "实体机模式不支持建机，请使用「接入实体机」")
    # 生成默认名
    if not body.name:
        count = len((await db.execute(select(Device.id))).all())
        body.name = f"云手机-{count + 1:03d}"
    device = await services.create_device(
        db,
        name=body.name,
        group_id=body.group_id,
        width=body.width,
        height=body.height,
        dpi=body.dpi,
        target_url=body.target_url,
        proxy=body.proxy,
        fingerprint_mode=body.fingerprint_mode,
        region=body.region,
        owner_id=user.id,
    )
    _log.info(
        "device.create id=%s name=%s backend=%s by=%s",
        device.id,
        device.name,
        settings.device_backend,
        user.username,
    )
    return device


@router.post("/batch", response_model=list[DeviceOut], dependencies=[Depends(require_operator)])
async def batch_create(
    body: DeviceBatchCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Device]:
    """一键创建/启动 N 台云手机（demo 验收 §2 建机）。"""
    if settings.device_backend == "physical":
        raise HTTPException(400, "实体机模式不支持批量建机，请使用「接入实体机」")
    base = len((await db.execute(select(Device.id))).all())
    devices: list[Device] = []
    # 并发拉起，提高 demo 建机体验
    async def _one(i: int) -> Device:
        return await services.create_device(
            db,
            name=f"{body.name_prefix}-{base + i:03d}",
            group_id=body.group_id,
            width=body.width,
            height=body.height,
            dpi=body.dpi,
            target_url=body.target_url,
            auto_start=body.auto_start,
            fingerprint_mode=body.fingerprint_mode,
            region=body.region,
            owner_id=user.id,
        )

    # SQLite 单连接不宜高并发写，顺序建；Postgres 可改并发
    for i in range(1, body.count + 1):
        devices.append(await _one(i))
    return devices


@router.post("/batch-delete", dependencies=[Depends(require_operator)])
async def batch_delete(
    body: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """批量删除设备"""
    _log.info("device.batch_delete count=%s by=%s", len(body.device_ids), user.username)
    deleted = 0
    for did in body.device_ids:
        device = await db.get(Device, did)
        if device:
            await services.destroy_device(db, device)
            deleted += 1
    return {"ok": True, "count": deleted}


@router.get("/renewing")
async def renewing() -> dict:
    """正在进行中的一键新机（页面刷新后补齐进度；增量走 WS renew_progress）。"""
    return {"renewing": services.renewing_snapshot()}


@router.get("/expiring")
async def expiring_devices(
    within_hours: int = Query(24, ge=1, le=720, description="到期提醒窗口（小时）"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """即将到期的设备清单（按 expires_at 升序），供前端顶部提醒与运营看板使用。"""
    now = datetime.now(timezone.utc)
    deadline = now + timedelta(hours=within_hours)
    stmt = (
        select(Device)
        .where(Device.expires_at.is_not(None))
        .where(Device.expires_at <= deadline)
        .order_by(Device.expires_at)
    )
    rows = list((await db.execute(stmt)).scalars().all())
    items = [DeviceOut.model_validate(d).model_dump(mode="json") for d in rows]
    return {"within_hours": within_hours, "count": len(items), "devices": items}


@router.post("/check", dependencies=[Depends(require_operator)])
async def check_devices(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """巡检全部设备的控制通道，并把掉线/恢复同步到设备状态。"""
    result = await services.check_devices(db)
    await record_audit(db, user.username, "device.check", target="all", detail=result)
    return {"ok": True, **result}


@router.post("/{device_id}/claim", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def claim_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    device = await _get_or_404(db, device_id)
    try:
        device = await services.claim_device(db, device, user.username, user.role)
    except services.DeviceClaimed as e:
        raise HTTPException(409, str(e)) from e
    await record_audit(
        db, user.username, "device.claim", target=f"device:{device.id}",
        detail={"claimed_by": user.username},
    )
    return device


@router.post("/{device_id}/release", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def release_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    device = await _get_or_404(db, device_id)
    try:
        device = await services.release_device(db, device, user.username, user.role)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    await record_audit(
        db, user.username, "device.release", target=f"device:{device.id}",
        detail={"claimed_by": device.claimed_by},
    )
    return device


@router.get("/discover")
async def discover_devices(db: AsyncSession = Depends(get_db)) -> dict:
    """扫描已连接的实体机（仅 physical 后端真正执行 adb 扫描）。"""
    if settings.device_backend != "physical":
        return {"backend": settings.device_backend, "devices": []}

    from ..orchestrator.physical import list_adb_devices

    try:
        devices = await list_adb_devices()
    except DeviceCommandError as e:
        return {"backend": "physical", "devices": [], "error": str(e)}

    adopted = set(
        (await db.execute(select(Device.backend_ref).where(Device.backend_ref.is_not(None))))
        .scalars().all()
    )
    for d in devices:
        d["adopted"] = d["serial"] in adopted
    return {"backend": "physical", "devices": devices}


@router.post("/adopt", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def adopt_device(
    body: DeviceAdopt,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    """把一台已连接的真实手机纳入设备池（记录设备原值，不篡改硬件标识）。"""
    if settings.device_backend != "physical":
        raise HTTPException(400, "当前不是实体机模式，请在配置中设置 CLOUD_DEVICE_BACKEND=physical")
    try:
        device = await services.adopt_device(
            db, serial=body.serial, name=body.name, group_id=body.group_id,
            owner_id=user.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except DeviceCommandError as e:
        raise HTTPException(502, str(e)) from e
    await record_audit(
        db, user.username, "device.adopt",
        target=f"device:{device.id}",
        detail={
            "serial": body.serial,
            "model": (device.fingerprint or {}).get("device", {}).get("model"),
        },
    )
    return device


@router.post("/batch-renew", dependencies=[Depends(require_operator)])
async def batch_renew(
    body: BatchRenew,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """批量测试环境重置：立即返回，后台按 CLOUD_RENEW_CONCURRENCY 限流执行。"""
    if settings.device_backend == "physical" and body.mode == "hard":
        raise HTTPException(400, "实体机不支持更换设备身份，请使用 QA 重置（clear_data）")
    devices = list(
        (await db.execute(select(Device).where(Device.id.in_(body.device_ids))))
        .scalars().all()
    )
    existing = {d.id for d in devices}
    missing = [i for i in body.device_ids if i not in existing]
    for device in devices:
        _ensure_can_manage_device(device, user)

    busy = {item["device_id"] for item in services.renewing_snapshot()}
    eligible = [d for d in devices if d.id not in busy]
    await reset_governance.ensure_reset_allowed(db, eligible, user)
    queued = await services.batch_renew(
        [d.id for d in eligible],
        mode=body.mode,
        rotate_proxy=body.rotate_proxy,
        keep_url=body.keep_url,
    )
    queued_ids = set(queued["device_ids"])
    detail = {
        "mode": body.mode,
        "rotate_proxy": body.rotate_proxy,
        "keep_url": body.keep_url,
        "device_ids": queued["device_ids"],
        "skipped": queued["skipped"],
        "missing": missing,
    }
    await reset_governance.record_reset_events(
        db,
        [d for d in eligible if d.id in queued_ids],
        user,
        "device.renew_batch",
        detail,
    )
    await record_audit(
        db, user.username, "device.renew_batch",
        target=f"{queued['queued']} 台",
        detail=detail,
    )
    return {"ok": True, **queued, "missing": missing}


@router.post("/{device_id}/renew", dependencies=[Depends(require_operator)])
async def renew_device(
    device_id: int,
    body: RenewCmd,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """测试环境重置（单台）：清数据并（可选）重建测试环境，后台执行。"""
    if settings.device_backend == "physical" and body.mode == "hard":
        raise HTTPException(400, "实体机不支持更换设备身份，请使用 QA 重置（clear_data）")
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    await reset_governance.ensure_reset_allowed(db, [device], user)
    queued = await services.batch_renew(
        [device.id],
        mode=body.mode,
        rotate_proxy=body.rotate_proxy,
        keep_url=body.keep_url,
    )
    if not queued["queued"]:
        raise HTTPException(409, "该设备正在重置中，请稍后再试")
    detail = {
        "mode": body.mode,
        "rotate_proxy": body.rotate_proxy,
        "keep_url": body.keep_url,
    }
    await reset_governance.record_reset_events(db, [device], user, "device.renew", detail)
    await record_audit(
        db, user.username, "device.renew",
        target=f"device:{device.id}",
        detail=detail,
    )
    return {"ok": True, **queued}


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    return await _get_or_404(db, device_id)


@router.patch("/{device_id}", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def update_device(device_id: int, body: DeviceUpdate, db: AsyncSession = Depends(get_db)) -> Device:
    device = await _get_or_404(db, device_id)
    # 必须看「有没有传这个字段」：group_id=null 是「移出分组」，不能和「没改分组」混成一谈。
    fields = body.model_fields_set
    if "name" in fields and body.name and body.name.strip():
        device.name = body.name.strip()
    if "group_id" in fields:
        device.group_id = body.group_id
    if "expires_at" in fields:
        device.expires_at = body.expires_at
    await db.commit()
    await db.refresh(device)
    await services.broadcast_device(device)
    return device


@router.delete("/{device_id}", dependencies=[Depends(require_operator)])
async def delete_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    await services.destroy_device(db, device)
    _log.info("device.delete id=%s name=%s by=%s", device_id, device.name, user.username)
    return {"ok": True}


@router.get("/{device_id}/snapshots", response_model=list[SnapshotOut])
async def list_snapshots(
    device_id: int, db: AsyncSession = Depends(get_db)
) -> list[DeviceSnapshot]:
    device = await _get_or_404(db, device_id)
    return await services.list_snapshots(db, device.id)


@router.post("/{device_id}/snapshots", response_model=SnapshotOut, dependencies=[Depends(require_operator)])
async def create_snapshot(
    device_id: int,
    body: SnapshotCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeviceSnapshot:
    """创建快照：保存设备数据（应用/账号/文件），用于回滚与黄金模板。"""
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    try:
        snap = await services.create_snapshot(db, device, body.name)
    except services.RenewInProgress as e:
        raise HTTPException(409, str(e)) from e
    except services.SnapshotFailed as e:
        raise HTTPException(502, str(e)) from e
    await record_audit(
        db, user.username, "device.snapshot.create",
        target=f"device:{device.id}",
        detail={"snapshot_id": snap.id, "name": snap.name, "size_bytes": snap.size_bytes},
    )
    return snap


@router.post("/{device_id}/snapshots/{snapshot_id}/restore", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def restore_snapshot(
    device_id: int,
    snapshot_id: int,
    body: ResetConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    """用快照覆盖设备当前数据并重启（设备身份不随快照回滚）。"""
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    _check_confirm_name(device, body.confirm_name)
    snap = await db.get(DeviceSnapshot, snapshot_id)
    if snap is None or snap.device_id != device.id:
        raise HTTPException(404, "快照不存在")
    await reset_governance.ensure_reset_allowed(db, [device], user)
    try:
        device = await services.restore_snapshot(db, device, snap)
    except services.RenewInProgress as e:
        raise HTTPException(409, str(e)) from e
    except services.SnapshotFailed as e:
        raise HTTPException(502, str(e)) from e
    detail = {"snapshot_id": snap.id, "name": snap.name}
    await reset_governance.record_reset_events(
        db, [device], user, "device.snapshot.restore", detail
    )
    await record_audit(
        db, user.username, "device.snapshot.restore",
        target=f"device:{device.id}",
        detail=detail,
    )
    return device


def _check_confirm_name(device: Device, confirm_name: str) -> None:
    """破坏性重置的二次确认：前端输入设备名，后端同样校验，避免绕过前端。"""
    if (confirm_name or "").strip() != device.name:
        raise HTTPException(400, "设备名确认不匹配：请输入完整的设备名称再执行")


@router.get("/{device_id}/reset-policy", dependencies=[Depends(require_operator)])
async def get_reset_policy(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """当前用户在该设备上的重置策略：冷却、每日已用/剩余额度。"""
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    return await reset_governance.policy_snapshot(db, device, user)


@router.post(
    "/{device_id}/reset/restore-snapshot",
    response_model=DeviceOut,
    dependencies=[Depends(require_operator)],
)
async def reset_restore_snapshot(
    device_id: int,
    body: ResetConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    """恢复到快照：取该设备最近一次 ready 快照并覆盖当前数据。

    没有可用快照时明确返回 409，不做「假成功」；实体机等不支持快照的后端
    会把后端错误如实返回 502。设备记录与绑定关系不变，仅数据回滚。
    """
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    _check_confirm_name(device, body.confirm_name)
    snap = await services.latest_ready_snapshot(db, device.id)
    if snap is None:
        raise HTTPException(
            409,
            "当前设备没有可用快照，无法恢复；请先创建快照后再试",
        )
    await reset_governance.ensure_reset_allowed(db, [device], user)
    try:
        device = await services.restore_snapshot(db, device, snap)
    except services.RenewInProgress as e:
        raise HTTPException(409, str(e)) from e
    except services.SnapshotFailed as e:
        raise HTTPException(502, str(e)) from e
    except Exception as e:  # noqa: BLE001  恢复失败必须如实返回
        _log.exception("device.reset.restore_snapshot 失败 device=%s", device.id)
        raise HTTPException(502, f"恢复到快照失败：{e}") from e
    detail = {"snapshot_id": snap.id, "name": snap.name, "mode": "restore_latest"}
    await reset_governance.record_reset_events(
        db, [device], user, "device.reset.restore_snapshot", detail
    )
    await record_audit(
        db, user.username, "device.reset.restore_snapshot",
        target=f"device:{device.id}",
        detail=detail,
    )
    return device


@router.post(
    "/{device_id}/reset/wipe-data",
    response_model=DeviceOut,
    dependencies=[Depends(require_operator)],
)
async def reset_wipe_data(
    device_id: int,
    body: ResetConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Device:
    """清空数据（保留设备）：真实擦除设备内数据并重启，同步返回结果。

    复用各后端 clear_data 擦除路径（redroid `_wipe_data` / physical 等效实现 /
    simulator 重置内存态），保留设备记录、分组、断占与 IP 绑定；失败返回 502，
    不返回成功。
    """
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    _check_confirm_name(device, body.confirm_name)
    await reset_governance.ensure_reset_allowed(db, [device], user)
    try:
        device = await services.wipe_device_data(db, device)
    except services.RenewInProgress as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:  # noqa: BLE001  清空失败必须如实报错
        _log.exception("device.reset.wipe_data 失败 device=%s", device.id)
        raise HTTPException(502, f"清空数据失败：{e}") from e
    detail = {"mode": "clear_data", "keep_device": True}
    await reset_governance.record_reset_events(
        db, [device], user, "device.reset.wipe_data", detail
    )
    await record_audit(
        db, user.username, "device.reset.wipe_data",
        target=f"device:{device.id}",
        detail=detail,
    )
    return device


@router.delete("/{device_id}/snapshots/{snapshot_id}", dependencies=[Depends(require_operator)])
async def delete_snapshot(
    device_id: int,
    snapshot_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)
    snap = await db.get(DeviceSnapshot, snapshot_id)
    if snap is None or snap.device_id != device.id:
        raise HTTPException(404, "快照不存在")
    snap_name = snap.name
    await services.delete_snapshot(db, device, snap)
    await record_audit(
        db, user.username, "device.snapshot.delete",
        target=f"device:{device.id}",
        detail={"snapshot_id": snapshot_id, "name": snap_name},
    )
    return {"ok": True}


@router.get("/{device_id}/shares", response_model=list[DeviceShareOut], dependencies=[Depends(require_operator)])
async def list_device_shares(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DeviceShareOut]:
    """列出设备共享记录（含已撤销历史），仅归属者或 admin+ 可查看。"""
    device = await _get_or_404(db, device_id)
    if not _can_manage_device(device, user):
        raise HTTPException(403, "仅设备归属者或管理员可查看共享设置")
    rows = (
        await db.execute(
            select(DeviceShare)
            .where(DeviceShare.device_id == device.id)
            .order_by(DeviceShare.revoked_at.is_not(None), DeviceShare.id.desc())
        )
    ).scalars().all()
    users = {
        u.id: u for u in (await db.execute(select(User).where(User.id.in_([r.user_id for r in rows])))).scalars().all()
    } if rows else {}
    return [
        DeviceShareOut(
            id=r.id,
            device_id=r.device_id,
            user_id=r.user_id,
            username=users[r.user_id].username if r.user_id in users else "",
            role=users[r.user_id].role if r.user_id in users else "",
            granted_by=r.granted_by,
            granted_by_id=r.granted_by_id,
            created_at=r.created_at,
            revoked_at=r.revoked_at,
            revoked_by=r.revoked_by,
            active=r.revoked_at is None,
        )
        for r in rows
    ]


@router.post("/{device_id}/shares", response_model=DeviceShareOut, dependencies=[Depends(require_operator)])
async def create_device_share(
    device_id: int,
    body: DeviceShareCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DeviceShareOut:
    """同租户内共享设备（viewer 级可见性，不提升写权限），仅归属者或 admin+ 可操作。"""
    device = await _get_or_404(db, device_id)
    if not _can_manage_device(device, user):
        raise HTTPException(403, "仅设备归属者或管理员可共享设备")
    if device.owner_id is not None and body.user_id == device.owner_id:
        raise HTTPException(400, "不能把设备共享给设备归属者本人")
    if body.user_id == user.id:
        raise HTTPException(400, "不能把设备共享给自己")
    target = await db.get(User, body.user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    existing = (
        await db.execute(
            select(DeviceShare).where(
                DeviceShare.device_id == device.id,
                DeviceShare.user_id == body.user_id,
                DeviceShare.revoked_at.is_(None),
            )
        )
    ).scalars().first()
    if existing is not None:
        raise HTTPException(409, f"该用户已在共享列表中：{target.username}")
    share = DeviceShare(
        device_id=device.id,
        user_id=target.id,
        granted_by=user.username,
        granted_by_id=user.id,
    )
    db.add(share)
    await db.commit()
    await db.refresh(share)
    await record_audit(
        db, user.username, "device.share.grant",
        target=f"device:{device.id}",
        detail={"user_id": target.id, "username": target.username, "role": target.role},
    )
    return DeviceShareOut(
        id=share.id,
        device_id=share.device_id,
        user_id=share.user_id,
        username=target.username,
        role=target.role,
        granted_by=share.granted_by,
        granted_by_id=share.granted_by_id,
        created_at=share.created_at,
        active=True,
    )


@router.delete("/{device_id}/shares/{share_id}", dependencies=[Depends(require_operator)])
async def revoke_device_share(
    device_id: int,
    share_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """撤销共享：置 revoked_at，立即失效；仅归属者或 admin+ 可操作。"""
    device = await _get_or_404(db, device_id)
    if not _can_manage_device(device, user):
        raise HTTPException(403, "仅设备归属者或管理员可撤销共享")
    share = await db.get(DeviceShare, share_id)
    if share is None or share.device_id != device.id:
        raise HTTPException(404, "共享记录不存在")
    if share.revoked_at is not None:
        raise HTTPException(409, "该共享已撤销")
    share.revoked_at = datetime.now(timezone.utc)
    share.revoked_by = user.username
    await db.commit()
    await record_audit(
        db, user.username, "device.share.revoke",
        target=f"device:{device.id}",
        detail={"share_id": share.id, "user_id": share.user_id},
    )
    return {"ok": True, "share_id": share.id, "revoked_at": share.revoked_at}


@router.get("/{device_id}/share-candidates", response_model=list[ShareCandidateOut], dependencies=[Depends(require_operator)])
async def device_share_candidates(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ShareCandidateOut]:
    """可共享的同租户用户（排除归属者与已有效共享的用户）。"""
    device = await _get_or_404(db, device_id)
    if not _can_manage_device(device, user):
        raise HTTPException(403, "仅设备归属者或管理员可查看可共享用户")
    shared = set(
        (
            await db.execute(
                select(DeviceShare.user_id).where(
                    DeviceShare.device_id == device.id,
                    DeviceShare.revoked_at.is_(None),
                )
            )
        ).scalars().all()
    )
    rows = (await db.execute(select(User).order_by(User.username))).scalars().all()
    excluded = {user.id, device.owner_id} | shared
    return [
        ShareCandidateOut(id=u.id, username=u.username, role=u.role)
        for u in rows
        if u.id not in excluded
    ]


@router.post("/{device_id}/start", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def start_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    return await services.start_device(db, await _get_or_404(db, device_id))


@router.post("/{device_id}/stop", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def stop_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    return await services.stop_device(db, await _get_or_404(db, device_id))


@router.post("/{device_id}/restart", response_model=DeviceOut, dependencies=[Depends(require_operator)])
async def restart_device(device_id: int, db: AsyncSession = Depends(get_db)) -> Device:
    device = await _get_or_404(db, device_id)
    await services.stop_device(db, device)
    await asyncio.sleep(0.05)
    return await services.start_device(db, device)


@router.post("/{device_id}/screen-lock", dependencies=[Depends(require_operator)])
async def lock_device_screen(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """锁定投屏遮罩（本端）：仅记录审计，不建立后端占用态。

    遮罩由发起端前端维持（显示锁定人与时间，禁用本端控制指令）；
    其他客户端/服务端均不受此状态约束。审计动作：device.screen_lock。
    """
    device = await _get_or_404(db, device_id)
    await record_audit(
        db,
        user.username,
        "device.screen_lock",
        target=f"device:{device.id}",
        detail={
            "backend": settings.device_backend,
            "name": device.name,
            "scope": "client_overlay",
            "server_occupancy": False,
        },
    )
    return {
        "ok": True,
        "device_id": device.id,
        "locked": True,
        "scope": "client_overlay",
        "note": "仅本端投屏遮罩，不是服务端占用；其他端不受影响",
    }


@router.post("/{device_id}/unlock", dependencies=[Depends(require_operator)])
async def unlock_device(
    device_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """解除投屏遮罩（本端）：语义为「解锁本端视觉遮罩」，不是服务端占用释放。

    该接口不操作设备 keyguard，也不释放任何服务端占用；调用仅记录审计
    device.screen_unlock。实际遮罩清除由前端在收到成功响应后本地完成。
    """
    device = await _get_or_404(db, device_id)
    await record_audit(
        db,
        user.username,
        "device.screen_unlock",
        target=f"device:{device.id}",
        detail={
            "backend": settings.device_backend,
            "name": device.name,
            "scope": "client_overlay",
            "server_occupancy": False,
        },
    )
    return {
        "ok": True,
        "device_id": device.id,
        "locked": False,
        "scope": "client_overlay",
        "note": "已解除本端投屏遮罩；该操作不涉及服务端占用",
    }


@router.get("/{device_id}/screenshot")
async def screenshot(
    device_id: int,
    fresh: bool = Query(False, description="true 时跳过帧缓存，强制重新截图"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    if fresh:
        await _check_fresh_rate(user.id, device_id)
    device = await _get_or_404(db, device_id)
    if not fresh:
        cached = hub.cached_frame(device_id)
        if cached:
            return {"device_id": device_id, "frame": cached, "cached": True}
    frame = await services.backend.screenshot(device)
    hub.store_frame(device_id, frame)
    return {"device_id": device_id, "frame": frame, "cached": False}


@router.post("/{device_id}/ban", dependencies=[Depends(require_operator)])
async def ban_device(
    device_id: int,
    body: BanDeviceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """封禁设备（需操作员权限）。"""
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)

    if device.is_banned:
        raise HTTPException(400, "设备已被封禁")

    device.is_banned = True
    device.banned_at = datetime.now(timezone.utc)
    device.banned_reason = body.reason
    await db.commit()
    await db.refresh(device)
    await record_audit(db, user.username, "封禁设备", f"device:{device.id}", {"reason": body.reason})
    return {"ok": True}


@router.post("/{device_id}/unban", dependencies=[Depends(require_operator)])
async def unban_device(
    device_id: int,
    body: UnbanDeviceRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """解封设备（需操作员权限）。"""
    device = await _get_or_404(db, device_id)
    _ensure_can_manage_device(device, user)

    if not device.is_banned:
        raise HTTPException(400, "设备未被封禁")

    device.is_banned = False
    device.banned_at = None
    device.banned_reason = None
    await db.commit()
    await db.refresh(device)
    await record_audit(db, user.username, "解封设备", f"device:{device.id}")
    return {"ok": True}
