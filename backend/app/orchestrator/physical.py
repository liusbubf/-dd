"""实体机后端：通过 ADB 纳管真实手机（USB / 无线调试）。

定位是 QA 设备池：远程操控 + 清理数据（等效恢复出厂），用于兼容性测试、
演示与回归验证。**不做任何硬件标识篡改** —— IMEI / 序列号 / Android ID
一律保持设备原值，也拒绝通过 `hard` 模式生成新身份。
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import shlex
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

from ..config import settings
from ..models import Device
from .base import (
    DeviceBackend,
    DeviceCommandError,
    DeviceUnreachable,
    Provisioned,
    RenewProgress,
    RenewResult,
    render_quality_params,
)
from .redroid import (
    _KEYCODES,
    _STATUSBAR_CMDS,
    _adb_server_up,
    _escape_shell_text,
    _is_transport_error,
    _run,
)

_RECONNECT_POLLS = 24
_RECONNECT_INTERVAL = 0.25
_BOOT_POLLS = 360  # 180s

_ADB_DEVICE_LINE_RE = re.compile(r"^(\S+)\s+(\S+)(?:\s+(.*))?$")
_WM_SIZE_RE = re.compile(r"(\d+)\s*x\s*(\d+)")
_WM_DENSITY_RE = re.compile(r"(\d+)")


async def _run_with_timeout(timeout: float, *args: str) -> tuple[int, bytes, bytes]:
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            list(args),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or b"", (e.stderr or b"") + b"\nadb command timeout"
    except OSError as e:
        return 127, b"", f"adb 无法启动（{settings.adb_path}）：{e}".encode()
    return proc.returncode or 0, proc.stdout, proc.stderr


def _is_tcp_serial(serial: str) -> bool:
    return ":" in serial


def _parse_devices(output: bytes) -> list[dict]:
    devices: list[dict] = []
    for raw in output.decode("utf-8", "ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices"):
            continue
        m = _ADB_DEVICE_LINE_RE.match(line)
        if not m:
            continue
        serial, state, tail = m.group(1), m.group(2), m.group(3) or ""
        info = {"serial": serial, "state": state, "model": "", "product": "", "device": ""}
        for token in tail.split():
            if ":" not in token:
                continue
            key, _, value = token.partition(":")
            if key in info:
                info[key] = value
        devices.append(info)
    return devices


async def list_adb_devices() -> list[dict]:
    """扫描当前 ADB server 下可见的实体机。"""
    await _adb_server_up()
    code, out, err = await _run(settings.adb_path, "devices", "-l")
    if code != 0:
        detail = err.decode(errors="replace").strip() or f"adb 退出码 {code}"
        raise DeviceCommandError(0, "扫描 ADB 设备", detail)
    return _parse_devices(out)


async def _probe_shell(serial: str, *args: str) -> str:
    code, out, err = await _run(settings.adb_path, "-s", serial, *args)
    if code != 0:
        raise DeviceCommandError(
            0,
            f"读取设备信息（{args[-1] if args else ''}）",
            err.decode(errors="replace").strip() or f"adb 退出码 {code}",
        )
    return out.decode("utf-8", "ignore").strip()


async def probe_device(serial: str) -> dict:
    """读取型号/分辨率/DPI/Android 版本，用于接入时落库。"""
    brand = await _probe_shell(serial, "shell", "getprop", "ro.product.brand")
    model = await _probe_shell(serial, "shell", "getprop", "ro.product.model")
    version = await _probe_shell(serial, "shell", "getprop", "ro.build.version.release")

    width = height = dpi = None
    raw_size = await _probe_shell(serial, "shell", "wm", "size")
    if m := _WM_SIZE_RE.search(raw_size):
        width, height = int(m.group(1)), int(m.group(2))
    raw_density = await _probe_shell(serial, "shell", "wm", "density")
    if m := _WM_DENSITY_RE.search(raw_density):
        dpi = int(m.group(1))

    return {
        "brand": brand or "Unknown",
        "model": model or "Android",
        "android_version": version,
        "width": width or 1080,
        "height": height or 1920,
        "dpi": dpi or 480,
    }


class PhysicalBackend(DeviceBackend):
    name = "physical"

    def _serial(self, device: Device) -> str:
        serial = (device.backend_ref or "").strip()
        if not serial:
            raise DeviceCommandError(device.id, "读取设备序列号", "设备未记录 ADB 序列号，请重新接入")
        return serial

    async def _ensure_connected(self, device: Device) -> None:
        serial = self._serial(device)
        await _adb_server_up()
        if _is_tcp_serial(serial):
            await _run(settings.adb_path, "connect", serial)

        last = ""
        for _ in range(_RECONNECT_POLLS):
            code, out, err = await _run(settings.adb_path, "-s", serial, "get-state")
            state = out.decode(errors="replace").strip()
            detail = (state + "\n" + err.decode(errors="replace")).lower()
            if code == 0 and state == "device":
                return
            if "unauthorized" in detail:
                raise DeviceUnreachable(
                    device.id, serial, "设备未授权 USB 调试，请在手机上确认「允许调试」"
                )
            last = state or err.decode(errors="replace").strip()
            await asyncio.sleep(_RECONNECT_INTERVAL)

        raise DeviceUnreachable(device.id, serial, last or "设备不在线")

    async def _adb(self, device: Device, *args: str, reconnect: bool = True) -> tuple[int, bytes, bytes]:
        serial = self._serial(device)
        code, out, err = await _run(settings.adb_path, "-s", serial, *args)
        if code == 0 or not _is_transport_error(err):
            return code, out, err

        if not reconnect:
            raise DeviceUnreachable(
                device.id, serial, err.decode(errors="replace").strip()
            )

        await self._ensure_connected(device)
        code, out, err = await _run(settings.adb_path, "-s", serial, *args)
        if code == 0 or not _is_transport_error(err):
            return code, out, err
        raise DeviceUnreachable(device.id, serial, err.decode(errors="replace").strip())

    async def _ensure_alive(self, device: Device) -> None:
        serial = self._serial(device)
        code, out, _ = await self._adb(device, "get-state")
        if code != 0 or out.decode(errors="replace").strip() != "device":
            raise DeviceUnreachable(
                device.id, serial, out.decode(errors="replace").strip() or "设备未就绪"
            )

    async def _wait_boot_completed(self, device: Device) -> None:
        serial = self._serial(device)
        await _adb_server_up()
        for _ in range(_BOOT_POLLS):
            if _is_tcp_serial(serial):
                await _run(settings.adb_path, "connect", serial)
            code, out, _ = await _run(
                settings.adb_path, "-s", serial, "shell", "getprop", "sys.boot_completed"
            )
            if code == 0 and out.strip() == b"1":
                await self._adb(device, "shell", "input", "keyevent", "KEYCODE_WAKEUP")
                return
            await asyncio.sleep(0.5)
        raise TimeoutError(f"实体机 {serial} 重启后 180s 内未完成开机")

    # ---------- 生命周期 ----------

    async def create(self, device: Device) -> Provisioned:
        raise DeviceCommandError(
            device.id, "创建实例",
            "实体机模式请使用「接入实体机」纳管已连接设备，不支持批量建机",
        )

    async def start(self, device: Device) -> None:
        await self._ensure_connected(device)
        await self._adb(device, "shell", "input", "keyevent", "KEYCODE_WAKEUP")

    async def stop(self, device: Device) -> None:
        serial = self._serial(device)
        if not _is_tcp_serial(serial):
            raise DeviceCommandError(
                device.id, "停止设备",
                "USB 连接的实体机无法远程停机；请改用无线调试，或直接断开数据线",
            )
        await _run(settings.adb_path, "disconnect", serial)

    async def destroy(self, device: Device) -> None:
        # 只删平台记录，不动真实设备
        return None

    async def check_health(self, device: Device) -> bool | None:
        try:
            code, out, _ = await self._adb(device, "get-state")
            return code == 0 and out.decode(errors="replace").strip() == "device"
        except Exception:  # noqa: BLE001  未授权 / 不在线 / adb 不可用
            return False

    async def renew(
        self,
        device: Device,
        *,
        mode: str = "hard",
        rotate_proxy: bool = False,
        keep_url: bool = False,
        progress: RenewProgress | None = None,
    ) -> RenewResult:
        if mode == "hard":
            raise DeviceCommandError(
                device.id, "一键新机",
                "实体机不支持更换设备身份（不篡改 IMEI/序列号/Android ID），请使用 QA 重置",
            )
        if mode != "clear_data":
            raise DeviceCommandError(device.id, "QA 重置", f"不支持的模式: {mode}")

        started = time.monotonic()
        serial = self._serial(device)

        async def _p(phase: str) -> None:
            if progress is not None:
                await progress(phase)

        await _p("stopping")
        packages, failures = await self._list_third_party(device)
        cleared = 0
        for pkg in packages:
            code, _, err = await self._adb(device, "shell", "pm", "clear", pkg, reconnect=False)
            if code == 0:
                cleared += 1
            else:
                failures.append(f"{pkg}: {err.decode(errors='replace').strip()[:80]}")

        await _p("wiping")
        wipe_cmd = "find /sdcard -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null; true"
        code, _, err = await _run_with_timeout(
            180, settings.adb_path, "-s", serial, "shell", "sh", "-c", wipe_cmd
        )
        if code != 0 and _is_transport_error(err):
            raise DeviceUnreachable(
                device.id, serial, err.decode(errors="replace").strip()
            )
        await self._adb(device, "shell", "logcat", "-c", reconnect=False)

        old_url = device.current_url
        device.current_url = old_url if keep_url else None

        await _p("booting")
        await self._adb(device, "reboot", reconnect=False)
        await self._wait_boot_completed(device)

        warnings: list[str] = []
        if failures:
            warnings.append(f"{len(failures)} 个应用数据未能清理：{failures[0]}")
        if packages and not cleared:
            warnings.append("所有应用数据清理均失败，请检查设备权限（可能需要设备管理员/企业模式）")
        if rotate_proxy:
            warnings.append("实体机不支持平台侧换代理，请在设备侧配置网络")

        if keep_url and old_url:
            await _p("url")
            try:
                await self.open_url(device, old_url)
            except Exception as e:  # noqa: BLE001
                warnings.append(f"恢复首页失败：{e}")
                device.current_url = None

        return RenewResult(
            device_id=device.id,
            mode=mode,
            fingerprint_changed=False,
            proxy=None,
            current_url=device.current_url,
            duration_s=round(time.monotonic() - started, 3),
            warnings=warnings,
        )

    async def _list_third_party(self, device: Device) -> tuple[list[str], list[str]]:
        code, out, err = await self._adb(device, "shell", "pm", "list", "packages", "-3")
        if code != 0:
            raise DeviceCommandError(
                device.id, "读取第三方应用",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        packages = [
            line.strip()[len("package:"):]
            for line in out.decode("utf-8", "ignore").splitlines()
            if line.strip().startswith("package:")
        ]
        return packages, []

    # ---------- 快照（实体机暂不支持） ----------

    async def snapshot(self, device: Device, snapshot_id: int):
        raise DeviceCommandError(
            device.id, "创建快照",
            "实体机暂不支持快照，请在设备侧使用系统备份或恢复出厂",
        )

    async def restore_snapshot(self, device: Device, backend_ref: str) -> None:
        raise DeviceCommandError(
            device.id, "恢复快照", "实体机暂不支持快照恢复"
        )

    async def delete_snapshot(self, device: Device, backend_ref: str) -> None:
        return None

    # ---------- 操控 ----------

    async def open_url(self, device: Device, url: str) -> None:
        await self._adb(
            device, "shell", "am", "start",
            "-a", "android.intent.action.VIEW", "-d", url,
        )
        device.current_url = url

    async def tap(self, device: Device, x: int, y: int) -> None:
        await self._adb(device, "shell", "input", "tap", str(x), str(y))

    async def swipe(self, device: Device, x1, y1, x2, y2, duration_ms) -> None:
        await self._adb(
            device, "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        )

    async def input_text(self, device: Device, text: str, append: bool = False) -> None:
        _, out, _ = await self._adb(device, "shell", "ime", "list", "-s")
        if "com.android.adbkeyboard/.AdbIME" in out.decode("utf-8", "ignore"):
            await self._adb(device, "shell", "ime", "set", "com.android.adbkeyboard/.AdbIME")
            await self._adb(
                device, "shell",
                f"am broadcast -a ADB_INPUT_TEXT --es msg {shlex.quote(text)}",
            )
            return
        await self._adb(device, "shell", "input", "text", _escape_shell_text(text))

    async def key(self, device: Device, key: str) -> None:
        if key in _STATUSBAR_CMDS:
            await self._adb(device, "shell", "cmd", "statusbar", _STATUSBAR_CMDS[key])
            return
        code = _KEYCODES.get(key, key)
        await self._adb(device, "shell", "input", "keyevent", code)

    async def unlock(self, device: Device) -> None:
        """清除实体机屏幕锁：dismiss-keyguard + MENU 键兜底（部分 ROM 需二次唤醒）。"""
        await self._adb(device, "shell", "wm", "dismiss-keyguard")
        await self._adb(device, "shell", "input", "keyevent", "82")

    async def install(self, device: Device, apk_url: str) -> None:
        parsed = urllib.parse.urlparse(apk_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError("APK 地址必须是 http/https")
        if settings.apk_url_allow_hosts and parsed.hostname not in settings.apk_url_allow_hosts:
            raise ValueError(f"APK 主机不在白名单: {parsed.hostname}")

        def _download() -> str:
            fd, path = tempfile.mkstemp(suffix=".apk")
            os.close(fd)
            try:
                with urllib.request.urlopen(apk_url, timeout=300) as resp, open(path, "wb") as f:
                    while chunk := resp.read(1024 * 256):
                        f.write(chunk)
            except Exception:
                os.unlink(path)
                raise
            return path

        local = await asyncio.to_thread(_download)
        try:
            code, _, err = await _run_with_timeout(
                600, settings.adb_path, "-s", self._serial(device), "install", "-r", local
            )
            if code != 0:
                raise DeviceCommandError(
                    device.id, "安装 APK",
                    err.decode(errors="replace").strip() or f"adb 退出码 {code}",
                )
        finally:
            try:
                os.unlink(local)
            except OSError:
                pass

    async def list_apps(self, device: Device) -> list[str]:
        packages: set[str] = set()
        failures: list[str] = []
        for extra in (("-3",), ()):
            code, out, err = await self._adb(device, "shell", "pm", "list", "packages", *extra)
            if code != 0 or not out:
                failures.append(err.decode(errors="replace").strip() or f"adb 退出码 {code}")
                continue
            for line in out.decode("utf-8", "ignore").splitlines():
                line = line.strip()
                if line.startswith("package:"):
                    packages.add(line[len("package:"):].strip())
        if not packages and failures:
            raise DeviceCommandError(device.id, "读取应用列表", failures[-1])
        return sorted(packages)[:200]

    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        code, out, err = await self._adb(device, "shell", "logcat", "-d", "-t", str(lines))
        if code != 0:
            raise DeviceCommandError(
                device.id, "读取日志",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        return out.decode("utf-8", "ignore").splitlines()[-lines:]

    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        await self._adb(device, "shell", "wm", "size", f"{width}x{height}")
        await self._adb(device, "shell", "wm", "density", str(dpi))
        device.width, device.height, device.dpi = width, height, dpi

    async def uninstall_app(self, device: Device, package: str) -> None:
        await self._adb(device, "uninstall", package)

    async def launch_app(self, device: Device, package: str) -> None:
        await self._adb(
            device, "shell", "monkey", "-p", package,
            "-c", "android.intent.category.LAUNCHER", "1",
        )

    async def stop_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "am", "force-stop", package)

    async def clear_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "pm", "clear", package)

    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        code, out, err = await self._adb(device, "shell", "ls", "-p", path)
        if code != 0:
            raise DeviceCommandError(
                device.id, f"读取目录 {path}",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        items = []
        for n in out.decode("utf-8", "ignore").splitlines():
            n = n.strip().rstrip("\r")
            if not n:
                continue
            items.append({"name": n.rstrip("/"), "is_dir": n.endswith("/")})
        return items[:500]

    async def push_file(self, device: Device, local_path: str, remote_path: str) -> None:
        await self._adb(device, "push", local_path, remote_path)

    async def pull_file(self, device: Device, remote_path: str, local_path: str) -> bool:
        code, _, _ = await self._adb(device, "pull", remote_path, local_path)
        return code == 0

    async def delete_file(self, device: Device, remote_path: str) -> None:
        await self._adb(device, "shell", "rm", "-rf", remote_path)

    async def screenshot(self, device: Device) -> str:
        code, out, err = await self._adb(device, "exec-out", "screencap", "-p")
        if code == 0 and out:
            return "data:image/png;base64," + base64.b64encode(out).decode("ascii")
        if _is_transport_error(err):
            raise DeviceUnreachable(
                device.id, self._serial(device),
                err.decode(errors="replace").strip(),
            )
        raise DeviceCommandError(
            device.id, "截图",
            err.decode(errors="replace").strip() or "screencap 返回空数据",
        )

    # ---------- 输入法 ----------

    async def list_input_methods(self, device: Device) -> list[dict]:
        code, out, err = await self._adb(device, "shell", "ime", "list", "-s")
        if code != 0:
            raise DeviceCommandError(
                device.id, "列出输入法",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        ids = [l.strip() for l in out.decode("utf-8", "ignore").splitlines() if l.strip()]
        active = await self.get_active_input_method(device)
        methods = []
        for mid in ids:
            code2, out2, _ = await self._adb(device, "shell", "ime", "is-enabled", mid)
            raw = out2.decode("utf-8", "ignore").strip().lower() if code2 == 0 else ""
            methods.append({
                "id": mid,
                "enabled": "enabled" in raw and "not" not in raw and "disabled" not in raw,
                "active": mid == active,
            })
        return methods

    async def get_active_input_method(self, device: Device) -> str:
        code, out, err = await self._adb(
            device, "shell", "settings", "get", "secure", "default_input_method"
        )
        if code != 0:
            raise DeviceCommandError(
                device.id, "获取当前输入法",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        return out.decode("utf-8", "ignore").strip()

    async def set_input_method(self, device: Device, ime_id: str) -> None:
        await self._adb(device, "shell", "ime", "set", ime_id)

    async def enable_input_method(self, device: Device, ime_id: str) -> None:
        await self._adb(device, "shell", "ime", "enable", ime_id)

    async def disable_input_method(self, device: Device, ime_id: str) -> None:
        await self._adb(device, "shell", "ime", "disable", ime_id)

    # ---------- scrcpy ----------

    async def prepare_scrcpy(self, device: Device) -> dict:
        from urllib.parse import quote

        base = (settings.ws_scrcpy_base or "").rstrip("/")
        if not base:
            return {
                "ready": False,
                "ws_scrcpy_base": "",
                "udid": self._serial(device),
                "iframe_url": "",
                "proxy_ws_url": "",
                "width": device.width,
                "height": device.height,
                "hint": "实体机模式需配置 CLOUD_WS_SCRCPY_BASE 指向 ws-scrcpy 服务",
            }

        await self._ensure_alive(device)
        udid = self._serial(device)
        await self._adb(device, "forward", "tcp:8886", "localabstract:scrcpy")
        proto = "wss" if base.lower().startswith("https://") else "ws"
        host_port = urllib.parse.urlparse(base).netloc
        inner_ws = f"{proto}://{host_port}/?action=proxy-adb&remote=tcp:8886&udid={quote(udid)}"
        q = render_quality_params(device.render_quality)
        iframe_url = (
            f"{base}/stream_only.html#!action=stream&udid={quote(udid)}"
            f"&player=broadway&ws={quote(inner_ws)}"
            f"&bitrate={q['bitrate']}&maxFps={q['max_fps']}"
            f"&iFrameInterval={q['i_frame_interval']}"
            f"&maxSize={max(device.width, device.height)}"
        )
        return {
            "ready": True,
            "ws_scrcpy_base": base,
            "udid": udid,
            "iframe_url": iframe_url,
            "proxy_ws_url": inner_ws,
            "width": device.width,
            "height": device.height,
        }
