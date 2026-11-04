"""下载中心（V2-3）：汇总「我发起的」CSV 报表 / 批量截图 / logcat 导出任务。

设计要点：
- 不新造存储：生成物写入云盘目录并登记一条 CloudFile，下载直接走既有的
  `/cloud-disk/files/{id}/download`，下载中心只提供任务列表与元数据。
- 任务同步生成：结束即 done / failed，不会留下半途 running 需要重启清理。
- 失败不假成功：异常会落一条 status=failed 的任务并带 error，便于前端展示原因。
- 写接口 operator+；创建/删除都写审计。
"""
from __future__ import annotations

import io
import logging
import uuid
import zipfile
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import services
from ..auth import get_current_user
from ..database import get_db
from ..models import CloudFile, Device, DownloadTask, User
from ..rbac import ROLE_LEVELS, record_audit, require_operator
from ..schemas import DownloadCreate, DownloadTaskOut
from .cloud_disk import _category_for, _storage_root
from .reports import build_devices_csv

_log = logging.getLogger("app.downloads")

router = APIRouter(prefix="/downloads", tags=["downloads"], dependencies=[Depends(get_current_user)])

# 单次生成上限：截图要逐台拉帧、日志要逐台 adb，限制数量避免一次点爆后端。
MAX_SHOT_DEVICES = 30
MAX_LOGCAT_DEVICES = 50

_KIND_TITLE = {
    "report_csv": "设备明细报表",
    "screenshots": "批量截图",
    "logcat": "设备日志",
}


def _sees_all(user: User) -> bool:
    return ROLE_LEVELS.get(user.role, 0) >= ROLE_LEVELS["admin"]


def _now_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _task_out(task: DownloadTask) -> dict:
    data = DownloadTaskOut.model_validate(task, from_attributes=True).model_dump(mode="json")
    data["device_ids"] = list((task.params or {}).get("device_ids") or [])
    data["download_url"] = (
        f"/api/cloud-disk/files/{task.cloud_file_id}/download" if task.cloud_file_id else None
    )
    return data


async def _store_bytes(db: AsyncSession, user: User, data: bytes, filename: str) -> CloudFile:
    """写云盘目录并登记 CloudFile（复用云盘的存储与下载链路）。"""
    stored_name = f"{uuid.uuid4().hex}_{filename}"
    path = _storage_root() / stored_name
    path.write_bytes(data)
    record = CloudFile(
        name=filename,
        category=_category_for(filename),
        size_bytes=len(data),
        stored_name=stored_name,
        uploaded_by=user.username,
        owner_id=user.id,
        is_public=False,
    )
    db.add(record)
    await db.flush()
    return record


def _frame_bytes(frame: str) -> tuple[bytes, str]:
    """把后端截图（data URL）还原成字节；返回 (bytes, 扩展名)。"""
    import base64

    header, _, payload = (frame or "").partition(",")
    if not header.startswith("data:") or not payload:
        raise ValueError("截图返回格式不是 data URL")
    mime = header[5:].split(";")[0].lower()
    ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/svg+xml": ".svg"}.get(mime, ".bin")
    return base64.b64decode(payload), ext


def _entry_name(device: Device, ext: str) -> str:
    """压缩包内文件名：去掉路径分隔符等非法字符。"""
    safe = (device.name or f"device-{device.id}").replace("/", "_").replace("\\", "_")
    safe = "".join(ch for ch in safe if ch not in ':*?"<>|').strip() or f"device-{device.id}"
    return f"#{device.id}_{safe}{ext}"


async def _build_report_csv(db: AsyncSession) -> tuple[bytes, str]:
    devices = list((await db.execute(select(Device).order_by(Device.id))).scalars().all())
    return build_devices_csv(devices).encode("utf-8"), f"设备报表_{_now_ts()}.csv"


