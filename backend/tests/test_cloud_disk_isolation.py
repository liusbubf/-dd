"""P1-①：云盘用户级隔离 + 下发任务落库。"""
from __future__ import annotations

import asyncio
import time
import uuid

from conftest import _ensure_user


def _upload(client, headers, name="note.txt", content=b"hello cloud"):
    r = client.post(
        "/api/cloud-disk/files",
        files={"file": (name, content, "text/plain")},
        data={"category": "auto"},
        headers=headers,
    )
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


def _other_operator(client, root_headers, suffix):
    return _ensure_user(client, root_headers, f"svc_cloud_{suffix}", "operator")


def test_upload_owner_and_visibility_isolation(client, root_headers, operator_headers, admin_headers):
    other_headers = _other_operator(client, root_headers, "b")

    rec = _upload(client, operator_headers, name="隔离测试.txt")
    assert rec["owner_id"] is not None
    assert rec["is_public"] is False

    own = client.get("/api/cloud-disk/files", headers=operator_headers).json()["files"]
    assert rec["id"] in [f["id"] for f in own]

    others = client.get("/api/cloud-disk/files", headers=other_headers).json()["files"]
    assert rec["id"] not in [f["id"] for f in others], "普通用户不应看到别人的文件"

    admin_view = client.get("/api/cloud-disk/files", headers=admin_headers).json()["files"]
    assert rec["id"] in [f["id"] for f in admin_view], "admin 应看到全部文件"

    assert client.get(f"/api/cloud-disk/files/{rec['id']}/download", headers=other_headers).status_code == 403
    assert client.get(f"/api/cloud-disk/files/{rec['id']}/download", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/cloud-disk/files/{rec['id']}", headers=other_headers).status_code == 403


def test_admin_can_publish_file(client, root_headers, operator_headers):
    other_headers = _other_operator(client, root_headers, "c")
    rec = _upload(client, operator_headers, name="公共文件.txt")

    assert client.get(f"/api/cloud-disk/files/{rec['id']}/download", headers=other_headers).status_code == 403

    r = client.patch(
        f"/api/cloud-disk/files/{rec['id']}", json={"is_public": True}, headers=root_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["is_public"] is True

    visible = client.get("/api/cloud-disk/files", headers=other_headers).json()["files"]
    assert rec["id"] in [f["id"] for f in visible]
    assert client.get(f"/api/cloud-disk/files/{rec['id']}/download", headers=other_headers).status_code == 200

    # 非 admin 不能改公共标记
    assert client.patch(
        f"/api/cloud-disk/files/{rec['id']}", json={"is_public": False}, headers=operator_headers
    ).status_code == 403


def test_push_job_is_persisted_and_listed(client, operator_headers):
    rec = _upload(client, operator_headers, name="push.txt")
    dev = _create_device(client, operator_headers, f"cloud-push-{uuid.uuid4().hex[:6]}")

    r = client.post(
        "/api/cloud-disk/push",
        json={"file_ids": [rec["id"]], "device_ids": [dev["id"]], "remote_dir": "/sdcard/Download"},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    detail = None
    for _ in range(60):
        resp = client.get(f"/api/cloud-disk/push/{job_id}", headers=operator_headers)
        assert resp.status_code == 200, resp.text
        detail = resp.json()
        if detail["status"] in ("done", "partial", "failed"):
            break
        time.sleep(0.05)
    assert detail is not None
    assert detail["status"] in ("done", "partial", "failed"), detail
    assert detail["total"] == 1
    assert len(detail["items"]) == 1
    assert detail["items"][0]["status"] in ("ok", "failed")

    jobs = client.get("/api/cloud-disk/push", headers=operator_headers).json()["jobs"]
    assert job_id in [j["id"] for j in jobs]
    listed = next(j for j in jobs if j["id"] == job_id)
    assert listed["status"] == detail["status"]


def test_running_jobs_marked_interrupted_on_restart(client):
    from app.database import init_db

    job_id = uuid.uuid4().hex
    asyncio.run(_insert_running_job(job_id))
    assert asyncio.run(_status(job_id)) == "running"

    asyncio.run(init_db())

    assert asyncio.run(_status(job_id)) == "interrupted"
    assert asyncio.run(_error(job_id))

    # 收尾，避免污染其它用例的历史列表断言
    asyncio.run(_delete_job(job_id))


async def _insert_running_job(job_id: str) -> None:
    from app.database import SessionLocal
    from app.models import CloudPushJob

    async with SessionLocal() as db:
        db.add(
            CloudPushJob(
                id=job_id,
                status="running",
                total=1,
                done=0,
                failed=0,
                items=[{"device_id": 1, "file_id": 1, "status": "pending", "error": ""}],
                created_by="svc_operator",
            )
        )
        await db.commit()


async def _status(job_id: str) -> str:
    from app.database import SessionLocal
    from app.models import CloudPushJob

    async with SessionLocal() as db:
        job = await db.get(CloudPushJob, job_id)
        assert job is not None
        return job.status


async def _error(job_id: str) -> str:
    from app.database import SessionLocal
    from app.models import CloudPushJob

    async with SessionLocal() as db:
        job = await db.get(CloudPushJob, job_id)
        assert job is not None
        return job.error


async def _delete_job(job_id: str) -> None:
    from app.database import SessionLocal
    from app.models import CloudPushJob

    async with SessionLocal() as db:
        job = await db.get(CloudPushJob, job_id)
        if job is not None:
            await db.delete(job)
            await db.commit()
