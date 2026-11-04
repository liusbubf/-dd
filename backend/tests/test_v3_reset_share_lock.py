"""V3 回归：重置两入口 / 同租户共享 / 投屏层遮罩语义。

覆盖：
- 恢复到快照：无快照 409、设备名校验 400、有快照成功回滚；
- 清空数据（保留设备）：设备名校验、真实走 clear_data、设备记录与归属保留；
- 共享：归属者可共享/撤销、非归属者 403、撤销后列表立即不可见、共享不提升写权限；
- 锁：screen-lock / unlock 仅写审计，不计为服务端占用。
"""
from __future__ import annotations

import uuid

from conftest import _ensure_user


def _create_device(client, headers, name=None):
    payload = {
        "name": name or f"v3-{uuid.uuid4().hex[:8]}",
        "width": 720,
        "height": 1280,
        "dpi": 320,
    }
    r = client.post("/api/devices", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _user_id(client, root_headers, username):
    users = client.get("/api/users", headers=root_headers).json()
    return next(u["id"] for u in users if u["username"] == username)


def test_reset_restore_latest_requires_snapshot_and_confirm(client, operator_headers):
    dev = _create_device(client, operator_headers)

    # 设备名不匹配：二次确认失败，不能进入快照逻辑
    r = client.post(
        f"/api/devices/{dev['id']}/reset/restore-snapshot",
        json={"confirm_name": "wrong"},
        headers=operator_headers,
    )
    assert r.status_code == 400, r.text

    # 没有可用快照：明确 409，不做假成功
    r = client.post(
        f"/api/devices/{dev['id']}/reset/restore-snapshot",
        json={"confirm_name": dev["name"]},
        headers=operator_headers,
    )
    assert r.status_code == 409, r.text
    assert "没有可用快照" in r.json()["detail"]


def test_reset_restore_latest_success(client, root_headers, operator_headers):
    dev = _create_device(client, operator_headers)
    r = client.post(
        f"/api/devices/{dev['id']}/control/open_url",
        json={"url": "https://before.example.com"},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    snap = client.post(
        f"/api/devices/{dev['id']}/snapshots",
        json={"name": "v3-snap"},
        headers=operator_headers,
    )
    assert snap.status_code == 200, snap.text

    # 快照后再改状态，恢复应回到快照时刻
    r = client.post(
        f"/api/devices/{dev['id']}/control/open_url",
        json={"url": "https://after.example.com"},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/devices/{dev['id']}/reset/restore-snapshot",
        json={"confirm_name": dev["name"]},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_url"] == "https://before.example.com"

    # 审计落库
    audit = client.get(
        "/api/audit",
        params={"action": "device.reset.restore_snapshot", "size": 20},
        headers=root_headers,
    )
    assert audit.status_code == 200, audit.text
    assert any(
        item["target"] == f"device:{dev['id']}" for item in audit.json()["items"]
    )


def test_reset_wipe_data_keeps_device_and_binding_meta(client, operator_headers):
    dev = _create_device(client, operator_headers)
    assert dev["owner_id"] is not None

    # 先制造一些运行态
    r = client.post(
        f"/api/devices/{dev['id']}/control/tap",
        json={"x": 100, "y": 200},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    # 名称不匹配：拒绝，不做任何擦除
    r = client.post(
        f"/api/devices/{dev['id']}/reset/wipe-data",
        json={"confirm_name": "wrong"},
        headers=operator_headers,
    )
    assert r.status_code == 400, r.text

    r = client.post(
        f"/api/devices/{dev['id']}/reset/wipe-data",
        json={"confirm_name": dev["name"]},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["id"] == dev["id"]
    assert data["name"] == dev["name"]
    assert data["owner_id"] == dev["owner_id"]
    assert data["renew_count"] == dev["renew_count"] + 1
    assert data["current_url"] is None

    from app import services

    assert services.backend._runtime[dev["id"]]["last_action"] == "started"


def test_share_grant_revoke_and_visibility(client, root_headers, operator_headers):
    dev = _create_device(client, operator_headers)
    viewer_headers = _ensure_user(client, root_headers, "v3_share_viewer", "viewer")
    viewer_id = _user_id(client, root_headers, "v3_share_viewer")

    # 未共享前：非归属者 operator 的列表看不到
    other_op = _ensure_user(client, root_headers, "v3_other_operator", "operator")
    names = [d["name"] for d in client.get("/api/devices", headers=other_op).json()]
    assert dev["name"] not in names

    # 非归属者不能共享
    r = client.post(
        f"/api/devices/{dev['id']}/shares",
        json={"user_id": viewer_id},
        headers=other_op,
    )
    assert r.status_code == 403, r.text

    # 归属者共享成功后，viewer 列表可见（viewer 级可见性）
    r = client.post(
        f"/api/devices/{dev['id']}/shares",
        json={"user_id": viewer_id},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    share_id = r.json()["id"]
    assert r.json()["username"] == "v3_share_viewer"
    names = [d["name"] for d in client.get("/api/devices", headers=viewer_headers).json()]
    assert dev["name"] in names

    # 重复共享：409
    r = client.post(
        f"/api/devices/{dev['id']}/shares",
        json={"user_id": viewer_id},
        headers=operator_headers,
    )
    assert r.status_code == 409, r.text

    # 撤销后立即失效
    r = client.delete(
        f"/api/devices/{dev['id']}/shares/{share_id}", headers=operator_headers
    )
    assert r.status_code == 200, r.text
    names = [d["name"] for d in client.get("/api/devices", headers=viewer_headers).json()]
    assert dev["name"] not in names

    # 共享不提升写权限：viewer 仍不能控制设备
    r = client.post(
        f"/api/devices/{dev['id']}/control/tap",
        json={"x": 10, "y": 10},
        headers=viewer_headers,
    )
    assert r.status_code == 403, r.text


def test_admin_can_share_any_device(client, root_headers, admin_headers):
    owner_headers = _ensure_user(client, root_headers, "v3_admin_owner", "operator")
    dev = _create_device(client, owner_headers)
    viewer_id = _user_id(client, root_headers, "v3_share_viewer")
    r = client.post(
        f"/api/devices/{dev['id']}/shares",
        json={"user_id": viewer_id},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text


def test_screen_lock_is_client_overlay_only(client, operator_headers):
    dev = _create_device(client, operator_headers)
    r = client.post(f"/api/devices/{dev['id']}/screen-lock", headers=operator_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["locked"] is True
    assert body["scope"] == "client_overlay"
    assert "不是服务端占用" in body["note"]

    r = client.post(f"/api/devices/{dev['id']}/unlock", headers=operator_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["locked"] is False
    assert body["scope"] == "client_overlay"
    assert "不涉及服务端占用" in body["note"]