async def _build_screenshots(devices: list[Device]) -> tuple[bytes, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in devices:
            frame = await services.backend.screenshot(d)
            data, ext = _frame_bytes(frame)
            zf.writestr(_entry_name(d, ext), data)
    return buf.getvalue(), f"批量截图_{len(devices)}台_{_now_ts()}.zip"


async def _build_logcat(devices: list[Device], lines: int) -> tuple[bytes, str]:
    out: list[str] = [
        "# 云手机 logcat 导出",
        f"# 导出时间: {datetime.now().isoformat(timespec='seconds')}",
        f"# 设备数: {len(devices)} / 每台 {lines} 行",
        "",
    ]
    for d in devices:
        out.append(f"=== #{d.id} {d.name} ===")
        out.extend(await services.backend.list_logcat(d, lines))
        out.append("")
    return "\n".join(out).encode("utf-8"), f"设备日志_{len(devices)}台_{_now_ts()}.txt"


@router.get("", response_model=list[DownloadTaskOut])
async def list_tasks(
    kind: str | None = Query(None, max_length=16),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """我发起的下载任务；admin+ 可看全部。"""
    stmt = select(DownloadTask).order_by(DownloadTask.created_at.desc(), DownloadTask.id.desc())
    if not _sees_all(user):
        stmt = stmt.where(DownloadTask.owner_id == user.id)
    if kind:
        if kind not in _KIND_TITLE:
            raise HTTPException(400, f"未知下载类型: {kind}")
        stmt = stmt.where(DownloadTask.kind == kind)
    rows = list((await db.execute(stmt.limit(limit))).scalars().all())
    return [_task_out(r) for r in rows]


@router.post("", dependencies=[Depends(require_operator)])
async def create_task(
    body: DownloadCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    devices: list[Device] = []
    if body.kind == "screenshots":
        if not body.device_ids:
            raise HTTPException(400, "请至少选择一台设备")
        if len(set(body.device_ids)) > MAX_SHOT_DEVICES:
            raise HTTPException(400, f"批量截图一次最多 {MAX_SHOT_DEVICES} 台")
    elif body.kind == "logcat":
        if not body.device_ids:
            raise HTTPException(400, "请至少选择一台设备")
        if len(set(body.device_ids)) > MAX_LOGCAT_DEVICES:
            raise HTTPException(400, f"日志导出一次最多 {MAX_LOGCAT_DEVICES} 台")

    if body.device_ids:
        devices = list(
            (await db.execute(select(Device).where(Device.id.in_(set(body.device_ids))))).scalars().all()
        )
        if len(devices) != len(set(body.device_ids)):
            raise HTTPException(404, "部分设备不存在，请刷新后重试")

    title = body.title.strip() or _KIND_TITLE[body.kind]
    params = {"device_ids": [d.id for d in devices], "lines": body.lines}
    task = DownloadTask(
        kind=body.kind,
        title=title,
        status="done",
        params=params,
        created_by=user.username,
        owner_id=user.id,
    )
    try:
        if body.kind == "report_csv":
            data, filename = await _build_report_csv(db)
        elif body.kind == "screenshots":
            data, filename = await _build_screenshots(devices)
        else:
            data, filename = await _build_logcat(devices, body.lines)
        record = await _store_bytes(db, user, data, filename)
        task.filename = filename
        task.cloud_file_id = record.id
        task.size_bytes = record.size_bytes
    except Exception as exc:  # 失败落库并保留原因，不假装成功
        await db.rollback()
        task = DownloadTask(
            kind=body.kind,
            title=title,
            status="failed",
            error=str(exc)[:200],
            params=params,
            created_by=user.username,
            owner_id=user.id,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        await record_audit(
            db, user.username, "download.create", target=title, detail={"kind": body.kind, "status": "failed"}
        )
        _log.warning("downloads.create failed kind=%s err=%s", body.kind, exc)
        return _task_out(task)

    db.add(task)
    await db.commit()
    await db.refresh(task)
    await record_audit(
        db,
        user.username,
        "download.create",
        target=task.filename,
        detail={"kind": body.kind, "size": task.size_bytes, "devices": len(devices)},
    )
    _log.info("downloads.create id=%s kind=%s size=%s", task.id, body.kind, task.size_bytes)
    return _task_out(task)


@router.delete("/{task_id}", dependencies=[Depends(require_operator)])
async def delete_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """删除任务并连带清理云盘生成物（避免云盘里留下孤儿文件）。"""
    task = await db.get(DownloadTask, task_id)
    if task is None:
        raise HTTPException(404, "下载任务不存在")
    if not _sees_all(user) and task.owner_id != user.id:
        raise HTTPException(403, "只能删除自己发起的任务")

    if task.cloud_file_id:
        record = await db.get(CloudFile, task.cloud_file_id)
        if record is not None:
            (_storage_root() / record.stored_name).unlink(missing_ok=True)
            await db.delete(record)

    filename = task.filename
    await db.delete(task)
    await db.commit()
    await record_audit(db, user.username, "download.delete", target=filename or f"task {task_id}")
    return {"ok": True, "id": task_id}
