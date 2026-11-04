"""V2 侧项 B：多控坐标按设备实际分辨率换算。

验证两件事：
1. `_scale` / `_source_dims` 的纯函数行为（含缺失分辨率时回落基准）；
2. `/api/batch/tap|swipe` 端到端：主控真实像素 + 主控分辨率 → 目标设备按自己分辨率落点。
"""
from __future__ import annotations

from types import SimpleNamespace

from app import services
from app.routers.batch import _scale, _source_dims
from app.schemas import BatchTap


def _make_device(client, headers, name: str, w: int, h: int) -> int:
    r = client.post(
        "/api/devices",
        json={"name": name, "width": w, "height": h},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _last_action(device_id: int) -> str:
    return services.backend._runtime.get(device_id, {}).get("last_action", "")


def test_scale_uses_source_resolution():
    target = SimpleNamespace(width=720, height=1280)
    assert _scale(target, 1080, 1920, 1080, 1920) == (720, 1280)
    # 主控 720×1280 的 (540,960) 折算到 1080×1920 目标
    assert _scale(SimpleNamespace(width=1080, height=1920), 540, 960, 720, 1280) == (810, 1440)


def test_source_dims_fallback_when_missing():
    body = BatchTap(device_ids=[1], x=100, y=200)
    assert _source_dims(body) == (1080, 1920)
    assert body.source_width is None and body.source_height is None

    body2 = BatchTap(device_ids=[1], x=100, y=200, source_width=720, source_height=1280)
    assert _source_dims(body2) == (720, 1280)


def test_batch_tap_uses_master_resolution(client, operator_headers):
    target = _make_device(client, operator_headers, "coord-target-1080", 1080, 1920)

    r = client.post(
        "/api/batch/tap",
        json={
            "device_ids": [target],
            "x": 540,
            "y": 960,
            "source_width": 720,
            "source_height": 1280,
        },
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] == 1
    assert _last_action(target) == "tap(810,1440)"


def test_batch_tap_falls_back_to_baseline(client, operator_headers):
    target = _make_device(client, operator_headers, "coord-target-fallback", 1080, 1920)

    r = client.post(
        "/api/batch/tap",
        json={"device_ids": [target], "x": 540, "y": 960},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    # 缺主控分辨率 → 按 1080×1920 基准，原样落到目标
    assert _last_action(target) == "tap(540,960)"


def test_batch_swipe_scales_both_points(client, operator_headers):
    target = _make_device(client, operator_headers, "coord-swipe", 720, 1280)

    r = client.post(
        "/api/batch/swipe",
        json={
            "device_ids": [target],
            "x1": 1080,
            "y1": 100,
            "x2": 200,
            "y2": 1200,
            "duration_ms": 300,
            "source_width": 1080,
            "source_height": 1920,
        },
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] == 1
    # 720/1080 = 0.666..., 1280/1920 = 0.666...
    assert _last_action(target) == "swipe(720,66)->(133,800)"
