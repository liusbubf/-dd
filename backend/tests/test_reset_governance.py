"""V3.1 回归：测试环境重置的归属校验、冷却、每日配额与审计。

治理只约束平台内的破坏性重置，不涉及任何指纹生成或第三方风控判断。
"""
from __future__ import annotations

import uuid

from conftest import _ensure_user

from app.config import settings


def _create_device(client, headers, name=None):
    payload = {
        "name": name or f"gov-{uuid.uuid4().hex[:8]}",
        "width": 720,
        "height": 1280,
        "dpi": 320,
    }
    r = client.post("/api/devices", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _wipe(client, headers, dev):
    return client.post(
        f"/api/devices/{dev['id']}/reset/wipe-data",
        json={"confirm_name": dev["name"]},
        headers=headers,
    )


def test_policy_endpoint_reports_usage(client, root_headers, monkeypatch):
    headers = _ensure_user(client, root_headers, "gov_policy_user", "operator")
    dev = _create_device(client, headers)
    # 用例断言 next_allowed_at，需要非零冷却；conftest 默认 0 是为其他用例关闭冷却。
    monkeypatch.setattr(settings, "reset_cooldown_seconds", 60)

    r = client.get(f"/api/devices/{dev['id']}/reset-policy", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["daily_quota"] == 1000
    before = body["used_today"]

    assert _wipe(client, headers, dev).status_code == 200

    body = client.get(f"/api/devices/{dev['id']}/reset-policy", headers=headers).json()
    assert body["used_today"] == before + 1
    assert body["remaining_today"] == 1000 - body["used_today"]
    assert body["next_allowed_at"] is not None


def test_cooldown_blocks_second_reset(client, root_headers, monkeypatch):
    headers = _ensure_user(client, root_headers, "gov_cooldown_user", "operator")
    dev = _create_device(client, headers)
    monkeypatch.setattr(settings, "reset_governance_enabled", True)
    monkeypatch.setattr(settings, "reset_cooldown_seconds", 60)
    monkeypatch.setattr(settings, "reset_daily_quota", 1000)

    assert _wipe(client, headers, dev).status_code == 200
    r = _wipe(client, headers, dev)
    assert r.status_code == 429, r.text
    assert int(r.headers["Retry-After"]) >= 1
    assert "冷却" in r.json()["detail"]


def test_daily_quota_blocks_extra_resets(client, root_headers, monkeypatch):
    headers = _ensure_user(client, root_headers, "gov_quota_user", "operator")
    first = _create_device(client, headers)
    second = _create_device(client, headers)
    monkeypatch.setattr(settings, "reset_governance_enabled", True)
    monkeypatch.setattr(settings, "reset_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "reset_daily_quota", 1)

    assert _wipe(client, headers, first).status_code == 200
    r = _wipe(client, headers, second)
    assert r.status_code == 429, r.text
    assert "配额不足" in r.json()["detail"]


def test_non_owner_cannot_reset_snapshot_or_delete(client, root_headers):
    owner = _ensure_user(client, root_headers, "gov_owner", "operator")
    other = _ensure_user(client, root_headers, "gov_other", "operator")
    dev = _create_device(client, owner)

    # 非归属者：策略、重置、快照、删除全部 403
    assert client.get(
        f"/api/devices/{dev['id']}/reset-policy", headers=other
    ).status_code == 403
    assert _wipe(client, other, dev).status_code == 403
    assert client.post(
        f"/api/devices/{dev['id']}/renew", json={"mode": "clear_data"}, headers=other
    ).status_code == 403
    assert client.post(
        f"/api/devices/{dev['id']}/snapshots", json={"name": "x"}, headers=other
    ).status_code == 403
    assert client.delete(f"/api/devices/{dev['id']}", headers=other).status_code == 403

    # 归属者仍可正常操作
    assert _wipe(client, owner, dev).status_code == 200
    assert client.delete(f"/api/devices/{dev['id']}", headers=owner).status_code == 200


def test_batch_renew_rejects_foreign_device(client, root_headers):
    owner = _ensure_user(client, root_headers, "gov_batch_owner", "operator")
    other = _ensure_user(client, root_headers, "gov_batch_other", "operator")
    dev = _create_device(client, owner)

    r = client.post(
        "/api/devices/batch-renew",
        json={"device_ids": [dev["id"]], "mode": "clear_data"},
        headers=other,
    )
    assert r.status_code == 403, r.text


def test_reset_writes_audit_log(client, root_headers):
    headers = _ensure_user(client, root_headers, "gov_audit_user", "operator")
    dev = _create_device(client, headers)
    assert _wipe(client, headers, dev).status_code == 200

    audit = client.get(
        "/api/audit",
        params={"action": "device.reset.wipe_data", "size": 20},
        headers=root_headers,
    )
    assert audit.status_code == 200, audit.text
    assert any(
        item["target"] == f"device:{dev['id']}" for item in audit.json()["items"]
    )
