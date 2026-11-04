"""模拟器后端：在没有 Docker/Redroid 的机器上跑通全部主流程。

它维护一份内存态（每台设备的当前页面、最近一次操作），并用 preview.render_frame
把状态渲染成 iOS 皮肤画面。所有操控/批量/脚本回放都会真实改变这份状态，
因此 Web 多画面预览、单机操控、批量同步、脚本回放在 demo 中都能被肉眼验证。
"""
from __future__ import annotations

import asyncio
import itertools
import json
import time

from ..fingerprint import generate_fingerprint
from ..models import Device
from ..preview import render_frame
from .base import (
    DeviceBackend,
    Provisioned,
    RenewProgress,
    RenewResult,
    SnapshotResult,
    pick_proxy,
)

_port_seq = itertools.count(6001)


class SimulatorBackend(DeviceBackend):
    name = "simulator"

    # 进程内共享的运行态：device_id -> {"last_action": str}
    _runtime: dict[int, dict] = {}

    def __init__(self) -> None:
        # backend_ref -> 状态副本；仅用于本地演示，进程重启即失效
        self._snapshots: dict[str, dict] = {}

    async def create(self, device: Device) -> Provisioned:
        await asyncio.sleep(0.02)  # 模拟拉起耗时
        port = next(_port_seq)
        return Provisioned(backend_ref=f"sim-{device.id}", adb_port=port)

    async def start(self, device: Device) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = "started"

    async def stop(self, device: Device) -> None:
        self._runtime.pop(device.id, None)

    async def destroy(self, device: Device) -> None:
        self._runtime.pop(device.id, None)

    async def check_health(self, device: Device) -> bool | None:
        return True

    async def renew(
        self,
        device: Device,
        *,
        mode: str = "hard",
        rotate_proxy: bool = False,
        keep_url: bool = False,
        progress: RenewProgress | None = None,
    ) -> RenewResult:
        if mode not in ("hard", "clear_data"):
            raise ValueError(f"不支持的换机模式: {mode}")

        started = time.monotonic()

        async def _p(phase: str) -> None:
            if progress is not None:
                await progress(phase)

        old_fp = device.fingerprint or {}
        old_seed = old_fp.get("seed")
        old_url = device.current_url

        await _p("stopping")
        await _p("wiping")
        self._runtime.pop(device.id, None)

        changed = False
        if mode == "hard":
            await _p("fingerprint")
            proxy = old_fp.get("network", {}).get("proxy")
            if rotate_proxy:
                proxy = pick_proxy(proxy)
            device.fingerprint = generate_fingerprint(
                proxy=proxy,
                mode=old_fp.get("mode", "commercial"),
                region=old_fp.get("region"),
            )
            changed = device.fingerprint.get("seed") != old_seed
        elif rotate_proxy:
            # 仅清数据：身份不变，但可以换出口代理
            fp = dict(old_fp)
            network = dict(fp.get("network", {}))
            network["proxy"] = pick_proxy(network.get("proxy"))
            fp["network"] = network
            device.fingerprint = fp

        device.current_url = old_url if keep_url else None

        await _p("creating")
        prov = await self.create(device)
        device.backend_ref = prov.backend_ref
        device.adb_port = prov.adb_port
        await _p("booting")
        await self.start(device)
        if keep_url and old_url:
            await self.open_url(device, old_url)
        await _p("url")

        return RenewResult(
            device_id=device.id,
            mode=mode,
            fingerprint_changed=changed,
            proxy=device.fingerprint.get("network", {}).get("proxy"),
            current_url=device.current_url,
            duration_s=round(time.monotonic() - started, 3),
        )

    async def snapshot(self, device: Device, snapshot_id: int) -> SnapshotResult:
        ref = f"sim-snap-{device.id}-{snapshot_id}"
        state = {
            "current_url": device.current_url,
            "runtime": dict(self._runtime.get(device.id, {})),
        }
        self._snapshots[ref] = state
        return SnapshotResult(ref, len(json.dumps(state).encode("utf-8")))

    async def restore_snapshot(self, device: Device, backend_ref: str) -> None:
        state = self._snapshots.get(backend_ref)
        if state is None:
            raise RuntimeError("快照数据不存在（模拟器快照不跨进程持久化）")
        device.current_url = state.get("current_url")
        self._runtime[device.id] = dict(state.get("runtime") or {})
        self._runtime[device.id]["last_action"] = "snapshot restored"

    async def delete_snapshot(self, device: Device, backend_ref: str) -> None:
        self._snapshots.pop(backend_ref, None)

    async def open_url(self, device: Device, url: str) -> None:
        device.current_url = url
        self._runtime.setdefault(device.id, {})["last_action"] = f"open {url}"

    async def tap(self, device: Device, x: int, y: int) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"tap({x},{y})"

    async def swipe(self, device: Device, x1, y1, x2, y2, duration_ms) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"swipe({x1},{y1})->({x2},{y2})"

    async def input_text(self, device: Device, text: str, append: bool = False) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = (
            f"text({text!r}, append={append})"
        )

    async def key(self, device: Device, key: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"key({key})"

    async def install(self, device: Device, apk_url: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"install({apk_url})"

    async def screenshot(self, device: Device) -> str:
        # V6：演示页统一渲染安卓桌面（含状态栏/图标网格/dock/手势条/演示角标），
        # 不再展示 Example Domain 浏览器页；真机/Redroid 仍走真实 screencap。
        return render_frame(device.name, None, device.fingerprint or {},
                            screen="android", theme=getattr(device, "skin", "ios") or "ios")

    async def list_apps(self, device: Device) -> list[str]:
        # demo 用：返回一份稳定的常见应用包名列表（可在设备详情页展示已装应用）
        return [
            "com.android.chrome",
            "com.android.launcher3",
            "com.android.settings",
            "com.android.vending",
            "com.android.webview",
            "org.chromium.webview_shell",
        ]

    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        last = self._runtime.get(device.id, {}).get("last_action", "idle")
        return [
            f"07-17 10:00:0{i} I ActivityManager: [sim:{device.name}] tick {i} last={last}"
            for i in range(1, 9)
        ]

    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        device.width, device.height, device.dpi = width, height, dpi
        self._runtime.setdefault(device.id, {})["last_action"] = f"display {width}x{height}@{dpi}"

    async def uninstall_app(self, device: Device, package: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"uninstall {package}"

    async def launch_app(self, device: Device, package: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"launch {package}"

    async def stop_app(self, device: Device, package: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"stop {package}"

    async def clear_app(self, device: Device, package: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"clear {package}"

    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        return [
            {"name": "Download", "is_dir": True},
            {"name": "Pictures", "is_dir": True},
            {"name": "DCIM", "is_dir": True},
            {"name": "demo.txt", "is_dir": False},
            {"name": "screenshot.png", "is_dir": False},
        ]

    async def push_file(self, device: Device, local_path: str, remote_path: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"push -> {remote_path}"

    async def pull_file(self, device: Device, remote_path: str, local_path: str) -> bool:
        with open(local_path, "w") as f:
            f.write(f"[sim] {device.name} pulled {remote_path}\n")
        return True

    async def delete_file(self, device: Device, remote_path: str) -> None:
        self._runtime.setdefault(device.id, {})["last_action"] = f"rm {remote_path}"
