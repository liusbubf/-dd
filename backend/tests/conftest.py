"""pytest 公共夹具：独立 SQLite 库 + simulator 后端 + 预置超管。

所有测试模块共享同一个 app / 引擎，避免多次 lifespan 把 async engine 绑到不同事件循环。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
TEST_DB = BACKEND / "_test_rbac.db"
CLOUD_DISK_DIR = BACKEND / "_test_cloud_disk"
if TEST_DB.exists():
    TEST_DB.unlink()

# 必须在 import app.* 之前设置（config.py 在导入时读取）
os.environ.update(
    {
        "CLOUD_DATABASE_URL": f"sqlite+aiosqlite:///{TEST_DB.as_posix()}",
        "CLOUD_DEVICE_BACKEND": "simulator",
        "CLOUD_ADMIN_USERNAME": "root",
        "CLOUD_ADMIN_PASSWORD": "rootpw123",
        "CLOUD_DEBUG": "true",
        "CLOUD_SEED_USERS": "[]",
        "CLOUD_CLOUD_DISK_DIR": str(CLOUD_DISK_DIR),
        # 自动化测试关闭验证码；验证码专项用例在运行时临时开启 settings.login_captcha_enabled
        "CLOUD_LOGIN_CAPTCHA_ENABLED": "false",
        # 重置治理默认关闭冷却、放大配额；治理专项用例在运行时临时改 settings
        "CLOUD_RESET_COOLDOWN_SECONDS": "0",
        "CLOUD_RESET_DAILY_QUOTA": "1000",
    }
)
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_cloud_disk():
    yield
    import shutil

    shutil.rmtree(CLOUD_DISK_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def root_headers(client):
    r = client.post("/api/auth/login", json={"username": "root", "password": "rootpw123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _ensure_user(client, root_headers, username: str, role: str) -> dict:
    """按需创建测试专用账号并返回其登录头。"""
    existing = {u["username"] for u in client.get("/api/users", headers=root_headers).json()}
    if username not in existing:
        r = client.post(
            "/api/users",
            json={"username": username, "password": "svcPassw0rd", "role": role},
            headers=root_headers,
        )
        assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"username": username, "password": "svcPassw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture(scope="session")
def operator_headers(client, root_headers):
    return _ensure_user(client, root_headers, "svc_operator", "operator")


@pytest.fixture(scope="session")
def admin_headers(client, root_headers):
    return _ensure_user(client, root_headers, "svc_admin", "admin")
