"""设备生命周期（simulator 后端）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _create_device(client, headers, name="t-device"):
    r = client.post(
        "/api/devices",
        json={"name": name, "width": 720, "height": 1280, "dpi": 320},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_create_and_list(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-create")
    assert dev["status"] in ("stopped", "starting", "running")
    names = [d["name"] for d in client.get("/api/devices", headers=operator_headers).json()]
    assert "sim-create" in names


def test_get_detail(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-detail")
    r = client.get(f"/api/devices/{dev['id']}", headers=operator_headers)
    assert r.status_code == 200
    assert r.json()["id"] == dev["id"]


def test_rename(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-rename")
    r = client.patch(
        f"/api/devices/{dev['id']}",
        json={"name": "sim-renamed"},
        headers=operator_headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "sim-renamed"


def test_invalid_group_rejected(client, operator_headers):
    r = client.post(
        "/api/devices",
        json={"name": "sim-bad-group", "group_id": 0},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_missing_device_404(client, operator_headers):
    r = client.get("/api/devices/999999", headers=operator_headers)
    assert r.status_code == 404


def test_batch_delete_empty_rejected(client, operator_headers):
    r = client.post("/api/devices/batch-delete", json={"device_ids": []}, headers=operator_headers)
    assert r.status_code == 422


def test_delete_device(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-delete")
    r = client.delete(f"/api/devices/{dev['id']}", headers=operator_headers)
    assert r.status_code == 200
    assert client.get(f"/api/devices/{dev['id']}", headers=operator_headers).status_code == 404


def test_set_expiry_and_remaining(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-expiry")
    target = datetime.now(timezone.utc) + timedelta(hours=30)
    r = client.patch(
        f"/api/devices/{dev['id']}",
        json={"expires_at": target.isoformat()},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["expires_at"]
    assert body["remaining_seconds"] is not None
    # 允许几秒误差
    assert 29 * 3600 < body["remaining_seconds"] <= 30 * 3600
    assert body["is_expiring_soon"] is False


def test_expiring_list_and_soon_flag(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-expiring")
    soon = datetime.now(timezone.utc) + timedelta(hours=2)
    r = client.patch(
        f"/api/devices/{dev['id']}",
        json={"expires_at": soon.isoformat()},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_expiring_soon"] is True
    listed = client.get("/api/devices/expiring?within_hours=24", headers=operator_headers).json()
    assert listed["count"] >= 1
    assert dev["id"] in [d["id"] for d in listed["devices"]]


def test_clear_expiry(client, operator_headers):
    dev = _create_device(client, operator_headers, "sim-expiry-clear")
    target = datetime.now(timezone.utc) + timedelta(days=5)
    client.patch(
        f"/api/devices/{dev['id']}", json={"expires_at": target.isoformat()}, headers=operator_headers
    )
    r = client.patch(
        f"/api/devices/{dev['id']}", json={"expires_at": None}, headers=operator_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["expires_at"] is None
    assert r.json()["remaining_seconds"] is None

