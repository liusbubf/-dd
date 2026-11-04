"""设备服务层：把「数据库 + 编排后端 + 指纹 + WS 广播」编排到一起。

routers 调用这里，避免在路由里堆业务逻辑。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import SessionLocal
from .fingerprint import generate_fingerprint
from .ip_routing import apply_bound_network
from .models import Device, DeviceSnapshot, DeviceStatus
from .orchestrator import get_backend
from .schemas import DeviceOut
from .ws_manager import manager

backend = get_backend()
_log = logging.getLogger("services")

_task_registry: set[asyncio.Task] = set()


class DeviceClaimed(RuntimeError):
    """设备已被其他成员占用。"""

    def __init__(self, claimed_by: str) -> None:
        self.claimed_by = claimed_by
        super().__init__(f"设备已被 {claimed_by} 占用")


class RenewInProgress(RuntimeError):
    """同一台设备不允许并发的「一键新机」。"""

    def __init__(self, device_id: int) -> None:
        self.device_id = device_id
        super().__init__(f"设备 {device_id} 正在一键新机中，请稍后再试")


class SnapshotFailed(RuntimeError):
    """快照创建/恢复失败（记录可能已落库，便于前端展示错误状态）。"""

    def __init__(self, snapshot_id: int | None, detail: str) -> None:
        self.snapshot_id = snapshot_id
        self.detail = detail
        super().__init__(f"快照操作失败：{detail}")


class DisplayChangeError(RuntimeError):
    """分辨率/DPI 切换失败；已尽力回滚，detail 中带回滚结果。"""

    def __init__(self, detail: str, rolled_back: bool) -> None:
        self.detail = detail
        self.rolled_back = rolled_back
        suffix = "，已回滚到原分辨率" if rolled_back else "，且回滚失败，请手动恢复原始分辨率"
        super().__init__(f"切换显示参数失败：{detail}{suffix}")


# 进行中的设备（含排队）：防止同一台被重复重置导致容器互删
_renewing: set[int] = set()
# 快照操作中的设备：避免同机打包/恢复/删除互相踩踏
_snapshotting: set[int] = set()
# device_id -> {device_id, phase, mode}；供页面刷新后补齐进度
_renew_progress: dict[int, dict] = {}
_renew_sem: asyncio.Semaphore | None = None


def _renew_semaphore() -> asyncio.Semaphore:
    global _renew_sem
    if _renew_sem is None:
        _renew_sem = asyncio.Semaphore(max(1, settings.renew_concurrency))
    return _renew_sem


def renewing_snapshot() -> list[dict]:
    return list(_renew_progress.values())


async def _report_renew(device_id: int, phase: str, **extra) -> None:
    info = {"device_id": device_id, "phase": phase, **extra}
    if phase in ("done", "failed"):
        _renew_progress.pop(device_id, None)
    else:
        _renew_progress[device_id] = info
    await manager.broadcast({"type": "renew_progress", **info})


def _pick_proxy() -> str | None:
    """新建设备用：没有显式绑定/指定代理时从代理池挑一个。"""
    from .orchestrator.base import pick_proxy

    return pick_proxy(None)


async def create_device(
    db: AsyncSession,
    *,
    name: str,
    group_id: int | None,
    width: int,
    height: int,
    dpi: int,
    target_url: str | None = None,
    proxy: str | None = None,
    auto_start: bool = True,
    fingerprint_mode: str = "commercial",
    region: str | None = None,
    owner_id: int | None = None,
) -> Device:
    """建库 → 生成一机一码 → 后端拉起（可选自动启动）。"""
    fp = generate_fingerprint(
        proxy=proxy or _pick_proxy(),
        mode=fingerprint_mode,
        region=region,
    )
    device = Device(
        name=name,
        group_id=group_id,
        width=width,
        height=height,
        dpi=dpi,
        orig_width=width,
        orig_height=height,
        orig_dpi=dpi,
        current_url=target_url,
        fingerprint=fp,
        status=DeviceStatus.creating,
        owner_id=owner_id,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)

    try:
        prov = await backend.create(device)
        device.backend_ref = prov.backend_ref
        device.adb_port = prov.adb_port
        if auto_start:
            await backend.start(device)
            if target_url:
                await backend.open_url(device, target_url)
            device.status = DeviceStatus.running
        else:
            device.status = DeviceStatus.stopped
    except Exception:  # noqa: BLE001  后端拉起失败标记 error，不阻塞其它设备
        device.status = DeviceStatus.error

    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def adopt_device(
    db: AsyncSession,
    *,
    serial: str,
    name: str | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
) -> Device:
    """纳管一台已连接的真实手机（只记录设备原值，不生成/篡改硬件标识）。"""
    from .orchestrator.physical import list_adb_devices, probe_device

    serial = (serial or "").strip()
    if not serial:
        raise ValueError("ADB 序列号不能为空")

    entry = next((d for d in await list_adb_devices() if d["serial"] == serial), None)
    if entry is None:
        raise ValueError("设备不在线：请确认 USB 调试已连接，或无线调试地址可达")
    if entry["state"] != "device":
        raise ValueError(f"设备状态为 {entry['state']}，请先在手机上授权 USB 调试")

    existing = (
        await db.execute(select(Device).where(Device.backend_ref == serial))
    ).scalars().first()
    if existing is not None:
        raise ValueError(f"该设备已接入：{existing.name}")

    info = await probe_device(serial)
    adb_port = None
    if ":" in serial:
        try:
            adb_port = int(serial.rsplit(":", 1)[1])
        except ValueError:
            adb_port = None

    device = Device(
        name=((name or "").strip()[:128] or f"{info['model']} ({serial[-4:]})"),
        group_id=group_id,
        backend_ref=serial,
        adb_port=adb_port,
        width=info["width"],
        height=info["height"],
        dpi=info["dpi"],
        orig_width=info["width"],
        orig_height=info["height"],
        orig_dpi=info["dpi"],
        skin="",
        fingerprint={
            "mode": "physical",
            "seed": f"physical-{serial}",
            "device": {
                "brand": info["brand"],
                "model": info["model"],
                "android_version": info["android_version"],
                "serial": serial,
            },
            "network": {"proxy": None, "exit_ip": ""},
            "browser": {},
        },
        status=DeviceStatus.running,
        renew_state="idle",
        owner_id=owner_id,
    )
    db.add(device)
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def set_device_display(
    db: AsyncSession, device: Device, width: int, height: int, dpi: int
) -> Device:
    """切换分辨率/DPI，失败时尽力回滚到切换前的值。

    后端能力差异：
    - redroid：重建容器（framebuffer 是容器参数），耗时长；
    - physical：adb `wm size` / `wm density`，即时生效；
    - simulator：只改内存态。
    """
    old = (device.width, device.height, device.dpi)
    try:
        await backend.set_display(device, width, height, dpi)
    except Exception as exc:  # noqa: BLE001  失败必须回滚并如实报错
        try:
            await backend.set_display(device, *old)
        except Exception as rb:  # noqa: BLE001
            raise DisplayChangeError(f"{exc}；回滚失败：{rb}", rolled_back=False) from exc
        raise DisplayChangeError(str(exc), rolled_back=True) from exc
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def reset_device_display(db: AsyncSession, device: Device) -> Device:
    """恢复到设备创建时的原始分辨率/密度。"""
    ow = device.orig_width or device.width
    oh = device.orig_height or device.height
    od = device.orig_dpi or device.dpi
    return await set_device_display(db, device, ow, oh, od)


async def set_device_render_quality(db: AsyncSession, device: Device, quality: str) -> Device:
    """保存投屏渲染质量；下次准备 scrcpy 时按 low/medium/high 生成参数。"""
    device.render_quality = quality
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def start_device(db: AsyncSession, device: Device) -> Device:
    await backend.start(device)
    device.status = DeviceStatus.running
    device.renew_state = "idle"  # 手动拉起成功即视为脱离开机失败状态
    if device.current_url:
        await backend.open_url(device, device.current_url)
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def stop_device(db: AsyncSession, device: Device) -> Device:
    await backend.stop(device)
    device.status = DeviceStatus.stopped
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def destroy_device(db: AsyncSession, device: Device) -> None:
    await backend.destroy(device)
    # 快照数据不会随容器消失，必须显式清理，避免磁盘泄漏
    snaps = (
        await db.execute(
            select(DeviceSnapshot).where(DeviceSnapshot.device_id == device.id)
        )
    ).scalars().all()
    for snap in snaps:
        if snap.backend_ref:
            try:
                await backend.delete_snapshot(device, snap.backend_ref)
            except Exception as e:  # noqa: BLE001  数据目录可能已随设备消失
                _log.warning("删除设备快照数据失败 snapshot=%s: %s", snap.id, e)
        await db.delete(snap)
    await db.delete(device)
    await db.commit()
    await manager.broadcast({"type": "device_removed", "device_id": device.id})


async def broadcast_device(device: Device) -> None:
    await manager.broadcast(
        {"type": "device_status", "device": DeviceOut.model_validate(device).model_dump(mode="json")}
    )


# ---------- 设备池：占用 / 巡检 ----------


def _is_admin(role: str) -> bool:
    return role in ("admin", "superadmin")


async def claim_device(
    db: AsyncSession, device: Device, username: str, role: str
) -> Device:
    if device.claimed_by == username:
        return device
    if device.claimed_by and not _is_admin(role):
        raise DeviceClaimed(device.claimed_by)
    device.claimed_by = username
    device.claimed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def release_device(
    db: AsyncSession, device: Device, username: str, role: str
) -> Device:
    if not device.claimed_by:
        return device
    if device.claimed_by != username and not _is_admin(role):
        raise PermissionError(f"设备由 {device.claimed_by} 占用，只有本人或管理员可释放")
    device.claimed_by = None
    device.claimed_at = None
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)
    return device


async def check_devices(db: AsyncSession) -> dict:
    """并发巡检全部设备，并同步状态：在线 → running，掉线 running → error。

    停止状态的设备不会被巡检改成 error；后端不支持巡检时跳过（simulator 返回 True）。
    """
    ids = list((await db.execute(select(Device.id))).scalars().all())
    sem = asyncio.Semaphore(max(1, settings.batch_concurrency))

    async def _check(did: int):
        async with sem:
            async with SessionLocal() as s:
                device = await s.get(Device, did)
                if device is None:
                    return None
                try:
                    healthy = await backend.check_health(device)
                except Exception:  # noqa: BLE001  单台异常不影响整体巡检
                    healthy = False
                return did, healthy

    pairs = [p for p in await asyncio.gather(*(_check(i) for i in ids)) if p]

    result = {
        "total": len(ids),
        "checked": 0,
        "healthy": 0,
        "unhealthy": 0,
        "changed": 0,
        "skipped": 0,
    }
    changed: list[Device] = []
    async with SessionLocal() as s:
        for did, healthy in pairs:
            if healthy is None:
                result["skipped"] += 1
                continue
            result["checked"] += 1
            device = await s.get(Device, did)
            if device is None:
                continue
            if healthy:
                result["healthy"] += 1
                if device.status == DeviceStatus.error:
                    device.status = DeviceStatus.running
                    changed.append(device)
            else:
                result["unhealthy"] += 1
                if device.status == DeviceStatus.running:
                    device.status = DeviceStatus.error
                    changed.append(device)
        await s.commit()

    result["changed"] = len(changed)
    for device in changed:
        await broadcast_device(device)
    return result


# ---------- 设备快照 ----------


def _default_snapshot_name() -> str:
    return f"快照-{datetime.now():%Y%m%d-%H%M%S}"


async def list_snapshots(db: AsyncSession, device_id: int) -> list[DeviceSnapshot]:
    stmt = (
        select(DeviceSnapshot)
        .where(DeviceSnapshot.device_id == device_id)
        .order_by(DeviceSnapshot.id.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def latest_ready_snapshot(db: AsyncSession, device_id: int) -> DeviceSnapshot | None:
    """最近一次可用快照；没有则返回 None，由路由明确报错而不是假成功。"""
    stmt = (
        select(DeviceSnapshot)
        .where(
            DeviceSnapshot.device_id == device_id,
            DeviceSnapshot.status == "ready",
            DeviceSnapshot.backend_ref.is_not(None),
        )
        .order_by(DeviceSnapshot.id.desc())
    )
    return (await db.execute(stmt)).scalars().first()


def _begin_snapshot_op(device: Device) -> None:
    if device.id in _renewing:
        raise RenewInProgress(device.id)
    if device.id in _snapshotting:
        raise SnapshotFailed(None, "该设备正在执行其他快照操作，请稍后再试")
    _snapshotting.add(device.id)


async def create_snapshot(db: AsyncSession, device: Device, name: str = "") -> DeviceSnapshot:
    _begin_snapshot_op(device)
    try:
        snap = DeviceSnapshot(
            device_id=device.id,
            name=(name or "").strip()[:128] or _default_snapshot_name(),
            status="creating",
        )
        db.add(snap)
        await db.commit()
        await db.refresh(snap)

        try:
            result = await backend.snapshot(device, snap.id)
        except Exception as e:  # noqa: BLE001  失败记录保留，供前端展示与重试
            snap.status = "error"
            snap.note = str(e)[:500]
            await db.commit()
            await db.refresh(snap)
            raise SnapshotFailed(snap.id, str(e)) from e

        snap.backend_ref = result.backend_ref
        snap.size_bytes = result.size_bytes
        snap.status = "ready"
        await db.commit()
        await db.refresh(snap)
        _log.info("快照创建完成 device=%s snapshot=%s size=%s",
                  device.id, snap.id, snap.size_bytes)
        return snap
    finally:
        _snapshotting.discard(device.id)


async def restore_snapshot(
    db: AsyncSession, device: Device, snap: DeviceSnapshot
) -> Device:
    _begin_snapshot_op(device)
    try:
        if snap.device_id != device.id:
            raise SnapshotFailed(snap.id, "快照不属于该设备")
        if snap.status != "ready" or not snap.backend_ref:
            raise SnapshotFailed(snap.id, "快照尚未就绪，无法恢复")

        snap.status = "restoring"
        await db.commit()
        try:
            await backend.restore_snapshot(device, snap.backend_ref)
        except Exception as e:  # noqa: BLE001
            snap.status = "ready"  # 快照文件仍完好，可重试
            device.status = DeviceStatus.error
            await db.commit()
            await db.refresh(device)
            await db.refresh(snap)
            await broadcast_device(device)
            raise SnapshotFailed(snap.id, str(e)) from e

        snap.status = "ready"
        device.status = DeviceStatus.running
        device.renew_state = "idle"
        await db.commit()
        await db.refresh(device)
        await db.refresh(snap)
        await broadcast_device(device)
        _log.info("快照恢复完成 device=%s snapshot=%s", device.id, snap.id)
        return device
    finally:
        _snapshotting.discard(device.id)


async def delete_snapshot(
    db: AsyncSession, device: Device, snap: DeviceSnapshot
) -> None:
    _begin_snapshot_op(device)
    try:
        if snap.backend_ref:
            try:
                await backend.delete_snapshot(device, snap.backend_ref)
            except Exception as e:  # noqa: BLE001  文件可能已不存在，记录照删
                _log.warning("删除快照数据失败 snapshot=%s: %s", snap.id, e)
        await db.delete(snap)
        await db.commit()
    finally:
        _snapshotting.discard(device.id)


# ---------- 一键新机 ----------


async def renew_device(
    db: AsyncSession,
    device: Device,
    *,
    mode: str = "hard",
    rotate_proxy: bool = False,
    keep_url: bool = False,
) -> Device:
    """同步执行一台设备的新机（供定时任务/内部调用；HTTP 接口走批量入队）。"""
    if device.id in _renewing:
        raise RenewInProgress(device.id)
    _renewing.add(device.id)
    try:
        return await _do_renew(
            db, device, mode=mode, rotate_proxy=rotate_proxy, keep_url=keep_url
        )
    finally:
        _renewing.discard(device.id)


async def wipe_device_data(db: AsyncSession, device: Device) -> Device:
    """清空数据（保留设备）：复用各后端 clear_data 擦除路径。

    - redroid：销毁容器 → `_wipe_data` 擦除 /data → 重建并启动；
    - physical：pm clear + sdcard 擦除 + 重启；
    - simulator：重置内存态并重新启动。
    设备记录、分组、断占、IP 绑定均保留；不更换设备身份。
    """
    return await renew_device(
        db, device, mode="clear_data", rotate_proxy=False, keep_url=False
    )


async def _do_renew(
    db: AsyncSession,
    device: Device,
    *,
    mode: str,
    rotate_proxy: bool,
    keep_url: bool,
) -> Device:
    did = device.id
    await _report_renew(did, "queued", mode=mode)

    device.renew_state = "renewing"
    device.status = DeviceStatus.creating
    await db.commit()
    await db.refresh(device)
    await broadcast_device(device)

    async def _cb(phase: str) -> None:
        await _report_renew(did, phase, mode=mode)

    # 显式绑定 IP 优先：绑定后一键新机不得再随机换出口
    bound = await apply_bound_network(db, device)
    if bound:
        await db.commit()
        await db.refresh(device)
        rotate_proxy = False

    try:
        result = await backend.renew(
            device,
            mode=mode,
            rotate_proxy=rotate_proxy,
            keep_url=keep_url,
            progress=_cb,
        )
        device.renew_count = (device.renew_count or 0) + 1
        device.last_renew_at = datetime.now(timezone.utc)
        device.renew_state = "idle"
        device.status = DeviceStatus.running
        await db.commit()
        await db.refresh(device)
        await broadcast_device(device)
        await _report_renew(
            did,
            "done",
            mode=mode,
            renew_count=device.renew_count,
            fingerprint_changed=result.fingerprint_changed,
            duration_s=result.duration_s,
            warnings=result.warnings,
        )
        _log.info(
            "一键新机完成 device=%s mode=%s 指纹变化=%s 耗时=%.1fs",
            did, mode, result.fingerprint_changed, result.duration_s,
        )
        return device
    except Exception as e:  # noqa: BLE001  失败要落库并广播，不能只记日志
        device.renew_state = "failed"
        device.status = DeviceStatus.error
        await db.commit()
        await db.refresh(device)
        await broadcast_device(device)
        await _report_renew(did, "failed", mode=mode, error=str(e))
        _log.exception("一键新机失败 device=%s mode=%s", did, mode)
        raise


async def batch_renew(
    device_ids: list[int],
    *,
    mode: str = "hard",
    rotate_proxy: bool = False,
    keep_url: bool = False,
) -> dict:
    """批量新机：立即返回，后台按 renew_concurrency 限流逐台执行。

    进行中的设备会被跳过（同一台不能并行删/建容器）。
    """
    ids = list(dict.fromkeys(device_ids))
    accepted: list[int] = []
    skipped: list[int] = []
    for did in ids:
        if did in _renewing:
            skipped.append(did)
        else:
            _renewing.add(did)
            accepted.append(did)

    for did in accepted:
        await _report_renew(did, "queued", mode=mode)

    if accepted:
        task = asyncio.create_task(
            _run_batch_renew(
                accepted, mode=mode, rotate_proxy=rotate_proxy, keep_url=keep_url
            )
        )
        _task_registry.add(task)
        task.add_done_callback(_task_registry.discard)

    return {"queued": len(accepted), "skipped": skipped, "device_ids": accepted}


async def _run_batch_renew(
    ids: list[int],
    *,
    mode: str,
    rotate_proxy: bool,
    keep_url: bool,
) -> None:
    sem = _renew_semaphore()

    async def _one(did: int) -> None:
        async with sem:
            try:
                async with SessionLocal() as db:
                    device = await db.get(Device, did)
                    if device is None:
                        return
                    await _do_renew(
                        db, device,
                        mode=mode, rotate_proxy=rotate_proxy, keep_url=keep_url,
                    )
            except Exception:  # noqa: BLE001  _do_renew 已上报 failed 并记录日志
                pass
            finally:
                _renewing.discard(did)

    await asyncio.gather(*(_one(i) for i in ids))
