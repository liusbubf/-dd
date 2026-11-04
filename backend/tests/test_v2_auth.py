"""V2-1 登录增强：图形验证码一次性 / 失败锁定 / 通用错误文案 / 上次登录提示。"""
from __future__ import annotations

import uuid

from app.config import settings
from app.routers import auth as auth_mod


def _issue(client):
    cap = client.get("/api/auth/captcha").json()
    code = auth_mod._captchas[cap["captcha_id"]]["code"]
    return cap, code


def _login(client, username, password, captcha):
    return client.post(
        "/api/auth/login",
        json={
            "username": username,
            "password": password,
            "captcha_id": captcha["captcha_id"],
            "captcha_code": captcha["captcha_code"],
        },
    )


def test_captcha_required_and_one_time(client, monkeypatch):
    monkeypatch.setattr(settings, "login_captcha_enabled", True)

    # 不带验证码 => 400（不是 401，避免误判为账号问题）
    r = client.post("/api/auth/login", json={"username": "root", "password": "rootpw123"})
    assert r.status_code == 400
    assert "验证码" in r.json()["detail"]

    cap, code = _issue(client)
    # 第一次：验证码正确但密码错误 => 401 通用文案，验证码被消费
    first = _login(client, "root", "wrong-password", {**cap, "captcha_code": code})
    assert first.status_code == 401
    assert first.json()["detail"] == "用户名或密码错误"

    # 第二次复用同一验证码 => 已被消费
    replay = _login(client, "root", "rootpw123", {**cap, "captcha_code": code})
    assert replay.status_code == 400
    assert "已过期" in replay.json()["detail"]


def test_login_returns_last_login_info(client, monkeypatch, root_headers):
    monkeypatch.setattr(settings, "login_captcha_enabled", True)
    cap, code = _issue(client)
    r = _login(client, "root", "rootpw123", {**cap, "captcha_code": code})
    assert r.status_code == 200, r.text
    data = r.json()
    # root 在 session 夹具里已经登录过一次，因此这次一定能拿到上次登录信息
    assert data["last_login"] is not None
    assert data["last_login"]["at"]
    assert data["last_login"]["ip"]
    # TestClient 的 client host 可能是 "testclient"（非 IP），此时按“取不到归属”降级
    assert data["last_login"]["location"] in (None, "本机", "内网")


def test_not_found_and_bad_password_use_same_message(client, monkeypatch):
    monkeypatch.setattr(settings, "login_captcha_enabled", True)
    cap, code = _issue(client)
    missing = _login(client, f"no_such_{uuid.uuid4().hex[:8]}", "whatever", {**cap, "captcha_code": code})
    assert missing.status_code == 401
    assert missing.json()["detail"] == "用户名或密码错误"


def test_login_failure_lockout(client, monkeypatch):
    monkeypatch.setattr(settings, "login_captcha_enabled", True)
    username = f"lockme_{uuid.uuid4().hex[:8]}"
    for _ in range(4):
        cap, code = _issue(client)
        r = _login(client, username, "bad-pass", {**cap, "captcha_code": code})
        assert r.status_code == 401, r.text
    # 第 5 次失败触发锁定，直接返回 429
    cap, code = _issue(client)
    locked = _login(client, username, "bad-pass", {**cap, "captcha_code": code})
    assert locked.status_code == 429
    assert int(locked.headers.get("Retry-After", "0")) >= 1
