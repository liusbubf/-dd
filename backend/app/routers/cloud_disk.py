"""云盘：文件上传 / 分类 / 下载 / 删除 / 批量下发到云机（进度可轮询）。

权限与归属：
- 普通用户（viewer/operator）只能看到自己的文件 + 公共文件；
- admin/superadmin 可以看到全部文件；
- 删除仅文件归属人本人或 admin+；
- 下发任务落库，服务重启后历史可查，进行中的任务标记为 interrupted。
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from .. import services
from ..auth import get_current_user
from ..config import settings
from ..database import SessionLocal, get_db
from ..models import CloudFile, CloudPushJob, Device, User
from ..rbac import ROLE_LEVELS, record_audit, require_admin, require_operator
from ..schemas import CLOUD_CATEGORIES, CloudFileOut, CloudFileUpdate, CloudPushRequest

_log = logging.getLogger("app.cloud_disk")

router = APIRouter(prefix="/cloud-disk", tags=["cloud-disk"], dependencies=[Depends(get_current_user)])

# 单文件上限 200MB，避免一次上传打爆磁盘
MAX_FILE_BYTES = 200 * 1024 * 1024
# 共享空间配额（仅用于前端展示，不做硬限制）
QUOTA_BYTES = 5 * 1024 * 1024 * 1024

_EXT_CATEGORY = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"},
    "video": {".mp4", ".mov", ".avi", ".mkv", ".webm"},
    "apk": {".apk", ".xapk", ".apks"},
    "document": {".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".json", ".md"},
}


def _storage_root() -> Path:
    raw = (settings.cloud_disk_dir or "").strip()
    base = Path(raw) if raw else Path(__file__).resolve().parents[2] / "cloud_disk_storage"
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[2] / base
    base.mkdir(parents=True, exist_ok=True)
    return base


def _category_for(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in _EXT_CATEGORY.items():
        if ext in exts:
            return cat
    return "other"


def _safe_name(name: str) -> str:
    """只保留文件名本身：浏览器可能带 ../ 或反斜杠，直接落盘会造成路径穿越。"""
    base = os.path.basename((name or "").replace("\\", "/")).strip()
    base = base.replace("\x00", "")
    if not base or base in (".", ".."):
        raise HTTPException(400, "非法文件名")
    if len(base) > 200:
        base = base[-200:]
    return base


def _safe_remote_dir(path: str) -> str:
    p = (path or "").strip()
    if not p.startswith("/"):
        raise HTTPException(400, "remote_dir 必须是设备上的绝对路径")
    if ".." in p.split("/"):
        raise HTTPException(400, "remote_dir 不允许包含 ..")
    return p.rstrip("/") or "/"


def _file_path(record: CloudFile) -> Path:
    # stored_name 由后端生成（uuid + 安全文件名），不接受外部输入
    return _storage_root() / record.stored_name


def _sees_all(user: User) -> bool:
    return ROLE_LEVELS.get(user.role, 0) >= ROLE_LEVELS["admin"]


def _visible_clause(user: User):
    """普通用户可见范围：公共文件 + 自己的文件（兼容 owner_id 为空的老数据）。"""
    if _sees_all(user):
        return None
    return or_(
        CloudFile.is_public.is_(True),
        CloudFile.owner_id == user.id,
        CloudFile.uploaded_by == user.username,
    )


def _can_read(user: User, record: CloudFile) -> bool:
    if _sees_all(user):
        return True
    if bool(record.is_public):
        return True
    if record.owner_id is not None:
        return record.owner_id == user.id
    return record.uploaded_by == user.username


def _is_owner(user: User, record: CloudFile) -> bool:
    if record.owner_id is not None:
        return record.owner_id == user.id
    return record.uploaded_by == user.username


def _job_out(job: CloudPushJob, *, with_items: bool = True) -> dict:
    data = {
        "id": job.id,
        "status": job.status,
        "total": job.total,
        "done": job.done,
        "failed": job.failed,
        "remote_dir": job.remote_dir,
        "created_by": job.created_by,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }
    if with_items:
        data["items"] = list(job.items or [])
    return data


@router.get("/categories")
async def categories() -> dict:
    return {
        "categories": [{"key": c, "label": c} for c in CLOUD_CATEGORIES],
        "quota_bytes": QUOTA_BYTES,
    }


@router.get("/files")
async def list_files(
    category: str | None = Query(None, max_length=32),
    q: str | None = Query(None, max_length=128),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    stmt = select(CloudFile).order_by(CloudFile.created_at.desc(), CloudFile.id.desc())
    visible = _visible_clause(user)
    if visible is not None:
        stmt = stmt.where(visible)
    if category:
        if category not in CLOUD_CATEGORIES:
            raise HTTPException(400, f"未知分类: {category}")
        stmt = stmt.where(CloudFile.category == category)
    if q:
        stmt = stmt.where(CloudFile.name.ilike(f"%{q}%"))
    rows = list((await db.execute(stmt)).scalars().all())

    used_stmt = select(func.coalesce(func.sum(CloudFile.size_bytes), 0))
    if visible is not None:
        used_stmt = used_stmt.where(visible)
    used = int((await db.execute(used_stmt)).scalar_one())
    return {
        "files": [CloudFileOut.model_validate(r).model_dump(mode="json") for r in rows],
        "used_bytes": used,
        "quota_bytes": QUOTA_BYTES,
    }


@router.post("/files", response_model=CloudFileOut, dependencies=[Depends(require_operator)])
async def upload_file(
    file: UploadFile = File(...),
    category: str = Form("auto"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CloudFile:
    name = _safe_name(file.filename or "")
    cat = _category_for(name) if category in ("auto", "") else category
    if cat not in CLOUD_CATEGORIES:
        raise HTTPException(400, f"未知分类: {cat}")

    stored_name = f"{uuid.uuid4().hex}_{name}"
    dest = _storage_root() / stored_name
    tmp = dest.with_suffix(dest.suffix + ".part")
    size = 0
    try:
        with tmp.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(413, "文件超过 200MB 上限")
                out.write(chunk)
        os.replace(tmp, dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

    record = CloudFile(
        name=name,
        category=cat,
        size_bytes=size,
        stored_name=stored_name,
        uploaded_by=user.username,
        owner_id=user.id,
        is_public=False,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    await record_audit(db, user.username, "cloud.upload", target=name, detail={"size": size})
    _log.info("cloud_disk.upload name=%s size=%s by=%s", name, size, user.username)
    return record


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    record = await db.get(CloudFile, file_id)
    if record is None:
        raise HTTPException(404, "文件不存在")
    if not _can_read(user, record):
        raise HTTPException(403, "无权访问该文件")
    path = _file_path(record)
    if not path.exists():
        raise HTTPException(404, "文件已丢失（可能被清理）")
    return FileResponse(path, filename=record.name, media_type="application/octet-stream")


@router.patch("/files/{file_id}", response_model=CloudFileOut, dependencies=[Depends(require_admin)])
async def update_file(
    file_id: int,
    body: CloudFileUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CloudFile:
    """admin+ 设置/取消公共文件。"""
    record = await db.get(CloudFile, file_id)
    if record is None:
        raise HTTPException(404, "文件不存在")
    record.is_public = body.is_public
    await db.commit()
    await db.refresh(record)
    await record_audit(
        db,
        user.username,
        "cloud.share",
        target=record.name,
        detail={"is_public": body.is_public},
    )
    return record


@router.delete("/files/{file_id}", dependencies=[Depends(require_operator)])
async def delete_file(
    file_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    record = await db.get(CloudFile, file_id)
    if record is None:
        raise HTTPException(404, "文件不存在")
    if not _sees_all(user) and not _is_owner(user, record):
        raise HTTPException(403, "只能删除自己的文件")
    path = _file_path(record)
    path.unlink(missing_ok=True)
    name = record.name
    await db.delete(record)
    await db.commit()
    await record_audit(db, user.username, "cloud.delete", target=name)
    return {"ok": True, "id": file_id}


@router.post("/push", dependencies=[Depends(require_operator)])
async def push_to_devices(
    body: CloudPushRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    remote_dir = _safe_remote_dir(body.remote_dir)
    files = list(
        (await db.execute(select(CloudFile).where(CloudFile.id.in_(body.file_ids)))).scalars().all()
    )
    if len(files) != len(set(body.file_ids)):
        raise HTTPException(400, "部分文件不存在，请刷新后重试")
    if any(not _can_read(user, f) for f in files):
        raise HTTPException(403, "部分文件无权访问，无法下发")
    devices = list(
        (await db.execute(select(Device).where(Device.id.in_(body.device_ids)))).scalars().all()
    )
    if len(devices) != len(set(body.device_ids)):
        raise HTTPException(404, "部分设备不存在，请刷新后重试")

    job_id = uuid.uuid4().hex
    total = len(files) * len(devices)
    items = [
        {
            "device_id": d.id,
            "device_name": d.name,
            "file_id": f.id,
            "file_name": f.name,
            "status": "pending",
            "error": "",
        }
        for d in devices
        for f in files
    ]
    job = CloudPushJob(
        id=job_id,
        status="running",
        total=total,
        done=0,
        failed=0,
        remote_dir=remote_dir,
        items=items,
        created_by=user.username,
    )
    db.add(job)
    await db.commit()

    file_rows = [{"id": f.id, "name": f.name, "stored_name": f.stored_name} for f in files]
    device_ids = [d.id for d in devices]
    asyncio.create_task(_run_push(job_id, file_rows, device_ids, remote_dir, user.username))
    return {"job_id": job_id, "total": total, "status": "running"}


async def _run_push(
    job_id: str, files: list[dict], device_ids: list[int], remote_dir: str, username: str
) -> None:
    """后台串行下发：单并发避免同时开多个 adb，进度按设备写回数据库。"""
    async with SessionLocal() as db:
        job = await db.get(CloudPushJob, job_id)
        if job is None:
            return
        # 深拷贝一份：JSON 列不支持原地变更追踪，直接改原列表不会被识别为脏数据
        items = [dict(i) for i in (job.items or [])]
        for device_id in device_ids:
            device = await db.get(Device, device_id)
            for f in files:
                item = next(
                    (i for i in items if i["device_id"] == device_id and i["file_id"] == f["id"]),
                    None,
                )
                if item is None:
                    continue
                if item["status"] != "pending":
                    continue  # 任务可能被重启中断过，已完成的项不重复执行
                if device is None:
                    item["status"] = "failed"
                    item["error"] = "设备已删除"
                    continue
                local = _storage_root() / f["stored_name"]
                remote = f"{remote_dir}/{f['name']}"
                try:
                    await services.backend.push_file(device, str(local), remote)
                    item["status"] = "ok"
                except Exception as exc:  # 单次失败不阻断整批
                    item["status"] = "failed"
                    item["error"] = str(exc)[:200]
                await asyncio.sleep(0)
            # 每台设备结束持久化一次，重启后进度不丢
            job.items = [dict(i) for i in items]
            job.done = sum(1 for i in items if i["status"] == "ok")
            job.failed = sum(1 for i in items if i["status"] == "failed")
            flag_modified(job, "items")
            await db.commit()

        job.items = [dict(i) for i in items]
        job.done = sum(1 for i in items if i["status"] == "ok")
        job.failed = sum(1 for i in items if i["status"] == "failed")
        flag_modified(job, "items")
        if job.failed == 0:
            job.status = "done"
        elif job.done == 0:
            job.status = "failed"
        else:
            job.status = "partial"
        await db.commit()
        await record_audit(
            db,
            username,
            "cloud.push",
            target=f"{len(files)} files -> {len(device_ids)} devices",
            detail={"job_id": job_id, "done": job.done, "failed": job.failed},
        )
    _log.info("cloud_disk.push job=%s done=%s failed=%s", job_id, job.done, job.failed)


@router.get("/push")
async def list_push_jobs(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """最近下发任务：普通用户只看自己发起的，admin+ 看全部。"""
    stmt = select(CloudPushJob).order_by(CloudPushJob.created_at.desc()).limit(limit)
    if not _sees_all(user):
        stmt = stmt.where(CloudPushJob.created_by == user.username)
    rows = list((await db.execute(stmt)).scalars().all())
    return {"jobs": [_job_out(r, with_items=False) for r in rows]}


@router.get("/push/{job_id}")
async def push_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    job = await db.get(CloudPushJob, job_id)
    if job is None:
        raise HTTPException(404, "下发任务不存在")
    if not _sees_all(user) and job.created_by != user.username:
        raise HTTPException(403, "无权查看该任务")
    return _job_out(job)


@router.post("/push/{job_id}/retry", dependencies=[Depends(require_operator)])
async def retry_push(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """重试失败项：复用同一张 cloud_push_jobs 表，新任务只包含失败条目，不重复推送成功项。"""
    job = await db.get(CloudPushJob, job_id)
    if job is None:
        raise HTTPException(404, "下发任务不存在")
    if not _sees_all(user) and job.created_by != user.username:
        raise HTTPException(403, "无权重试该任务")
    failed = [dict(i) for i in (job.items or []) if i.get("status") == "failed"]
    if not failed:
        raise HTTPException(400, "该任务没有失败项，无需重试")

    file_ids = {i["file_id"] for i in failed}
    files = list(
        (await db.execute(select(CloudFile).where(CloudFile.id.in_(file_ids)))).scalars().all()
    )
    if len(files) != len(file_ids):
        raise HTTPException(400, "部分安装包已被删除，无法重试，请重新选择文件")
    if any(not _can_read(user, f) for f in files):
        raise HTTPException(403, "部分安装包无权访问，无法重试")

    device_ids = sorted({i["device_id"] for i in failed})
    new_id = uuid.uuid4().hex
    items = [{**i, "status": "pending", "error": ""} for i in failed]
    new_job = CloudPushJob(
        id=new_id,
        status="running",
        total=len(items),
        done=0,
        failed=0,
        remote_dir=job.remote_dir,
        items=items,
        created_by=user.username,
    )
    db.add(new_job)
    await db.commit()

    file_rows = [{"id": f.id, "name": f.name, "stored_name": f.stored_name} for f in files]
    asyncio.create_task(_run_push(new_id, file_rows, device_ids, job.remote_dir, user.username))
    await record_audit(
        db,
        user.username,
        "cloud.push.retry",
        target=f"job {job_id}",
        detail={"new_job_id": new_id, "failed_items": len(items)},
    )
    return {"job_id": new_id, "total": len(items), "status": "running"}
