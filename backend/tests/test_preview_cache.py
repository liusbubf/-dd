"""P1-②：preview_hub 帧缓存 TTL 与无订阅者停止采集。"""
from __future__ import annotations

import asyncio
import time

from app.preview_hub import FRAME_TTL, hub


def _create_device(client, headers):
    r = client.post(
        "/api/devices",
        json={"name": "preview-cache", "width": 720, "height": 1280, "dpi": 320},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_screenshot_uses_frame_cache(client, operator_headers):
    hub._frames.clear()
    dev = _create_device(client, operator_headers)

    first = client.get(f"/api/devices/{dev['id']}/screenshot", headers=operator_headers)
    assert first.status_code == 200, first.text
    assert first.json()["cached"] is False
    frame = first.json()["frame"]
    assert frame

    second = client.get(f"/api/devices/{dev['id']}/screenshot", headers=operator_headers)
    assert second.json()["cached"] is True
    assert second.json()["frame"] == frame

    # fresh=true 强制重新截图，不走缓存
    third = client.get(
        f"/api/devices/{dev['id']}/screenshot", params={"fresh": "true"}, headers=operator_headers
    )
    assert third.json()["cached"] is False


def test_frame_ttl_expires_and_sweep_trims():
    hub._frames.clear()
    hub._frames[1] = (time.time() - FRAME_TTL - 1, "stale")
    assert hub.cached_frame(1) is None

    hub.store_frame(2, "fresh")
    assert hub.cached_frame(2) == "fresh"
    # sweep 会清掉过期帧，只保留新帧
    assert hub.frame_cache_size == 1


def test_collect_stops_without_subscribers():
    hub._subs.clear()
    # 无订阅者时采集协程应立即返回，不空转打 adb
    asyncio.run(asyncio.wait_for(hub._collect(999999), timeout=1.0))


def test_drop_cancels_collect_task():
    asyncio.run(_drop_cycle())


async def _drop_cycle() -> None:
    task = asyncio.create_task(asyncio.sleep(10))
    hub._subs[7] = {}
    hub._tasks[7] = task
    hub._drop(7)
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert task.cancelled()
    assert hub.task_count == 0
    assert 7 not in hub._subs
