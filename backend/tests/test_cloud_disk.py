"""云盘与云端下发（simulator 后端）。"""
from __future__ import annotations

import time

from conftest import _ensure_user


def _upload(client, headers, name="demo.txt", content=b"hello cloud-disk", category="auto"):
    r = client.post(
        "/api/cloud-disk/files",
        files={"file": (name, content, "text/plain")},
        data={"category": category},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_categories(client, operator_headers):
    r = client.get("/api/cloud-disk/categories", headers=operator_headers)
    assert r.status_code == 200
    keys = [c["key"] for c in r.json()["categories"]]
    assert "image" in keys and "apk" in keys and "other" in keys
    assert r.json()["quota_bytes"] > 0


def test_upload_list_download_delete(client, operator_headers):
    rec = _upload(client, operator_headers, "note.txt", b"hello cloud disk")
    assert rec["category"] == "document"
    assert rec["size_bytes"] == 16

    listed = client.get("/api/cloud-disk/files", headers=operator_headers).json()
    assert rec["id"] in [f["id"] for f in listed["files"]]
    assert listed["used_bytes"] >= 16

    dl = client.get(f"/api/cloud-disk/files/{rec['id']}/download", headers=operator_headers)
    assert dl.status_code == 200
    assert dl.content == b"hello cloud disk"

    r = client.delete(f"/api/cloud-disk/files/{rec['id']}", headers=operator_headers)
    assert r.status_code == 200
    assert client.get(f"/api/cloud-disk/files/{rec['id']}/download", headers=operator_headers).status_code == 404


def test_upload_requires_operator(client, root_headers):
    viewer = _ensure_user(client, root_headers, "svc_viewer_disk", "viewer")
    r = client.post(
        "/api/cloud-disk/files",
        files={"file": ("v.txt", b"nope", "text/plain")},
        data={"category": "auto"},
        headers=viewer,
    )
    assert r.status_code == 403


def test_upload_unknown_category(client, operator_headers):
    r = client.post(
        "/api/cloud-disk/files",
        files={"file": ("x.bin", b"x", "application/octet-stream")},
        data={"category": "hack"},
        headers=operator_headers,
    )
    assert r.status_code == 400


def test_push_to_device_and_poll(client, operator_headers):
    rec = _upload(client, operator_headers, "push.txt", b"push me")
    dev = client.post(
        "/api/devices",
        json={"name": "cloud-push-device", "width": 720, "height": 1280, "dpi": 320},
        headers=operator_headers,
    ).json()

    r = client.post(
        "/api/cloud-disk/push",
        json={"file_ids": [rec["id"]], "device_ids": [dev["id"]], "remote_dir": "/sdcard/Download"},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert r.json()["total"] == 1

    job = None
    for _ in range(40):
        jr = client.get(f"/api/cloud-disk/push/{job_id}", headers=operator_headers)
        assert jr.status_code == 200
        job = jr.json()
        if job["status"] in ("done", "partial", "failed"):
            break
        time.sleep(0.05)
    assert job["status"] == "done"
    assert job["done"] == 1 and job["failed"] == 0
    assert job["items"][0]["status"] == "ok"


def test_push_rejects_relative_remote_dir(client, operator_headers):
    rec = _upload(client, operator_headers, "rel.txt", b"x")
    dev = client.post(
        "/api/devices",
        json={"name": "cloud-push-bad", "width": 720, "height": 1280, "dpi": 320},
        headers=operator_headers,
    ).json()
    r = client.post(
        "/api/cloud-disk/push",
        json={"file_ids": [rec["id"]], "device_ids": [dev["id"]], "remote_dir": "../sdcard"},
        headers=operator_headers,
    )
    assert r.status_code == 400


def test_push_missing_file(client, operator_headers):
    dev = client.post(
        "/api/devices",
        json={"name": "cloud-push-missing", "width": 720, "height": 1280, "dpi": 320},
        headers=operator_headers,
    ).json()
    r = client.post(
        "/api/cloud-disk/push",
        json={"file_ids": [999999], "device_ids": [dev["id"]], "remote_dir": "/sdcard"},
        headers=operator_headers,
    )
    assert r.status_code == 400
