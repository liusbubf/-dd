"""设备同步：从服务器自动同步设备列表到本地。

作为从节点，定期轮询服务器 API：
- 服务器新增设备 → 本地自动创建 + ADB 连接
- 服务器设备更新 → 本地同步指纹/皮肤/名称/当前页面/分组
- 服务器设备删除 → 本地标记为 stopped（不直接删，防误删）

配置项（.env）：
    CLOUD_SYNC_SERVER=http://<SYNC_HOST>:8000/api
    CLOUD_SYNC_INTERVAL=30
    CLOUD_SYNC_USERNAME=admin
    CLOUD_SYNC_PASSWORD=admin123
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import select

from .auth import get_current_user
from .rbac import require_admin
from .config import settings
from .database import SessionLocal
from .models import Device, DeviceStatus, Group
from .ws_manager import manager

_log = logging.getLogger("sync")

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[Depends(get_current_user)])

# 同步状态（供 API 查询）
_last_sync: dict = {
    "ok": False,
    "ts": None,
    "msg": "未同步",
    "created": 0,
    "updated": 0,
    "offline": 0,
    "server": "",
    "interval": 0,
}


async def _adb_connect(port: int) -> None:
    """通过 ADB 连接到远程设备（异步，不阻塞事件循环）。"""
    try:
        serial = f"{settings.redroid_host}:{port}"
        proc = await asyncio.create_subprocess_exec(
            settings.adb_path, "connect", serial,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), timeout=10)
        _log.info("ADB 连接: %s", serial)
    except Exception as e:
        _log.warning("ADB 连接失败 port=%s: %s", port, e)


async def _login(client: httpx.AsyncClient) -> str:
    """登录服务器，返回 access_token。"""
    resp = await client.post(
        f"{settings.sync_server}/auth/login",
        json={"username": settings.sync_username, "password": settings.sync_password},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def _sync_groups(client: httpx.AsyncClient, headers: dict) -> dict[int | None, int | None]:
    """同步分组：按名称匹配，服务器分组在本地不存在时自动创建。

    返回 服务器group_id → 本地group_id 的映射。
    """
    resp = await client.get(f"{settings.sync_server}/groups", headers=headers)
    resp.raise_for_status()
    server_groups = resp.json()

    # 获取本地已有分组，按名称建索引
    async with SessionLocal() as db:
        local_groups = list((await db.execute(select(Group).order_by(Group.id))).scalars().all())
        local_by_name = {g.name: g for g in local_groups}

        # 映射：服务器 group_id → 本地 group_id
        # None 表示"未分组"，直接映射
        port_map: dict[int | None, int | None] = {None: None}

        for sg in server_groups:
            sg_id = sg["id"]
            sg_name = sg["name"]
            if sg_name in local_by_name:
                port_map[sg_id] = local_by_name[sg_name].id
            else:
                # 本地不存在，创建
                new_group = Group(name=sg_name, parent_id=None)
                db.add(new_group)
                await db.flush()
                port_map[sg_id] = new_group.id
                _log.info("同步新分组: %s (本地id=%s)", sg_name, new_group.id)

        await db.commit()
        return port_map


async def _sync_once() -> None:
    """执行一次同步。"""
    async with httpx.AsyncClient(timeout=15) as client:
        token = await _login(client)
        headers = {"Authorization": f"Bearer {token}"}

        # 获取服务器设备列表（含完整指纹）
        resp = await client.get(f"{settings.sync_server}/devices", headers=headers)
        resp.raise_for_status()
        server_devices = resp.json()

        # 同步分组，拿到 服务器group_id → 本地group_id 映射
        group_map = await _sync_groups(client, headers)

        # 按 adb_port 建索引
        server_by_port: dict[int, dict] = {}
        for d in server_devices:
            port = d.get("adb_port")
            if port:
                server_by_port[port] = d

        created = 0
        updated = 0
        offline = 0

        async with SessionLocal() as db:
            local_devices = list(
                (await db.execute(select(Device).order_by(Device.id))).scalars().all()
            )
            local_by_port: dict[int, Device] = {
                d.adb_port: d for d in local_devices if d.adb_port
            }

            # 1. 新增：服务器有、本地没有
            for port, srv in server_by_port.items():
                if port not in local_by_port:
                    srv_group_id = srv.get("group_id")
                    local_group_id = group_map.get(srv_group_id)

                    dev = Device(
                        name=srv.get("name", f"设备-{port}"),
                        group_id=local_group_id,
                        adb_port=port,
                        backend_ref=srv.get("backend_ref"),
                        status=DeviceStatus.running,
                        width=srv.get("width", 720),
                        height=srv.get("height", 1280),
                        dpi=srv.get("dpi", 320),
                        skin=srv.get("skin", ""),
                        current_url=srv.get("current_url"),
                        fingerprint=srv.get("fingerprint") or {},
                    )
                    db.add(dev)
                    await db.flush()
                    created += 1
                    _log.info("同步新设备: %s (port=%s, id=%s)", dev.name, port, dev.id)
                    await _adb_connect(port)
                    await manager.broadcast(
                        {"type": "device_created", "device_id": dev.id, "name": dev.name}
                    )

            # 2. 更新：两边都有，强制同步所有字段
            for port, srv in server_by_port.items():
                if port in local_by_port:
                    dev = local_by_port[port]
                    changed = False

                    # 指纹
                    srv_fp = srv.get("fingerprint") or {}
                    if srv_fp and srv_fp != (dev.fingerprint or {}):
                        dev.fingerprint = srv_fp
                        changed = True

                    # 皮肤（强制覆盖，保留服务器原始值，空字符串表示"原生安卓"）
                    srv_skin = srv.get("skin")
                    if srv_skin is None:
                        srv_skin = ""
                    if srv_skin != dev.skin:
                        dev.skin = srv_skin
                        changed = True

                    # 当前页面（强制覆盖，包括 None）
                    srv_url = srv.get("current_url")
                    if srv_url != dev.current_url:
                        dev.current_url = srv_url
                        changed = True

                    # 名称
                    srv_name = srv.get("name", "")
                    if srv_name and srv_name != dev.name:
                        dev.name = srv_name
                        changed = True

                    # 分组（按名称匹配后的本地 group_id）
                    srv_group_id = srv.get("group_id")
                    local_group_id = group_map.get(srv_group_id)
                    if local_group_id != dev.group_id:
                        dev.group_id = local_group_id
                        changed = True

                    if changed:
                        updated += 1
                        await manager.broadcast(
                            {"type": "device_updated", "device_id": dev.id}
                        )

            # 3. 离线：本地有、服务器没有
            for port, dev in local_by_port.items():
                if port not in server_by_port:
                    if dev.status != DeviceStatus.stopped:
                        dev.status = DeviceStatus.stopped
                        offline += 1
                        _log.info("设备在服务器已删除，标记离线: %s (port=%s)", dev.name, port)
                        await manager.broadcast(
                            {"type": "device_updated", "device_id": dev.id}
                        )

            await db.commit()

        _last_sync.update({
            "ok": True,
            "ts": datetime.now(timezone.utc).isoformat(),
            "msg": f"同步完成: 新增{created} 更新{updated} 离线{offline}",
            "created": created,
            "updated": updated,
            "offline": offline,
            "server": settings.sync_server,
            "interval": settings.sync_interval,
        })

        if created or updated or offline:
            _log.info("同步完成: 新增=%d 更新=%d 离线=%d", created, updated, offline)


async def device_sync_loop():
    """设备同步主循环（后台协程）。

    在 main.py 的 lifespan 中通过 asyncio.create_task 启动。
    配置 CLOUD_SYNC_SERVER 后自动运行，未配置则跳过。
    """
    if not settings.sync_server:
        _log.info("未配置 CLOUD_SYNC_SERVER，设备同步已禁用")
        return

    _log.info(
        "设备同步已启动: 间隔=%ss 服务器=%s",
        settings.sync_interval,
        settings.sync_server,
    )

    while True:
        try:
            await _sync_once()
        except httpx.ConnectError:
            _last_sync.update({"ok": False, "msg": "无法连接服务器"})
            _log.warning("设备同步: 无法连接服务器 %s", settings.sync_server)
        except httpx.HTTPStatusError as e:
            _last_sync.update({"ok": False, "msg": f"服务器返回 {e.response.status_code}"})
            _log.warning("设备同步: 服务器返回 %s", e.response.status_code)
        except Exception as e:
            _last_sync.update({"ok": False, "msg": f"同步失败: {e}"})
            _log.warning("设备同步失败: %s", e)
        await asyncio.sleep(settings.sync_interval)


@router.get("/status")
async def sync_status() -> dict:
    """查看同步状态。"""
    return _last_sync


@router.post("/run", dependencies=[Depends(require_admin)])
async def sync_run_now() -> dict:
    """手动触发一次同步。"""
    await _sync_once()
    return _last_sync
