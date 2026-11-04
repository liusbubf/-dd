"""设备文件互传（PC-104 / §7.2.4）：浏览 / 上传 / 下载 / 删除设备文件。

与既有 devices / device_detail / logs 路由共用 /devices 前缀：FastAPI 允许多个路由挂同一
前缀，只要子路径不同即可。这里使用 /{id}/files 系列子路径，不与其它路由冲突。

文件读写由编排后端提供（redroid 走 adb push/pull/ls/rm，simulator 返回演示数据）：
  - services.backend.list_files(device, path)           -> list[{"name","is_dir"}]
  - services.backend.push_file(device, local, remote)   本地文件 -> 设备
  - services.backend.pull_file(device, remote, local)   设备文件 -> 本地（bool 成功与否）
  - services.backend.delete_file(device, remote)        删除设备文件
"""
from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from ..auth import get_current_user
from ..rbac import require_operator
from ..database import get_db
from ..deps import get_device_or_404 as _get_or_404
from .. import services

router = APIRouter(prefix="/devices", tags=["files"], dependencies=[Depends(get_current_user)])

# 禁止删除的关键目录：避免误删设备根 / 外置存储根导致数据丢失。
_PROTECTED = {"", "/", "/sdcard", "/sdcard/"}


def _safe_remote_path(path: str) -> str:
    """设备侧路径必须绝对、且不含 .. ——防止借相对路径跳到未授权目录。"""
    p = (path or "").strip()
    if not p.startswith("/"):
        raise HTTPException(400, "设备路径必须是绝对路径")
    if ".." in p.split("/"):
        raise HTTPException(400, "设备路径不允许包含 ..")
    return p


@router.get("/{device_id}/files")
async def list_files(
    device_id: int,
    path: str = Query("/sdcard/", max_length=512, description="要浏览的设备目录"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = await _get_or_404(db, device_id)
    path = _safe_remote_path(path)
    items = await services.backend.list_files(device, path)
    return {"path": path, "items": items}


@router.post("/{device_id}/files/upload", dependencies=[Depends(require_operator)])
async def upload_file(
    device_id: int,
    file: UploadFile = File(...),
    remote_dir: str = Form("/sdcard/", max_length=512),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = await _get_or_404(db, device_id)
    remote_dir = _safe_remote_path(remote_dir)
    # 只取文件名本身：浏览器可能带 ../ 或 Windows 反斜杠，直接拼路径可写到任意设备目录
    filename = os.path.basename((file.filename or "").replace("\\", "/")).strip()
    if not filename or filename in (".", ".."):
        raise HTTPException(400, "非法文件名")
    # 先把上传流落到本地临时文件，再交给编排后端 push 到设备。
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp_path = tmp.name
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            tmp.write(chunk)
    remote_path = remote_dir.rstrip("/") + "/" + filename
    try:
        await services.backend.push_file(device, tmp_path, remote_path)
    finally:
        os.remove(tmp_path)
    return {"ok": True, "name": filename}


@router.get("/{device_id}/files/download")
async def download_file(
    device_id: int,
    path: str = Query(..., max_length=512, description="要下载的设备文件绝对路径"),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    device = await _get_or_404(db, device_id)
    path = _safe_remote_path(path)
    # 先 pull 到本地临时文件，再作为附件回传；响应结束后后台清理临时文件。
    fd, tmp_path = tempfile.mkstemp()
    os.close(fd)
    ok = await services.backend.pull_file(device, path, tmp_path)
    if not ok:
        os.remove(tmp_path)
        raise HTTPException(404, "文件下载失败")
    return FileResponse(
        tmp_path,
        filename=os.path.basename(path),
        background=BackgroundTask(os.remove, tmp_path),
    )


@router.delete("/{device_id}/files", dependencies=[Depends(require_operator)])
async def delete_file(
    device_id: int,
    path: str = Query(..., max_length=512, description="要删除的设备文件 / 目录绝对路径"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    device = await _get_or_404(db, device_id)
    path = _safe_remote_path(path)
    if path.strip() in _PROTECTED:
        raise HTTPException(400, "禁止删除该目录")
    await services.backend.delete_file(device, path)
    return {"ok": True}
