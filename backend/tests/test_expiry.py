"""P1-⑤：到期自动回收（默认关闭，开关可配）。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone


def test_expire_sweep_defaults_to_disabled():
    from app.config import settings

    assert settings.expire_sweep_enabled is False, "默认必须关闭，避免误伤演示环境"
    assert settings.expire_sweep_interval >= 10


def _create_ip(client, headers):
    r = client.post(
        "/api/ips",
        json={"ip": "10.7.7.7", "port": 7777, "username": "u", "password": "p"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_device(client, headers):
    r = client.post(
        "/api/devices",
        json={"name": "expiring-device", "width": 720, "height": 1280, "dpi": 320},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _sweep():
    from app.database import SessionLocal
    from app.expiry import sweep_expired

    async with SessionLocal() as db:
        return await sweep_expired(db)


async def _bind_other_device(device_id: int, ip_id: int) -> None:
    from app.database import SessionLocal
    from app.models import Device

    async with SessionLocal() as db:
        dev = await db.get(Device, device_id)
        assert dev is not None
        dev.ip_id = ip_id
        await db.commit()


def test_ip_not_released_while_other_device_still_bound(client, operator_headers):
    """回收只解绑自己；IP 仍被其它设备占用时不得置回 available（避免误放共享 IP）。"""
    ip = _create_ip(client, operator_headers)
    a = _create_device(client, operator_headers)
    b = _create_device(client, operator_headers)

    bind = client.post(
        f"/api/ips/{ip['id']}/bind",
        json={"device_id": a["id"], "apply_to_fingerprint": True},
        headers=operator_headers,
    )
    assert bind.status_code == 200, bind.text
    asyncio.run(_bind_other_device(b["id"], ip["id"]))

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    patch = client.patch(
        f"/api/devices/{a['id']}", json={"expires_at": past}, headers=operator_headers
    )
    assert patch.status_code == 200, patch.text

    result = asyncio.run(_sweep())
    assert a["id"] in [x["device_id"] for x in result["reclaimed"]], result

    ips = client.get("/api/ips", headers=operator_headers).json()["items"]
    rec = next(x for x in ips if x["id"] == ip["id"])
    assert rec["status"] != "available", "其它设备仍绑定该 IP 时不应释放"

    # 清理共享绑定，避免影响后续用例
    asyncio.run(_bind_other_device(b["id"], None))


def test_expire_reclaims_running_device_and_releases_ip(client, operator_headers):
    ip = _create_ip(client, operator_headers)
    dev = _create_device(client, operator_headers)
    bind = client.post(
        f"/api/ips/{ip['id']}/bind",
        json={"device_id": dev["id"], "apply_to_fingerprint": True},
        headers=operator_headers,
    )
    assert bind.status_code == 200, bind.text

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    patch = client.patch(
        f"/api/devices/{dev['id']}", json={"expires_at": past}, headers=operator_headers
    )
    assert patch.status_code == 200, patch.text

    result = asyncio.run(_sweep())
    assert dev["id"] in [x["device_id"] for x in result["reclaimed"]], result

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert detail["status"] == "stopped"
    assert detail["ip_id"] is None
    assert detail["expires_at"] is None

    ips = client.get("/api/ips", headers=operator_headers).json()["items"]
    assert next(x for x in ips if x["id"] == ip["id"])["status"] == "available"

    # 幂等：已回收的设备不会再次被扫描
    again = asyncio.run(_sweep())
    assert dev["id"] not in [x["device_id"] for x in again["reclaimed"]]
