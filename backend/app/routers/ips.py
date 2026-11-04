"""IP 资源池：CRUD + 真实连通性探测 + 绑定到云机（写入指纹网络信息）。"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from ..auth import get_current_user
from ..database import get_db
from ..ip_routing import proxy_from_record
from ..models import Device, IpResource, User
from ..rbac import record_audit, require_operator
from ..schemas import IpBindRequest, IpResourceCreate, IpResourceOut, IpResourceUpdate

_log = logging.getLogger("app.ips")

router = APIRouter(prefix="/ips", tags=["ips"], dependencies=[Depends(get_current_user)])

# 探测超时：3 秒连不上就判失败，不假装成功
TEST_TIMEOUT = 3.0


def _to_out(record: IpResource) -> dict:
    return IpResourceOut.model_validate(record).model_dump(mode="json")


@router.get("")
async def list_ips(
    status: str | None = Query(None, max_length=16),
    group_name: str | None = Query(None, max_length=64),
    q: str | None = Query(None, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict:
    stmt = select(IpResource).order_by(IpResource.id.desc())
    if status:
        stmt = stmt.where(IpResource.status == status)
    if group_name:
        stmt = stmt.where(IpResource.group_name == group_name)
    if q:
        stmt = stmt.where(IpResource.ip.ilike(f"%{q}%"))
    rows = list((await db.execute(stmt)).scalars().all())
    return {"items": [_to_out(r) for r in rows]}


@router.post("", response_model=IpResourceOut, dependencies=[Depends(require_operator)])
async def create_ip(
    body: IpResourceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IpResource:
    record = IpResource(**body.model_dump())
    db.add(record)
    await db.commit()
    await db.refresh(record)
    await record_audit(db, user.username, "ip.create", target=f"{record.ip}:{record.port}")
    return record


@router.patch("/{ip_id}", response_model=IpResourceOut, dependencies=[Depends(require_operator)])
async def update_ip(
    ip_id: int,
    body: IpResourceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> IpResource:
    record = await db.get(IpResource, ip_id)
    if record is None:
        raise HTTPException(404, "IP 资源不存在")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    await db.commit()
    await db.refresh(record)
    await record_audit(db, user.username, "ip.update", target=f"{record.ip}:{record.port}")
    return record


@router.delete("/{ip_id}", dependencies=[Depends(require_operator)])
async def delete_ip(
    ip_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    record = await db.get(IpResource, ip_id)
    if record is None:
        raise HTTPException(404, "IP 资源不存在")
    bound = list(
        (await db.execute(select(Device).where(Device.ip_id == ip_id))).scalars().all()
    )
    if bound:
        raise HTTPException(409, f"仍有 {len(bound)} 台设备绑定该 IP，请先解绑")
    target = f"{record.ip}:{record.port}"
    await db.delete(record)
    await db.commit()
    await record_audit(db, user.username, "ip.delete", target=target)
    return {"ok": True, "id": ip_id}


def _tcp_probe(ip: str, port: int) -> tuple[bool, str]:
    """真实 TCP 连接探测（同步实现，由调用方放进线程池）。"""
    import socket

    try:
        with socket.create_connection((ip, port), timeout=TEST_TIMEOUT):
            return True, f"TCP {ip}:{port} 连接成功"
    except OSError as exc:
        return False, f"TCP {ip}:{port} 连接失败：{exc}"[:300]


@router.post("/{ip_id}/test", dependencies=[Depends(require_operator)])
async def test_ip(
    ip_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    record = await db.get(IpResource, ip_id)
    if record is None:
        raise HTTPException(404, "IP 资源不存在")
    if record.port <= 0:
        # 没有端口无法做 TCP 探测，如实返回失败，不伪造成功
        ok, detail = False, "端口未配置（port=0），无法做 TCP 探测"
    else:
        ok, detail = await asyncio.to_thread(_tcp_probe, record.ip, record.port)
    record.test_result = "ok" if ok else "failed"
    record.test_detail = detail
    record.last_tested_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(record)
    await record_audit(
        db, user.username, "ip.test", target=f"{record.ip}:{record.port}", detail={"ok": ok}
    )
    return {"id": record.id, "ok": ok, "test_result": record.test_result, "detail": detail}


@router.post("/{ip_id}/bind", dependencies=[Depends(require_operator)])
async def bind_ip(
    ip_id: int,
    body: IpBindRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    record = await db.get(IpResource, ip_id)
    if record is None:
        raise HTTPException(404, "IP 资源不存在")
    if record.status == "disabled":
        raise HTTPException(400, "该 IP 已停用，不能绑定")
    device = await db.get(Device, body.device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    if device.ip_id and device.ip_id != ip_id:
        raise HTTPException(409, "该设备已绑定其他 IP，请先解绑")

    device.ip_id = ip_id
    record.status = "in_use"
    if body.apply_to_fingerprint:
        # 与一键新机的网络字段保持一致：exit_ip + proxy（格式与 ip_routing 一致）
        fp = dict(device.fingerprint or {})
        net = dict(fp.get("network") or {})
        net["exit_ip"] = record.ip
        proxy = proxy_from_record(record)
        if proxy:
            net["proxy"] = proxy
        else:
            net.pop("proxy", None)
        fp["network"] = net
        device.fingerprint = fp
        flag_modified(device, "fingerprint")
    await db.commit()
    await record_audit(
        db,
        user.username,
        "ip.bind",
        target=f"{record.ip}:{record.port} -> {device.name}",
        detail={"device_id": device.id},
    )
    _log.info("ip.bind ip=%s device=%s by=%s", record.ip, device.id, user.username)
    return {"ok": True, "ip_id": ip_id, "device_id": device.id}


@router.post("/{ip_id}/unbind", dependencies=[Depends(require_operator)])
async def unbind_ip(
    ip_id: int,
    body: IpBindRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    record = await db.get(IpResource, ip_id)
    if record is None:
        raise HTTPException(404, "IP 资源不存在")
    device = await db.get(Device, body.device_id)
    if device is None:
        raise HTTPException(404, "设备不存在")
    if device.ip_id != ip_id:
        # 幂等：重复解绑（或该设备本就没绑这个 IP）直接返回成功，不报错
        return {"ok": True, "ip_id": ip_id, "device_id": device.id, "already_unbound": True}

    device.ip_id = None
    # 解绑后回落：清掉指纹里的绑定网络信息，后续新机按代理池选路
    fp = dict(device.fingerprint or {})
    net = dict(fp.get("network") or {})
    net.pop("proxy", None)
    net.pop("exit_ip", None)
    fp["network"] = net
    device.fingerprint = fp
    flag_modified(device, "fingerprint")

    still_bound = list(
        (await db.execute(select(Device).where(Device.ip_id == ip_id))).scalars().all()
    )
    if not still_bound:
        record.status = "available"
    await db.commit()
    await record_audit(db, user.username, "ip.unbind", target=f"{record.ip} <- {device.name}")
    return {
        "ok": True,
        "ip_id": ip_id,
        "device_id": device.id,
        "already_unbound": False,
    }
