"""单机控制入参边界（simulator 后端）。"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def device_id(client, operator_headers):
    r = client.post(
        "/api/devices",
        json={"name": "sim-control", "width": 720, "height": 1280},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_tap_out_of_bounds_rejected(client, operator_headers, device_id):
    r = client.post(
        f"/api/devices/{device_id}/control/tap",
        json={"x": 99999, "y": 10},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_tap_ok(client, operator_headers, device_id):
    r = client.post(
        f"/api/devices/{device_id}/control/tap",
        json={"x": 10, "y": 10},
        headers=operator_headers,
    )
    assert r.status_code == 200


def test_open_url_bad_scheme_rejected(client, operator_headers, device_id):
    r = client.post(
        f"/api/devices/{device_id}/control/open_url",
        json={"url": "file:///etc/passwd"},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_text_too_long_rejected(client, operator_headers, device_id):
    r = client.post(
        f"/api/devices/{device_id}/control/text",
        json={"text": "x" * 2001},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_swipe_negative_duration_rejected(client, operator_headers, device_id):
    r = client.post(
        f"/api/devices/{device_id}/control/swipe",
        json={"x1": 0, "y1": 0, "x2": 100, "y2": 100, "duration_ms": -1},
        headers=operator_headers,
    )
    assert r.status_code == 422


def test_control_missing_device_404(client, operator_headers):
    r = client.post(
        "/api/devices/999999/control/tap",
        json={"x": 1, "y": 1},
        headers=operator_headers,
    )
    assert r.status_code == 404
