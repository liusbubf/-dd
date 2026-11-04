"""脚本 CRUD 与回放（simulator 后端）。"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def script_id(client, operator_headers):
    r = client.post(
        "/api/scripts",
        json={
            "name": "t-script",
            "description": "pytest",
            "steps": [
                {"action": "tap", "params": {"x": 10, "y": 10}},
                {"action": "wait", "params": {"ms": 50}},
            ],
        },
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_list_scripts(client, operator_headers, script_id):
    ids = [s["id"] for s in client.get("/api/scripts", headers=operator_headers).json()]
    assert script_id in ids


def test_get_script(client, operator_headers, script_id):
    r = client.get(f"/api/scripts/{script_id}", headers=operator_headers)
    assert r.status_code == 200
    assert len(r.json()["steps"]) == 2


def test_create_empty_name_rejected(client, operator_headers):
    r = client.post(
        "/api/scripts",
        json={"name": "", "steps": []},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_run_script(client, operator_headers, script_id):
    dev = client.post(
        "/api/devices",
        json={"name": "sim-script-run"},
        headers=operator_headers,
    ).json()
    r = client.post(
        f"/api/scripts/{script_id}/run",
        json={"device_ids": [dev["id"]]},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["results"]) == 1


def test_run_empty_devices_rejected(client, operator_headers, script_id):
    r = client.post(
        f"/api/scripts/{script_id}/run",
        json={"device_ids": []},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_delete_script(client, operator_headers, script_id):
    r = client.delete(f"/api/scripts/{script_id}", headers=operator_headers)
    assert r.status_code == 200
    assert client.get(f"/api/scripts/{script_id}", headers=operator_headers).status_code == 404
