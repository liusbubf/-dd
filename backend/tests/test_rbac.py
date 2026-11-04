"""RBAC 与自助改密的回归测试（夹具见 conftest.py）。

运行（在 backend 目录）：
    python -m pytest tests/test_rbac.py -q

覆盖：
- 4 个角色 × 代表性读/写/管理接口
- 任何已登录用户可改自己的口令，但改不了别人
- 入参边界（空设备列表、非法 URL）返回 422 而不是 500
"""
from __future__ import annotations

import pytest


def login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"登录失败 {username}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="module")
def ctx(client):
    root = login(client, "root", "rootpw123")
    users = {}
    for name, role in (
        ("t_admin", "admin"),
        ("t_operator", "operator"),
        ("t_viewer", "viewer"),
    ):
        r = client.post(
            "/api/users",
            json={"username": name, "password": "Passw0rd123", "role": role},
            headers=root,
        )
        assert r.status_code == 200, f"创建 {name} 失败: {r.text}"
        users[role] = {"id": r.json()["id"], "headers": login(client, name, "Passw0rd123")}
    return {"root": root, "users": users}


# ---------------- 读接口：viewer 起可用 ----------------
def test_viewer_can_read_devices(client, ctx):
    r = client.get("/api/devices", headers=ctx["users"]["viewer"]["headers"])
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_viewer_can_read_alerts(client, ctx):
    r = client.get("/api/alerts/current", headers=ctx["users"]["viewer"]["headers"])
    assert r.status_code == 200


# ---------------- 写接口：operator 起可用 ----------------
def test_viewer_cannot_create_device(client, ctx):
    r = client.post(
        "/api/devices",
        json={"name": "viewer-should-fail"},
        headers=ctx["users"]["viewer"]["headers"],
    )
    assert r.status_code == 403


def test_operator_can_create_device(client, ctx):
    r = client.post(
        "/api/devices",
        json={"name": "rbac-op-device", "width": 720, "height": 1280},
        headers=ctx["users"]["operator"]["headers"],
    )
    assert r.status_code == 200, r.text
    ctx["device_id"] = r.json()["id"]


def test_viewer_cannot_control_device(client, ctx):
    r = client.post(
        f"/api/devices/{ctx['device_id']}/start",
        headers=ctx["users"]["viewer"]["headers"],
    )
    assert r.status_code == 403


def test_operator_can_control_device(client, ctx):
    r = client.post(
        f"/api/devices/{ctx['device_id']}/start",
        headers=ctx["users"]["operator"]["headers"],
    )
    assert r.status_code == 200, r.text


def test_viewer_cannot_batch(client, ctx):
    r = client.post(
        "/api/batch/open_url",
        json={"device_ids": [ctx["device_id"]], "url": "https://example.com"},
        headers=ctx["users"]["viewer"]["headers"],
    )
    assert r.status_code == 403


def test_operator_can_batch(client, ctx):
    r = client.post(
        "/api/batch/open_url",
        json={"device_ids": [ctx["device_id"]], "url": "https://example.com"},
        headers=ctx["users"]["operator"]["headers"],
    )
    assert r.status_code == 200, r.text


def test_empty_batch_rejected(client, ctx):
    r = client.post(
        "/api/batch/open_url",
        json={"device_ids": [], "url": "https://example.com"},
        headers=ctx["users"]["operator"]["headers"],
    )
    assert r.status_code == 422


def test_bad_url_rejected(client, ctx):
    r = client.post(
        "/api/batch/open_url",
        json={"device_ids": [ctx["device_id"]], "url": "javascript:alert(1)"},
        headers=ctx["users"]["operator"]["headers"],
    )
    assert r.status_code == 422


# ---------------- 管理接口：admin 起可用 ----------------
def test_viewer_cannot_list_users(client, ctx):
    r = client.get("/api/users", headers=ctx["users"]["viewer"]["headers"])
    assert r.status_code == 403


def test_operator_cannot_list_users(client, ctx):
    r = client.get("/api/users", headers=ctx["users"]["operator"]["headers"])
    assert r.status_code == 403


def test_admin_can_list_users(client, ctx):
    r = client.get("/api/users", headers=ctx["users"]["admin"]["headers"])
    assert r.status_code == 200
    assert any(u["username"] == "root" for u in r.json())


def test_operator_cannot_read_audit(client, ctx):
    r = client.get("/api/audit", headers=ctx["users"]["operator"]["headers"])
    assert r.status_code == 403


def test_admin_can_read_audit(client, ctx):
    r = client.get("/api/audit", headers=ctx["users"]["admin"]["headers"])
    assert r.status_code == 200


def test_admin_cannot_create_admin(client, ctx):
    r = client.post(
        "/api/users",
        json={"username": "should_fail_admin", "password": "Passw0rd123", "role": "admin"},
        headers=ctx["users"]["admin"]["headers"],
    )
    assert r.status_code == 400


def test_admin_cannot_delete_superadmin(client, ctx):
    root_id = client.get("/api/users", headers=ctx["users"]["admin"]["headers"]).json()[0]["id"]
    r = client.delete(f"/api/users/{root_id}", headers=ctx["users"]["admin"]["headers"])
    assert r.status_code == 400


# ---------------- 自助改密 ----------------
def test_self_password_wrong_old(client, ctx):
    r = client.patch(
        "/api/users/me/password",
        json={"old_password": "wrong-old", "new_password": "NewPassw0rd"},
        headers=ctx["users"]["viewer"]["headers"],
    )
    assert r.status_code == 400


def test_viewer_can_change_own_password(client, ctx):
    r = client.patch(
        "/api/users/me/password",
        json={"old_password": "Passw0rd123", "new_password": "NewPassw0rd99"},
        headers=ctx["users"]["viewer"]["headers"],
    )
    assert r.status_code == 200, r.text
    # 新口令可登录
    login(client, "t_viewer", "NewPassw0rd99")


def test_viewer_cannot_change_others(client, ctx):
    admin_id = ctx["users"]["admin"]["id"]
    r = client.patch(
        f"/api/users/{admin_id}",
        json={"password": "Hacked123"},
        headers=ctx["users"]["viewer"]["headers"],
    )
    assert r.status_code == 403


def test_operator_cannot_change_others(client, ctx):
    admin_id = ctx["users"]["admin"]["id"]
    r = client.patch(
        f"/api/users/{admin_id}",
        json={"password": "Hacked123"},
        headers=ctx["users"]["operator"]["headers"],
    )
    assert r.status_code == 403


def test_admin_can_reset_operator_password(client, ctx):
    op_id = ctx["users"]["operator"]["id"]
    r = client.patch(
        f"/api/users/{op_id}",
        json={"password": "ResetPassw0rd"},
        headers=ctx["users"]["admin"]["headers"],
    )
    assert r.status_code == 200
    login(client, "t_operator", "ResetPassw0rd")
