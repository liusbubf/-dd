"""V5 回归：分辨率/DPI 切换、恢复原始值、投屏渲染质量。

覆盖：
- 非法分辨率（超总像素、宽高比过极端）返回 422，且不改动设备；
- simulator 后端切换成功，设备记录与运行时状态同步，写审计；
- 恢复原始分辨率/密度回到创建时的值；
- 后端切换失败时回滚并返回 502，设备记录保持原值；
- 渲染质量 low/medium/high 可切换并落库，非法值 422；
- render_quality_params 生成正确的 scrcpy 参数。
"""
from __future__ import annotations

import uuid

import pytest

from app import services
from app.orchestrator.base import RENDER_QUALITY_PRESETS, render_quality_params


def _create_device(client, headers, width=720, height=1280, dpi=320):
    payload = {
        "name": f"v5-{uuid.uuid4().hex[:8]}",
        "width": width,
        "height": height,
        "dpi": dpi,
    }
    r = client.post("/api/devices", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_invalid_resolution_returns_422(client, operator_headers):
    dev = _create_device(client, operator_headers)

    # 总像素超过 2160×3840
    r = client.post(
        f"/api/devices/{dev['id']}/control/display",
        json={"width": 2160, "height": 3840, "dpi": 480},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/devices/{dev['id']}/control/display",
        json={"width": 2160, "height": 4000, "dpi": 480},
        headers=operator_headers,
    )
    assert r.status_code == 422, r.text
    assert "分辨率过大" in r.text

    # 宽高比超出 1:4 ~ 4:1
    r = client.post(
        f"/api/devices/{dev['id']}/control/display",
        json={"width": 320, "height": 3840, "dpi": 320},
        headers=operator_headers,
    )
    assert r.status_code == 422, r.text
    assert "宽高比" in r.text

    # 非法请求后设备保持上一步合法值
    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert detail["width"] == 2160
    assert detail["height"] == 3840


def test_display_change_and_audit(client, root_headers, operator_headers):
    dev = _create_device(client, operator_headers)
    r = client.post(
        f"/api/devices/{dev['id']}/control/display",
        json={"width": 1080, "height": 1920, "dpi": 480},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["width"] == 1080
    assert body["height"] == 1920
    assert body["dpi"] == 480
    assert body["restart_required"] is False  # simulator 直接改内存态

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert (detail["width"], detail["height"], detail["dpi"]) == (1080, 1920, 480)
    # 原始值保持创建时的参数，供恢复使用
    assert (detail["orig_width"], detail["orig_height"], detail["orig_dpi"]) == (720, 1280, 320)

    audit = client.get(
        "/api/audit",
        params={"action": "device.display.change", "size": 20},
        headers=root_headers,
    )
    assert audit.status_code == 200, audit.text
    assert any(item["target"] == f"device:{dev['id']}" for item in audit.json()["items"])


def test_reset_display_restores_original(client, operator_headers):
    dev = _create_device(client, operator_headers)
    r = client.post(
        f"/api/devices/{dev['id']}/control/display",
        json={"width": 1440, "height": 2560, "dpi": 560},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"/api/devices/{dev['id']}/control/display/reset",
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["width"], r.json()["height"], r.json()["dpi"]) == (720, 1280, 320)

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert (detail["width"], detail["height"], detail["dpi"]) == (720, 1280, 320)


def test_display_change_rolls_back_on_backend_failure(
    client, operator_headers, monkeypatch
):
    dev = _create_device(client, operator_headers)
    calls: list[tuple[int, int, int]] = []

    async def failing_set_display(device, width, height, dpi):
        calls.append((width, height, dpi))
        raise RuntimeError("adb: device offline")

    monkeypatch.setattr(services.backend, "set_display", failing_set_display)

    r = client.post(
        f"/api/devices/{dev['id']}/control/display",
        json={"width": 1080, "height": 1920, "dpi": 480},
        headers=operator_headers,
    )
    assert r.status_code == 502, r.text
    assert "回滚" in r.json()["detail"]
    # 第一次用新值，回滚时用原值
    assert calls == [(1080, 1920, 480), (720, 1280, 320)]

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert (detail["width"], detail["height"], detail["dpi"]) == (720, 1280, 320)


def test_render_quality_switch_and_validation(client, operator_headers):
    dev = _create_device(client, operator_headers)

    r = client.post(
        f"/api/devices/{dev['id']}/control/render-quality",
        json={"quality": "high"},
        headers=operator_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["quality"] == "high"

    detail = client.get(f"/api/devices/{dev['id']}", headers=operator_headers).json()
    assert detail["render_quality"] == "high"

    r = client.post(
        f"/api/devices/{dev['id']}/control/render-quality",
        json={"quality": "ultra"},
        headers=operator_headers,
    )
    assert r.status_code == 422, r.text


def test_render_quality_params():
    assert render_quality_params("low") == {
        "max_fps": 15,
        "bitrate": 2_000_000,
        "i_frame_interval": 2,
    }
    assert render_quality_params("medium")["max_fps"] == 30
    assert render_quality_params("high")["max_fps"] == 60
    # 未知值回落 medium
    assert render_quality_params("unknown") == RENDER_QUALITY_PRESETS["medium"]
