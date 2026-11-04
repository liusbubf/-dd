"""V2-3 下载中心接口测试。

覆盖：三类任务生成（CSV / 批量截图 zip / logcat）、走既有云盘下载、删除连带清理、
权限（viewer 不能创建/删除、跨用户不可删）、参数校验（缺设备/超上限/设备不存在）。
"""
from __future__ import annotations

import io
import zipfile

from conftest import _ensure_user


def _make_device(client, headers, name: str) -> int:
    r = client.post(
        "/api/devices",
        json={"name": name, "width": 720, "height": 1280},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _task_ids(client, headers) -> list[int]:
    r = client.get("/api/downloads", headers=headers)
    assert r.status_code == 200, r.text
    return [x["id"] for x in r.json()]


def test_report_csv_download_and_delete(client, operator_headers):
    r = client.post("/api/downloads", json={"kind": "report_csv"}, headers=operator_headers)
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "done"
    assert task["filename"].endswith(".csv")
    assert task["download_url"], task
    assert task["size_bytes"] > 0

    # 下载走既有云盘接口，不是下载中心自造出口
    dl = client.get(task["download_url"], headers=operator_headers)
    assert dl.status_code == 200, dl.text
    assert "名称" in dl.text  # CSV 含中文表头（BOM 不影响 text 匹配）

    assert task["id"] in _task_ids(client, operator_headers)

    d = client.delete(f"/api/downloads/{task['id']}", headers=operator_headers)
    assert d.status_code == 200, d.text
    assert task["id"] not in _task_ids(client, operator_headers)
    # 云盘里的生成物一并删除，下载链接失效
    assert client.get(task["download_url"], headers=operator_headers).status_code == 404


def test_batch_screenshot_zip(client, operator_headers):
    ids = [
        _make_device(client, operator_headers, "dl-shot-a"),
        _make_device(client, operator_headers, "dl-shot-b"),
    ]
    r = client.post(
        "/api/downloads",
        json={"kind": "screenshots", "device_ids": ids},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "done", task
    assert task["filename"].endswith(".zip")
    assert sorted(task["device_ids"]) == sorted(ids)

    dl = client.get(task["download_url"], headers=operator_headers)
    assert dl.status_code == 200, dl.text
    zf = zipfile.ZipFile(io.BytesIO(dl.content))
    names = zf.namelist()
    assert len(names) == 2, names
    assert all(n.startswith("#") for n in names)


def test_logcat_export(client, operator_headers):
    device_id = _make_device(client, operator_headers, "dl-log")
    r = client.post(
        "/api/downloads",
        json={"kind": "logcat", "device_ids": [device_id], "lines": 50},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    task = r.json()
    assert task["status"] == "done", task
    assert task["filename"].endswith(".txt")

    dl = client.get(task["download_url"], headers=operator_headers)
    assert dl.status_code == 200, dl.text
    assert f"=== #{device_id}" in dl.text


def test_download_permissions_and_validation(client, operator_headers, root_headers):
    viewer = _ensure_user(client, root_headers, "svc_viewer_downloads", "viewer")
    r = client.post("/api/downloads", json={"kind": "report_csv"}, headers=viewer)
    assert r.status_code == 403

    # 截图 / 日志必须选设备
    assert (
        client.post("/api/downloads", json={"kind": "screenshots"}, headers=operator_headers).status_code
        == 400
    )
    assert (
        client.post("/api/downloads", json={"kind": "logcat"}, headers=operator_headers).status_code == 400
    )
    # 设备不存在
    assert (
        client.post(
            "/api/downloads",
            json={"kind": "screenshots", "device_ids": [999999]},
            headers=operator_headers,
        ).status_code
        == 404
    )
    # 超过截图上限（31 台）
    assert (
        client.post(
            "/api/downloads",
            json={"kind": "screenshots", "device_ids": list(range(1, 32))},
            headers=operator_headers,
        ).status_code
        == 400
    )


def test_cannot_delete_others_task(client, operator_headers, root_headers):
    other = _ensure_user(client, root_headers, "svc_downloads_other", "operator")
    r = client.post("/api/downloads", json={"kind": "report_csv"}, headers=other)
    assert r.status_code == 200, r.text
    task = r.json()

    # 列表隔离：operator 看不到别人发起的任务
    assert task["id"] not in _task_ids(client, operator_headers)
    # 跨用户删除被拒
    assert client.delete(f"/api/downloads/{task['id']}", headers=operator_headers).status_code == 403

    # 本人可删，admin 也可删
    assert client.delete(f"/api/downloads/{task['id']}", headers=other).status_code == 200
