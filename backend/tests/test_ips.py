"""IP 资源池：CRUD / 真实探测 / 绑定设备。"""
from __future__ import annotations

import socket
import threading

from conftest import _ensure_user


def _create_ip(client, headers, ip="127.0.0.1", port=0, **extra):
    payload = {"ip": ip, "port": port, **extra}
    r = client.post("/api/ips", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _create_device(client, headers, name):
    r = client.post(
        "/api/devices",
        json={"name": name, "width": 720, "height": 1280, "dpi": 320},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_create_and_list(client, operator_headers):
    rec = _create_ip(client, operator_headers, group_name="hk", note="hk exit")
    assert rec["ip"] == "127.0.0.1"
    listed = client.get("/api/ips", headers=operator_headers).json()["items"]
    assert rec["id"] in [x["id"] for x in listed]
    # 口令不回传完整值
    assert rec["password"] == ""


def test_create_requires_operator(client, root_headers):
    viewer = _ensure_user(client, root_headers, "svc_viewer_ip", "viewer")
    r = client.post("/api/ips", json={"ip": "10.1.2.3", "port": 8080}, headers=viewer)
    assert r.status_code == 403


def test_invalid_ip_rejected(client, operator_headers):
    r = client.post("/api/ips", json={"ip": "not-an-ip", "port": 8080}, headers=operator_headers)
    assert r.status_code == 422


def test_probe_success_against_local_tcp(client, operator_headers):
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _accept():
        try:
            srv.settimeout(5)
            conn, _ = srv.accept()
            conn.close()
        except OSError:
            pass

    thread = threading.Thread(target=_accept, daemon=True)
    thread.start()
    try:
        rec = _create_ip(client, operator_headers, port=port)
        r = client.post(f"/api/ips/{rec['id']}/test", headers=operator_headers)
        body = r.json()
        assert r.status_code == 200
        assert body["ok"] is True, body
        assert body["test_result"] == "ok"
        assert "成功" in body["detail"]
    finally:
        thread.join(timeout=2)
        srv.close()


def test_probe_failure_is_honest(client, operator_headers):
    # 取一个刚关闭的端口，探测必须如实返回失败
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()

    rec = _create_ip(client, operator_headers, port=closed_port)
    body = client.post(f"/api/ips/{rec['id']}/test", headers=operator_headers).json()
    assert body["ok"] is False
    assert body["test_result"] == "failed"
    assert "失败" in body["detail"]


def test_probe_without_port(client, operator_headers):
    rec = _create_ip(client, operator_headers, port=0)
    body = client.post(f"/api/ips/{rec['id']}/test", headers=operator_headers).json()
    assert body["ok"] is False
    assert "端口未配置" in body["detail"]


def test_bind_and_unbind_device(client, operator_headers):
    ip = _create_ip(client, operator_headers, ip="10.9.9.9", port=8888, username="u", password="p@ss")
    dev = _create_device(client, operator_headers, "ip-bind-device")

    r = client.post(
        f"/api/ips/{ip['id']}/bind",
        json={"device_id": dev["id"], "apply_to_fingerprint": True},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert detail["ip_id"] == ip["id"]
    assert detail["fingerprint"]["network"]["exit_ip"] == "10.9.9.9"
    assert "10.9.9.9:8888" in detail["fingerprint"]["network"]["proxy"]

    listed = client.get("/api/ips", headers=operator_headers).json()["items"]
    assert next(x for x in listed if x["id"] == ip["id"])["status"] == "in_use"

    r = client.post(
        f"/api/ips/{ip['id']}/unbind", json={"device_id": dev["id"]}, headers=operator_headers
    )
    assert r.status_code == 200
    assert client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()["ip_id"] is None


def test_delete_bound_ip_conflict(client, operator_headers):
    ip = _create_ip(client, operator_headers, ip="10.7.7.7", port=9999)
    dev = _create_device(client, operator_headers, "ip-bound-device")
    client.post(
        f"/api/ips/{ip['id']}/bind", json={"device_id": dev["id"]}, headers=operator_headers
    )
    r = client.delete(f"/api/ips/{ip['id']}", headers=operator_headers)
    assert r.status_code == 409
    assert "绑定" in r.json()["detail"]


def test_update_ip_status(client, operator_headers):
    rec = _create_ip(client, operator_headers, ip="10.3.3.3", port=7000)
    r = client.patch(f"/api/ips/{rec['id']}", json={"status": "disabled", "note": "维护中"}, headers=operator_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "disabled"
