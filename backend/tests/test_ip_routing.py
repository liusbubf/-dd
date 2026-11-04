"""P1-③：IP 选路收敛（绑定优先 → 代理池兜底）。"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.ip_routing import apply_bound_network, current_proxy, proxy_from_record, resolve_proxy
from app.models import Device, IpResource


def _ip(ip="10.9.9.9", port=8888, username="u", password="p@ss", status="available"):
    return IpResource(ip=ip, port=port, username=username, password=password, status=status)


class _StubDB:
    """只实现 resolve_proxy 需要的 db.get。"""

    def __init__(self, rec):
        self.rec = rec
        self.calls = 0

    async def get(self, model, pk):
        self.calls += 1
        return self.rec


def _device(ip_id=None, proxy=None):
    net = {"proxy": proxy} if proxy else {}
    return Device(name="routing", fingerprint={"network": net}, ip_id=ip_id)


def test_proxy_format_requires_port():
    assert proxy_from_record(_ip()) == "http://u:p@ss@10.9.9.9:8888"
    assert proxy_from_record(_ip(port=0)) is None
    assert proxy_from_record(_ip(username="")) == "http://10.9.9.9:8888"
    assert proxy_from_record(None) is None


def test_bound_proxy_wins_even_when_rotating():
    rec = _ip()
    dev = _device(ip_id=1, proxy="http://old:1")
    got = asyncio.run(resolve_proxy(_StubDB(rec), dev, rotate=True))
    assert got == "http://u:p@ss@10.9.9.9:8888", "绑定了就一定用绑定 IP，不能被代理池换掉"


def test_disabled_binding_falls_back_to_pool(monkeypatch):
    monkeypatch.setattr(settings, "proxy_pool", ["http://1.2.3.4:9000"])
    rec = _ip(status="disabled")
    dev = _device(ip_id=1, proxy="http://old:1")
    got = asyncio.run(resolve_proxy(_StubDB(rec), dev, rotate=True))
    assert got == "http://1.2.3.4:9000"


def test_unbound_device_falls_back_to_pool_only_when_rotate(monkeypatch):
    monkeypatch.setattr(settings, "proxy_pool", ["http://5.6.7.8:8080"])
    dev = _device(proxy="http://old:1")
    assert asyncio.run(resolve_proxy(_StubDB(None), dev, rotate=False)) == "http://old:1"
    assert asyncio.run(resolve_proxy(_StubDB(None), dev, rotate=True)) == "http://5.6.7.8:8080"


def test_empty_pool_keeps_current(monkeypatch):
    monkeypatch.setattr(settings, "proxy_pool", [])
    dev = _device(proxy="http://old:1")
    assert asyncio.run(resolve_proxy(_StubDB(None), dev, rotate=True)) == "http://old:1"


def test_apply_bound_network_writes_fingerprint():
    rec = _ip()
    dev = _device(ip_id=1, proxy="http://old:1")
    ok = asyncio.run(apply_bound_network(_StubDB(rec), dev))
    assert ok is True
    assert dev.fingerprint["network"]["exit_ip"] == "10.9.9.9"
    assert dev.fingerprint["network"]["proxy"] == "http://u:p@ss@10.9.9.9:8888"
    assert current_proxy(dev) == "http://u:p@ss@10.9.9.9:8888"


def test_apply_bound_network_ignores_disabled():
    rec = _ip(status="disabled")
    dev = _device(ip_id=1, proxy="http://old:1")
    assert asyncio.run(apply_bound_network(_StubDB(rec), dev)) is False
    assert current_proxy(dev) == "http://old:1"


def _create_ip(client, headers, ip="10.9.9.9", port=8888):
    r = client.post(
        "/api/ips",
        json={"ip": ip, "port": port, "username": "u", "password": "p@ss"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _create_device(client, headers):
    r = client.post(
        "/api/devices",
        json={"name": "routing-device", "width": 720, "height": 1280, "dpi": 320},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_renew_keeps_bound_ip(client, operator_headers):
    ip = _create_ip(client, operator_headers)
    dev = _create_device(client, operator_headers)
    r = client.post(
        f"/api/ips/{ip['id']}/bind",
        json={"device_id": dev["id"], "apply_to_fingerprint": True},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    renew = client.post(
        f"/api/devices/{dev['id']}/renew",
        json={"mode": "hard", "rotate_proxy": True},
        headers=operator_headers,
    )
    assert renew.status_code == 200, renew.text

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert detail["ip_id"] == ip["id"]
    net = detail["fingerprint"]["network"]
    assert net["exit_ip"] == "10.9.9.9"
    assert "10.9.9.9:8888" in net["proxy"]


def test_unbind_clears_network_and_is_idempotent(client, operator_headers):
    ip = _create_ip(client, operator_headers, ip="10.8.8.8", port=9999)
    dev = _create_device(client, operator_headers)
    client.post(
        f"/api/ips/{ip['id']}/bind",
        json={"device_id": dev["id"], "apply_to_fingerprint": True},
        headers=operator_headers,
    )

    r = client.post(
        f"/api/ips/{ip['id']}/unbind", json={"device_id": dev["id"]}, headers=operator_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["already_unbound"] is False

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert detail["ip_id"] is None
    assert "proxy" not in detail["fingerprint"]["network"]
    assert "exit_ip" not in detail["fingerprint"]["network"]
    listed = client.get("/api/ips", headers=operator_headers).json()["items"]
    assert next(x for x in listed if x["id"] == ip["id"])["status"] == "available"

    again = client.post(
        f"/api/ips/{ip['id']}/unbind", json={"device_id": dev["id"]}, headers=operator_headers
    )
    assert again.status_code == 200
    assert again.json()["already_unbound"] is True
