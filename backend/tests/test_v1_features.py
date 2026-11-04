"""V1：清屏锁 / fresh 截图限流 / 推送失败重试。"""
from __future__ import annotations

import asyncio
import time
import uuid

from conftest import _ensure_user


def _create_device(client, headers, name=None):
    r = client.post(
        "/api/devices",
        json={"name": name or f"v1-{uuid.uuid4().hex[:6]}", "width": 720, "height": 1280, "dpi": 320},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_unlock_simulator_success_and_permission(client, root_headers, operator_headers):
    dev = _create_device(client, operator_headers)
    r = client.post(f"/api/devices/{dev['id']}/unlock", headers=operator_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    viewer = _ensure_user(client, root_headers, f"v1_viewer_{uuid.uuid4().hex[:6]}", "viewer")
    assert client.post(f"/api/devices/{dev['id']}/unlock", headers=viewer).status_code == 403


def test_fresh_screenshot_rate_limited_per_user_and_device(client, operator_headers):
    dev = _create_device(client, operator_headers)
    url = f"/api/devices/{dev['id']}/screenshot"

    # 10 秒窗口内允许 2 次 fresh
    assert client.get(url, params={"fresh": "true"}, headers=operator_headers).status_code == 200
    assert client.get(url, params={"fresh": "true"}, headers=operator_headers).status_code == 200

    third = client.get(url, params={"fresh": "true"}, headers=operator_headers)
    assert third.status_code == 429, third.text
    assert int(third.headers.get("Retry-After", "0")) >= 1

    # 非 fresh 走帧缓存，不受限流影响
    assert client.get(url, headers=operator_headers).status_code == 200


def _upload(client, headers, name="retry.apk"):
    r = client.post(
        "/api/cloud-disk/files",
        files={"file": (name, b"fake apk bytes", "application/vnd.android.package-archive")},
        data={"category": "apk"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _insert_failed_job(job_id: str, file_id: str, device_id: int, created_by: str) -> None:
    from app.database import SessionLocal
    from app.models import CloudPushJob

    async with SessionLocal() as db:
        db.add(
            CloudPushJob(
                id=job_id,
                status="failed",
                total=1,
                done=0,
                failed=1,
                remote_dir="/sdcard/Download",
                items=[{
                    "device_id": device_id,
                    "device_name": "retry-target",
                    "file_id": file_id,
                    "file_name": "retry.apk",
                    "status": "failed",
                    "error": "模拟失败",
                }],
                created_by=created_by,
            )
        )
        await db.commit()


async def _delete_job(job_id: str) -> None:
    from app.database import SessionLocal
    from app.models import CloudPushJob

    async with SessionLocal() as db:
        job = await db.get(CloudPushJob, job_id)
        if job is not None:
            await db.delete(job)
            await db.commit()


def test_retry_failed_items_creates_new_job(client, root_headers, operator_headers):
    dev = _create_device(client, operator_headers)
    file_rec = _upload(client, operator_headers)
    job_id = uuid.uuid4().hex
    asyncio.run(_insert_failed_job(job_id, file_rec["id"], dev["id"], "svc_operator"))

    r = client.post(f"/api/cloud-disk/push/{job_id}/retry", headers=operator_headers)
    assert r.status_code == 200, r.text
    new_id = r.json()["job_id"]
    assert new_id != job_id
    assert r.json()["total"] == 1

    detail = None
    for _ in range(60):
        resp = client.get(f"/api/cloud-disk/push/{new_id}", headers=operator_headers)
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        if detail["status"] in ("done", "partial", "failed"):
            break
        time.sleep(0.05)
    assert detail is not None
    assert detail["total"] == 1
    assert detail["items"][0]["status"] in ("ok", "failed")

    # 没有失败项时拒绝重试
    if detail["failed"] == 0:
        assert client.post(f"/api/cloud-disk/push/{new_id}/retry", headers=operator_headers).status_code == 400

    # viewer 无重试权限
    viewer = _ensure_user(client, root_headers, f"v1_retry_viewer_{uuid.uuid4().hex[:6]}", "viewer")
    assert client.post(f"/api/cloud-disk/push/{job_id}/retry", headers=viewer).status_code == 403

    asyncio.run(_delete_job(job_id))
    asyncio.run(_delete_job(new_id))
