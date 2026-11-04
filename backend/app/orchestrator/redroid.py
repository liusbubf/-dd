"""Redroid 后端：真实 Docker + Redroid + adb（仅 Linux 宿主机）。

对应计划 D1/D3（起容器）、D3/D5（一机一码注入 props）、D4（编排 API）、
D5（独立出口 IP/代理）、D11–D12（批量/同步操控走 adb/minitouch）。

依赖：
- docker（Python SDK）：容器生命周期。
- adb（命令行）：连接容器 5555、下发触控/输入/装 APK。
在 macOS/无 Docker 环境不会被导入（get_backend 按配置选择）。
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import shlex
import subprocess
import time

from ..config import settings
from ..fingerprint import generate_fingerprint, redroid_props
from ..models import Device
from .base import (
    DeviceBackend,
    DeviceCommandError,
    DeviceUnreachable,
    Provisioned,
    RenewProgress,
    RenewResult,
    SnapshotResult,
    pick_proxy,
    render_quality_params,
)

# 主题壁纸（随后端一起分发到 app/skins/）
_SKIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skins")

_KEYCODES = {
    "back": "KEYCODE_BACK",
    "home": "KEYCODE_HOME",
    "menu": "KEYCODE_MENU",
    "recent": "KEYCODE_APP_SWITCH",  # 最近任务
    "power": "KEYCODE_POWER",
    "wake": "KEYCODE_WAKEUP",
    "enter": "KEYCODE_ENTER",
    "del": "KEYCODE_DEL",                    # 退格（Backspace，删除光标前字符）
    "forward_del": "KEYCODE_FORWARD_DEL",    # Delete（删除光标后字符）
    "volume_up": "KEYCODE_VOLUME_UP",
    "volume_down": "KEYCODE_VOLUME_DOWN",
    # 导航键
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "tab": "KEYCODE_TAB",
    "space": "KEYCODE_SPACE",
    "move_home": "KEYCODE_MOVE_HOME",        # 行首
    "move_end": "KEYCODE_MOVE_END",          # 行尾
    "page_up": "KEYCODE_PAGE_UP",
    "page_down": "KEYCODE_PAGE_DOWN",
    "cut": "KEYCODE_CUT",
    "copy": "KEYCODE_COPY",
    "paste": "KEYCODE_PASTE",
    "select_all": "KEYCODE_SELECT_ALL",
}

# adb shell input text 经过设备端 shell 解释，特殊字符（& | ; $ 等）会被误解析
_SHELL_ESCAPE_RE = re.compile(r'([&|;(){}<>$`"\'!*?#~\\\[\]])')

def _escape_shell_text(text: str) -> str:
    """转义文本中的 shell 特殊字符，空格用 %s 替代（Android input 命令规范）。"""
    return _SHELL_ESCAPE_RE.sub(r'\\\1', text).replace(" ", "%s")


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    # Windows 下 ProactorEventLoop 与 create_subprocess_exec 不兼容（会抛
    # NotImplementedError），改用 subprocess.run + asyncio.to_thread 跨平台执行。
    # 必须带超时：adb 卡死会永久占用线程池线程（默认约 32 个），累积后整个后端假死。
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            list(args),
            capture_output=True,
            timeout=settings.adb_timeout,
        )
    except subprocess.TimeoutExpired as e:
        detail = f"\nadb 命令超时（>{settings.adb_timeout:g}s）"
        return 124, e.stdout or b"", (e.stderr or b"") + detail.encode()
    except OSError as e:
        # adb 不存在 / 无执行权限：返回错误码让上层转成可读提示，而不是 500
        return 127, b"", f"adb 无法启动（{settings.adb_path}）：{e}".encode()
    return proc.returncode or 0, proc.stdout, proc.stderr


# 状态栏动作 -> `cmd statusbar` 子命令（AOSP 正规入口，比顶端下滑手势可靠）
_STATUSBAR_CMDS = {
    "notifications": "expand-notifications",  # 通知栏（iOS 语义：从左上角下滑）
    "quicksettings": "expand-settings",       # 快捷设置（iOS 语义：控制中心）
    "collapse": "collapse",                   # 收起
}

# adb 传输层错误特征（stderr 命中即认为设备不可达，而非命令本身失败）。
#
# 判据分两段，缺一不可：
#   1) 必须是 adb 客户端自己报的错（行首 "error:" / "adb:"）——用于把设备侧
#      shell 的错误排除掉，比如 `sh: xyz: not found` 不该被当成设备失联；
#   2) 且命中传输类关键词。
# 坑：真实报文是 `error: device 'localhost:5561' not found`，序列号夹在中间，
# 所以不能直接匹配 "device not found"（早期版本正是因此从未触发自愈重连）。
_ADB_ERR_PREFIX_RE = re.compile(rb"^\s*(error|adb):", re.I | re.M)
_TRANSPORT_KEYWORDS = (
    b"not found",
    b"no devices",
    b"offline",
    b"unauthorized",
    b"still connecting",
    b"connection refused",
    b"cannot connect to daemon",
    b"protocol fault",
    b"closed",
)

# _ensure_alive 的体检缓存时长（秒）。取帧最高 12fps，不能每帧体检
_ALIVE_TTL = 5.0

# 自愈重连后等待设备就绪的轮询次数与间隔（总上限约 2s，足够本地 TCP 握手）
_RECONNECT_POLLS = 8
_RECONNECT_INTERVAL = 0.25


def _is_transport_error(err: bytes) -> bool:
    low = (err or b"").lower()
    if not _ADB_ERR_PREFIX_RE.search(low):
        return False
    return any(k in low for k in _TRANSPORT_KEYWORDS)


async def _adb_server_up() -> None:
    """确保 adb server 已在跑（输出重定向 DEVNULL）。

    坑：adb 客户端发现 server 不在会自动 fork 一个常驻 server，子进程继承
    stdout/stderr 管道 → _run 的 communicate() 永远等不到 EOF 而挂死
    （表现为换肤后台任务卡在 queued）。先用 DEVNULL 显式起 server 即可规避。
    """
    try:
        await asyncio.to_thread(
            subprocess.run,
            [settings.adb_path, "start-server"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # 起不来就让后续命令按传输错误处理


class RedroidBackend(DeviceBackend):
    name = "redroid"

    def __init__(self) -> None:
        import docker  # 延迟导入，避免非 Linux 环境报错

        self.docker = docker.from_env()
        self._alive_at: dict[int, float] = {}  # device_id -> 上次体检通过的时刻

    def _serial(self, device: Device) -> str:
        return f"{settings.redroid_host}:{device.adb_port}"

    async def _adb(
        self, device: Device, *args: str, reconnect: bool = True
    ) -> tuple[int, bytes, bytes]:
        """执行一条 adb 命令。

        与「命令本身返回非 0」（如 pm 查不到包）不同，**传输层错误**（设备没连上 /
        offline / 容器没了）意味着这台设备根本控制不了 —— 此时先尝试自愈重连一次，
        仍不行就抛 DeviceUnreachable，**绝不返回让调用方误当成功**。

        背景：宿主休眠、adb server 重启、容器重建都会掉连接，过去这里静默返回，
        导致「预览有画面、批量报成功」而设备实际失联。
        """
        serial = self._serial(device)
        code, out, err = await _run(settings.adb_path, "-s", serial, *args)
        if code == 0 or not _is_transport_error(err):
            return code, out, err

        if not reconnect:
            raise DeviceUnreachable(device.id, serial, err.decode(errors="replace").strip())

        # 自愈：显式起 server（防 fork 继承管道挂死）后重连再重试。
        # 注意 `adb connect` 是异步的 —— 它先返回 "connected"，TCP 握手与设备就绪
        # 还要几百毫秒。立刻重试会照样拿到 "device not found"，所以必须等就绪。
        await _adb_server_up()
        await _run(settings.adb_path, "connect", serial)
        for _ in range(_RECONNECT_POLLS):
            st_code, st_out, _ = await _run(settings.adb_path, "-s", serial, "get-state")
            if st_code == 0 and st_out.strip() == b"device":
                break
            await asyncio.sleep(_RECONNECT_INTERVAL)

        code, out, err = await _run(settings.adb_path, "-s", serial, *args)
        if code == 0 or not _is_transport_error(err):
            self._alive_at.pop(device.id, None)  # 让下次 _ensure_alive 重新体检
            return code, out, err
        raise DeviceUnreachable(device.id, serial, err.decode(errors="replace").strip())

    async def _ensure_alive(self, device: Device) -> None:
        """确认控制通道真的活着（带 TTL 缓存，避免高频取帧把 adb 打爆）。

        截图会按 5–12fps 轮询，不能每帧都体检；但也不能不检 —— 主屏皮肤渲染那条
        路径根本不碰 adb，设备死了照样出图，正是它把故障藏了起来。
        """
        now = time.monotonic()
        if now - self._alive_at.get(device.id, 0.0) < _ALIVE_TTL:
            return
        code, out, err = await self._adb(device, "get-state")  # 失败会自愈/抛错
        if code != 0 or out.strip() != b"device":
            raise DeviceUnreachable(
                device.id, self._serial(device),
                (out + err).decode(errors="replace").strip() or "设备未就绪",
            )
        self._alive_at[device.id] = now

    async def create(self, device: Device) -> Provisioned:
        port = settings.redroid_base_adb_port + device.id
        props = redroid_props(device.fingerprint or {})
        env_proxy = (device.fingerprint or {}).get("network", {}).get("proxy")

        # 清理可能残留的同名容器，避免创建冲突
        try:
            old = await asyncio.to_thread(self.docker.containers.get, f"redroid_{device.id}")
            await asyncio.to_thread(old.remove, force=True)
        except Exception:  # noqa: BLE001
            pass

        container = await asyncio.to_thread(
            self.docker.containers.run,
            settings.redroid_image,
            command=[
                f"androidboot.redroid_gpu_mode={settings.redroid_gpu_mode}",
                f"androidboot.redroid_width={device.width}",
                f"androidboot.redroid_height={device.height}",
                f"androidboot.redroid_dpi={device.dpi}",
                *props,
            ],
            name=f"redroid_{device.id}",
            detach=True,
            privileged=True,
            volumes={f"{settings.redroid_data_dir}/inst{device.id}": {"bind": "/data", "mode": "rw"}},
            ports={"5555/tcp": port},
            environment={"HTTP_PROXY": env_proxy, "HTTPS_PROXY": env_proxy} if env_proxy else None,
            restart_policy={"Name": "unless-stopped"},  # VM/Docker 重启后自动拉起，避免休眠丢运行态
        )
        return Provisioned(backend_ref=container.id, adb_port=port)

    async def _wait_boot_completed(self, device: Device) -> None:
        """等 Android 真正 boot_completed，adb 才可用。create 后容器已在运行，直接等 boot。"""
        serial = self._serial(device)
        await _adb_server_up()  # 防 connect 自动 fork server 继承管道挂死 _run
        for _ in range(360):  # 最多 ~180s（轮询 0.5s，检测更灵敏）
            await _run(settings.adb_path, "connect", serial)
            _, out, _ = await _run("adb", "-s", serial, "shell", "getprop", "sys.boot_completed")
            if out.strip() == b"1":
                return
            await asyncio.sleep(0.5)

    async def start(self, device: Device) -> None:
        if device.backend_ref:
            c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
            await asyncio.to_thread(c.start)
        await self._wait_boot_completed(device)

    async def stop(self, device: Device) -> None:
        if device.backend_ref:
            c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
            await asyncio.to_thread(c.stop)

    async def destroy(self, device: Device) -> None:
        if device.backend_ref:
            try:
                c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
                await asyncio.to_thread(c.remove, force=True)
            except Exception:  # noqa: BLE001  容器可能已不存在
                pass

    async def check_health(self, device: Device) -> bool | None:
        if not device.backend_ref:
            return False
        try:
            c = await asyncio.to_thread(self.docker.containers.get, device.backend_ref)
            return c.status == "running"
        except Exception:  # noqa: BLE001  容器不存在 / Docker 不可达
            return False

    async def _helper(self, command: str, volumes: dict[str, dict]) -> tuple[int, bytes]:
        """用 Redroid 镜像起一个一次性助手容器执行 shell 命令。

        用于操作 bind mount 的 /data：Docker commit 不会包含挂载卷，必须真正
        在容器内打包/解包。远程 DOCKER_HOST 下也由远端 daemon 执行，路径语义一致。
        """

        def _do() -> tuple[int, bytes]:
            container = self.docker.containers.create(
                settings.redroid_image,
                entrypoint=["/system/bin/sh", "-c"],
                command=[command],
                volumes=volumes,
                network_disabled=True,
            )
            try:
                container.start()
                result = container.wait(timeout=600)
                return int(result.get("StatusCode", 1)), container.logs()
            finally:
                try:
                    container.remove(force=True)
                except Exception:  # noqa: BLE001
                    pass

        return await asyncio.to_thread(_do)

    def _snap_dir(self, device_id: int) -> str:
        return f"{settings.redroid_data_dir}/snapshots/{device_id}"

    async def _wipe_data(self, device_id: int) -> None:
        """清空实例数据目录（必须在容器已停止/删除之后执行）。

        不能只删容器：`/data` 是宿主 bind mount，重建容器后会原样挂回来，
        设备里装的应用/登录态/文件全都还在，「新机」就是假的。
        优先用 Docker 助手容器（兼容远程 DOCKER_HOST），失败再退回本地 rmtree；
        两条路都不通时明确报错，绝不静默跳过清空。
        """
        path = f"{settings.redroid_data_dir}/inst{device_id}"
        try:
            code, _ = await self._helper(
                "find /data -mindepth 1 -maxdepth 1 -exec rm -rf {} +",
                {path: {"bind": "/data", "mode": "rw"}},
            )
            if code == 0:
                return
        except Exception:  # noqa: BLE001  镜像缺少 sh / Docker 不可用 → 试本地
            pass

        import shutil

        if os.path.isdir(path):
            await asyncio.to_thread(shutil.rmtree, path, True)
            return
        raise RuntimeError(f"无法清空实例数据目录 {path}（助手容器执行失败，本地也不存在）")

    @staticmethod
    def _check_ref(backend_ref: str) -> str:
        """快照引用必须是纯文件名，避免被拼进路径做目录穿越。"""
        if not backend_ref or os.path.basename(backend_ref) != backend_ref:
            raise ValueError(f"非法快照引用: {backend_ref}")
        return backend_ref

    async def snapshot(self, device: Device, snapshot_id: int) -> SnapshotResult:
        """停机后打包 /data（停机保证数据库/文件一致）。"""
        cref = device.backend_ref or f"redroid_{device.id}"
        container = await asyncio.to_thread(self.docker.containers.get, cref)
        was_running = container.status == "running"
        name = f"snap-{snapshot_id}.tar.gz"

        if was_running:
            await asyncio.to_thread(container.stop, timeout=15)
        try:
            code, out = await self._helper(
                f"mkdir -p /snap && tar -czf /snap/{name} -C /data . "
                f"&& stat -c %s /snap/{name}",
                {
                    f"{settings.redroid_data_dir}/inst{device.id}": {"bind": "/data", "mode": "ro"},
                    self._snap_dir(device.id): {"bind": "/snap", "mode": "rw"},
                },
            )
        finally:
            if was_running:
                await asyncio.to_thread(container.start)
                await self._wait_boot_completed(device)

        if code != 0:
            raise RuntimeError(
                f"快照打包失败（退出码 {code}）：{out.decode(errors='replace').strip()[-300:]}"
            )
        size = None
        lines = out.decode(errors="replace").strip().splitlines()
        if lines:
            try:
                size = int(lines[-1].strip())
            except ValueError:
                pass
        return SnapshotResult(backend_ref=name, size_bytes=size)

    async def restore_snapshot(self, device: Device, backend_ref: str) -> None:
        """清空当前数据 → 解包快照 → 重启到可用。身份以设备当前记录为准。"""
        ref = self._check_ref(backend_ref)
        snap_dir = self._snap_dir(device.id)

        # 先确认快照可读，避免清空后才发现文件不存在
        code, _ = await self._helper(
            f"test -s /snap/{ref}",
            {snap_dir: {"bind": "/snap", "mode": "ro"}},
        )
        if code != 0:
            raise RuntimeError(f"快照文件不存在或为空: {ref}")

        cref = device.backend_ref or f"redroid_{device.id}"
        container = await asyncio.to_thread(self.docker.containers.get, cref)
        was_running = container.status == "running"
        if was_running:
            await asyncio.to_thread(container.stop, timeout=15)

        await self._wipe_data(device.id)
        try:
            code, out = await self._helper(
                f"tar -xzf /snap/{ref} -C /data",
                {
                    f"{settings.redroid_data_dir}/inst{device.id}": {"bind": "/data", "mode": "rw"},
                    snap_dir: {"bind": "/snap", "mode": "ro"},
                },
            )
            if code != 0:
                raise RuntimeError(
                    f"快照解包失败（退出码 {code}）："
                    f"{out.decode(errors='replace').strip()[-300:]}"
                )
        finally:
            # 即使恢复失败也把容器拉起来，至少让设备可诊断
            await asyncio.to_thread(container.start)
            await self._wait_boot_completed(device)
            self._alive_at.pop(device.id, None)

    async def delete_snapshot(self, device: Device, backend_ref: str) -> None:
        """删除快照文件；已不存在视为成功。"""
        ref = self._check_ref(backend_ref)
        snap_dir = self._snap_dir(device.id)
        try:
            code, _ = await self._helper(
                f"rm -f /snap/{ref}",
                {snap_dir: {"bind": "/snap", "mode": "rw"}},
            )
            if code == 0:
                return
        except Exception:  # noqa: BLE001  Docker 不可用时试本地路径
            pass

        local = os.path.join(snap_dir, ref)
        if os.path.isfile(local):
            os.remove(local)

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

        # 1) 删容器：ro.* 指纹与代理环境变量都是创建期注入，不重建不会生效
        await _p("stopping")
        await self.destroy(device)
        self._alive_at.pop(device.id, None)

        # 2) 清 /data：应用、账号、文件、启动器数据全部归零
        await _p("wiping")
        await self._wipe_data(device.id)

        # 3) 硬重置换新身份；清数据模式保留原身份证
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
            # 仅清数据：身份不变，但可以换出口代理（容器照样重建以注入新 env）
            fp = dict(old_fp)
            network = dict(fp.get("network", {}))
            network["proxy"] = pick_proxy(network.get("proxy"))
            fp["network"] = network
            device.fingerprint = fp

        device.current_url = old_url if keep_url else None

        # 4) 按新指纹/新代理重建并等待开机
        await _p("creating")
        prov = await self.create(device)
        device.backend_ref = prov.backend_ref
        device.adb_port = prov.adb_port
        await _p("booting")
        await self._wait_boot_completed(device)

        # 5) 数据清空后皮肤（启动器/壁纸）也没了，按设备原主题重新落地。
        # 皮肤失败不阻断新机：设备已可用，只是外观回退到原生安卓。
        warnings: list[str] = []
        theme = getattr(device, "skin", "ios") or "ios"
        await _p("skin")
        try:
            await self.apply_skin(device, theme)
        except Exception as e:  # noqa: BLE001
            import logging

            logging.getLogger("redroid").warning(
                "新机后皮肤落地失败 device=%s theme=%s: %s", device.id, theme, e
            )
            warnings.append(f"皮肤落地失败：{e}")

        # 6) 按需恢复首页；失败只记警告 —— 设备已经就绪，不该因打不开网页判整次新机失败
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
            fingerprint_changed=changed,
            proxy=device.fingerprint.get("network", {}).get("proxy"),
            current_url=device.current_url,
            duration_s=round(time.monotonic() - started, 3),
            warnings=warnings,
        )

    async def open_url(self, device: Device, url: str) -> None:
        # 先下发再写库：反过来的话 adb 失败仍会把 current_url 落库，
        # 列表显示「当前页面 = xxx」而设备上根本没打开（失联时的假象来源之一）
        await self._adb(device, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url)
        device.current_url = url

    async def tap(self, device: Device, x: int, y: int) -> None:
        await self._adb(device, "shell", "input", "tap", str(x), str(y))

    async def swipe(self, device: Device, x1, y1, x2, y2, duration_ms) -> None:
        await self._adb(device, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms))

    async def input_text(self, device: Device, text: str, append: bool = False) -> None:
        import logging

        log = logging.getLogger("redroid.input_text")
        log.info("device %d input_text: %s append=%s", device.id, repr(text), append)

        # 拼接模式：先读取输入框当前文字，再拼上新文字后整体回写
        if append:
            current = await self._read_focused_text(device)
            if current:
                text = current + text
                log.info("device %d append: current=%r + new=%r → %r", device.id, current, text[len(current):], text)

        # 统一走 ADBKeyboard 广播，避免被搜狗等第三方输入法拦截 input text
        # 流程：切到 ADBKeyboard（不可见键盘）→ 广播发送 → 保持 ADBKeyboard
        # 不切回原 IME，否则原 IME 检测到输入框聚焦会自动弹出云手机键盘
        adb_ime = "com.android.adbkeyboard/.AdbIME"

        try:
            # 读取当前默认 IME，避免重复切换（每次 ime set 都有开销）
            _, out, _ = await self._adb(device, "shell", "settings", "get", "secure", "default_input_method")
            current_ime = out.decode("utf-8", errors="replace").strip()

            if current_ime != adb_ime:
                await self._adb(device, "shell", "ime", "set", adb_ime)
            # 用 shlex.quote() 将文本包裹在单引号中，POSIX 单引号内所有字符均原样保留
            escaped = shlex.quote(text)
            await self._adb(
                device, "shell",
                f"am broadcast -a ADB_INPUT_TEXT --es msg {escaped}",
            )
            await asyncio.sleep(0.05)  # 等广播处理完成
            # 不切回原 IME：ADBKeyboard 是不可见键盘，保持它作为默认 IME 可防止云手机键盘弹出
            log.info("device %d: ADBKeyboard broadcast sent, text=%s", device.id, repr(text))
        except DeviceUnreachable:
            raise
        except Exception as e:
            log.warning("device %d: ADBKeyboard failed (%s), trying fallback", device.id, e)
            import tempfile

            remote = "/sdcard/_cloud_phone_input.txt"
            with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", delete=False, encoding="utf-8"
            ) as f:
                f.write(text)
                local = f.name
            try:
                await self._adb(device, "push", local, remote)
            finally:
                os.unlink(local)
            try:
                await self._adb(
                    device, "shell", "sh", "-c",
                    f"input text $(sed 's/ /%s/g' {remote})",
                )
            except Exception:
                pass
            try:
                await self._adb(device, "shell", "rm", remote)
            except Exception:
                pass

    async def _read_focused_text(self, device: Device) -> str:
        """通过 dumpsys input_method 读取当前焦点输入框中的文字。

        解析 mExtractedText 区域的 text=<value> 行，返回空串表示无焦点或读取失败。
        """
        import logging
        log = logging.getLogger("redroid._read_focused_text")

        try:
            _, out, _ = await self._adb(device, "shell", "dumpsys", "input_method")
            text = out.decode("utf-8", errors="replace")
        except Exception as e:
            log.warning("device %d: dumpsys input_method failed: %s", device.id, e)
            return ""

        # 在 mExtractedText 区域内匹配 text=<value> 行
        # 输出格式示例：
        #   mExtractedText:
        #     text=hello world
        #     partialStartOffset=-1
        m = re.search(r"mExtractedText:\s*\n\s*text=(.*)", text)
        if m:
            current = m.group(1).strip()
            log.info("device %d: focused text=%r", device.id, current)
            return current

        log.info("device %d: no focused text found in dumpsys", device.id)
        return ""

    async def key(self, device: Device, key: str) -> None:
        # 通知栏/控制中心：从屏幕顶端下滑手势在 adb input swipe 下并不可靠
        # （起点必须压在状态栏上，且手势导航开启后更易被吞），statusbar 命令是
        # AOSP 的正规入口，幂等且立即生效。
        if key in _STATUSBAR_CMDS:
            await self._adb(device, "shell", "cmd", "statusbar", _STATUSBAR_CMDS[key])
            return
        if key == "home":
            # 标准 HOME 键事件。之前用 `am start MAIN/HOME`，当启动器已处于主屏时会
            # 触发「二次 Home」误开 app 抽屉（search apps），改用 KEYCODE_HOME 更可靠。
            await self._adb(device, "shell", "input", "keyevent", "KEYCODE_HOME")
            return
        code = _KEYCODES.get(key, key)
        await self._adb(device, "shell", "input", "keyevent", code)

    async def unlock(self, device: Device) -> None:
        """清除屏幕锁：dismiss-keyguard 是 AOSP 正规入口，再补 MENU 键唤醒。"""
        await self._adb(device, "shell", "wm", "dismiss-keyguard")
        await self._adb(device, "shell", "input", "keyevent", "82")

    async def install(self, device: Device, apk_url: str) -> None:
        # 简化：容器内下载再安装；生产可先落地宿主再 adb install
        await self._adb(device, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", apk_url)

    async def list_apps(self, device: Device) -> list[str]:
        # 优先列第三方应用（-3），再补一份全量（去桌面/输入法等系统噪声后仍可见常用系统应用）
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
                    name = line[len("package:"):].strip()
                    if name:
                        packages.add(name)
        # 两次 pm 都失败且一个包都没读到 = 读取失败，不是「这台设备没装应用」。
        # 空列表曾把失联设备伪装成「0 个应用」，必须如实报错。
        if not packages and failures:
            raise DeviceCommandError(device.id, "读取应用列表", failures[-1])
        return sorted(packages)[:200]

    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        code, out, err = await self._adb(device, "shell", "logcat", "-d", "-t", str(lines))
        # 命令失败要如实报错：返回空列表会被前端显示成「这台设备没有日志」，
        # 把「读不到」伪装成「没有」——与截图静默回退是同一类问题。
        if code != 0:
            raise DeviceCommandError(
                device.id, "读取日志",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        return out.decode("utf-8", "ignore").splitlines()[-lines:]

    async def _resolve_home_pkg(self, device: Device, timeout_s: float = 0) -> str | None:
        """解析当前 HOME 启动器包名。

        timeout_s > 0 时：轮询等待 home 可用（用于刚开机 framework 还没起完）。
        resolve-activity --brief 输出可能有两行（首行元数据、末行才是组件名），
        取最后一行再 split("/")[0]，避免把脏数据当包名导致 force-stop/monkey 失效。
        """
        start = asyncio.get_event_loop().time()
        while True:
            code, out, _ = await self._adb(
                device, "shell", "cmd", "package", "resolve-activity", "--brief",
                "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
            )
            if code == 0 and out:
                lines = [ln for ln in out.decode(errors="replace").splitlines() if ln.strip()]
                if lines:
                    return lines[-1].strip().split("/")[0]
            if timeout_s <= 0 or asyncio.get_event_loop().time() - start >= timeout_s:
                return None
            await asyncio.sleep(0.5)

    async def _restart_launcher(self, device: Device, pkg: str | None, wait: float = 3.0) -> None:
        """重启启动器并回到主屏。"""
        if pkg:
            await self._adb(device, "shell", "am", "force-stop", pkg)
        await asyncio.sleep(0.5)
        await self._adb(device, "shell", "input", "keyevent", "KEYCODE_HOME")
        if wait > 0:
            await asyncio.sleep(wait)

    async def _relayout_launcher(self, device: Device, width: int, height: int) -> None:
        """分辨率切换后更新启动器偏好并重启，让 Lawnchair 基于新分辨率重建布局。

        关键：分辨率切换后必须更新 launcher preferences 中的 pref_numRows
        （以及其他网格参数），否则启动器会用旧行数在新分辨率下渲染，
        导致图标/底部 Dock 栏偏移。

        注意：等待时间宁可略长，也不能让图标/Dock布局错乱，否则体验更差。
        """
        pkg = await self._resolve_home_pkg(device)
        if not pkg:
            return

        cref = device.backend_ref or f"redroid_{device.id}"
        try:
            container = await asyncio.to_thread(self.docker.containers.get, cref)
            # 1. 更新 launcher preferences 中的网格参数（基于新分辨率）
            try:
                await self._merge_launcher_prefs(container, pkg, width, height)
            except Exception:
                pass
        except Exception:
            pass

        # 2. force-stop 启动器，然后用新分辨率+新偏好启动它
        #    等待时间必须充足：等 Lawnchair 用新 metrics + 新 prefs 重建完成布局
        #    不然 Dock 栏与桌面图标会错位（宁可多等 1-2s，也不能留错位）
        await self._adb(device, "shell", "am", "force-stop", pkg)
        await asyncio.sleep(0.5)
        await self._adb(device, "shell", "input", "keyevent", "KEYCODE_HOME")
        await asyncio.sleep(2.5)

    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        """切换分辨率：重建容器以应用真正的 framebuffer 分辨率。

        Redroid 的分辨率在容器创建时通过 kernel 参数 (androidboot.redroid_width/height/dpi)
        设定，`wm size` 只能修改 WindowManager 的虚拟分辨率，无法改变 framebuffer 实际分辨率。
        虚拟分辨率 ≠ framebuffer 时，启动器的 Dock 栏和图标位置会错乱。
        因此必须重建容器来应用真正的分辨率。
        """
        # 1. 更新内存中的设备参数（create 会读取这些值）
        device.width, device.height, device.dpi = width, height, dpi

        # 优化：移除多余的 stop() 调用
        #   - create() 内部已做 old.remove(force=True)，会直接强杀旧容器
        #   - stop() 是优雅停止，默认等 10s 超时才 SIGKILL，白白浪费数秒
        # # 2. 停止旧容器
        # try:
        #     await self.stop(device)
        # except Exception:
        #     pass

        # 2. 创建新容器（create 内部会 remove 旧容器 + 用新分辨率参数创建）
        prov = await self.create(device)
        device.backend_ref = prov.backend_ref
        device.adb_port = prov.adb_port

        # 3. 启动新容器并等待开机完成
        # 优化：create 中 containers.run(detach=True) 已直接启动容器，跳过 start() 中多余的 c.start()
        await self._wait_boot_completed(device)

        # 4. 轮询等待启动器就绪（比硬等更快）：PackageManager 返回 home app pkg 即 framework OK
        # 优化：timeout 8.0s → 5.0s（boot_completed=1 后 framework 已基本就绪，home pkg 很快可用）
        pkg = await self._resolve_home_pkg(device, timeout_s=5.0)
        # 优化：去掉 pkg=None 时的保底 sleep(2.0)
        # _relayout_launcher 内部已含 force-stop → HOME → sleep，足够覆盖启动器延迟

        # 6. 更新启动器偏好（基于新分辨率计算 pref_numRows）并重启启动器
        await self._relayout_launcher(device, width, height)

    async def uninstall_app(self, device: Device, package: str) -> None:
        await self._adb(device, "uninstall", package)

    async def launch_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "monkey", "-p", package, "-c",
                        "android.intent.category.LAUNCHER", "1")

    async def stop_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "am", "force-stop", package)

    async def clear_app(self, device: Device, package: str) -> None:
        await self._adb(device, "shell", "pm", "clear", package)

    # --------- 输入法管理 ---------
    async def list_input_methods(self, device: Device) -> list[dict]:
        """列出所有输入法及启用/激活状态。"""
        # 用 -s 获取简洁 ID 列表，比 -a 输出更易解析
        code, out, err = await self._adb(device, "shell", "ime", "list", "-s")
        if code != 0:
            raise DeviceCommandError(
                device.id, "列出输入法",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        ids = [l.strip() for l in out.decode("utf-8", "ignore").splitlines() if l.strip()]
        
        # 获取当前默认 IME
        code2, out2, _ = await self._adb(
            device, "shell", "settings", "get", "secure", "default_input_method"
        )
        active_id = out2.decode("utf-8", "ignore").strip() if code2 == 0 else ""
        
        methods = []
        for mid in ids:
            # 检查每个 IME 是否启用（ime is-enabled 返回 "enabled" 或 "disabled"）
            code3, out3, _ = await self._adb(device, "shell", "ime", "is-enabled", mid)
            raw = out3.decode("utf-8", "ignore").strip().lower() if code3 == 0 else ""
            enabled = "enabled" in raw and "not" not in raw and "disabled" not in raw
            methods.append({
                "id": mid,
                "enabled": enabled,
                "active": (mid == active_id),
            })
        
        return methods

    async def get_active_input_method(self, device: Device) -> str:
        """获取当前默认输入法 ID。"""
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
        """设置默认输入法。"""
        await self._adb(device, "shell", "ime", "set", ime_id)

    async def enable_input_method(self, device: Device, ime_id: str) -> None:
        """启用指定输入法。"""
        await self._adb(device, "shell", "ime", "enable", ime_id)

    async def disable_input_method(self, device: Device, ime_id: str) -> None:
        """禁用指定输入法。"""
        await self._adb(device, "shell", "ime", "disable", ime_id)

    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        code, out, err = await self._adb(device, "shell", "ls", "-p", path)
        # 只有「命令成功但没输出」才是真的空目录；命令失败（路径不存在/无权限）
        # 必须报错，否则前端把「打不开」显示成「这个目录是空的」。
        if code != 0:
            raise DeviceCommandError(
                device.id, f"读取目录 {path}",
                err.decode(errors="replace").strip() or f"adb 退出码 {code}",
            )
        if not out:
            return []
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
        from ..preview import render_frame

        theme = getattr(device, "skin", "ios") or "ios"
        await self._ensure_alive(device)

        # 始终尝试真实 ADB 截图，保证操控画面实时更新
        code, out, err = await self._adb(device, "exec-out", "screencap", "-p")
        if code == 0 and out:
            return "data:image/png;base64," + base64.b64encode(out).decode("ascii")

        # ADB 截图失败时回退到皮肤图（设备失联等场景）
        if not device.current_url:
            return render_frame(device.name, None, device.fingerprint or {}, theme=theme)

        raise DeviceUnreachable(
            device.id, self._serial(device),
            err.decode(errors="replace").strip() or "screencap 返回空数据",
        )

    async def apply_skin(self, device: Device, theme: str, progress=None) -> None:
        """真机换肤：iOS 桌面（Lawnchair 4列/Dock/squircle）+ 主题壁纸 + 容器重启。

        deploy/ios-skin/apply-ios-skin.sh 已在真机验证过的流程的 API 移植：
          1) 装 Lawnchair（app/skins/lawnchair.apk，如未装）并 set-home-activity
          2) 重排 launcher.db：应用铺进 4 列网格 + Dock（重启后随开机加载）
          3) 主题壁纸 put_archive 写进 /data/system/users/0/wallpaper
          4) 整机重启 —— redroid 硬约束：`cmd wallpaper` 空实现、位图缓存在
             system_server，只有重启后 WallpaperManagerService 才从文件重读
          5) 开机后合并 Lawnchair 偏好（4列/Dock4/squircle 圆角）——必须在开机
             迁移之后写才留得住，且 key 均为 String 型（int 会崩启动器）
        耗时约 1–2 分钟（首次含装启动器），由调用方作为后台任务运行；
        progress(phase) 逐步上报：launcher/grid/wallpaper/reboot/prefs。
        """
        import io
        import tarfile

        async def _report(phase: str) -> None:
            if progress is not None:
                await progress(phase)

        # 壁纸选型：与 preview._svg_home 相同的 rid 公式（seed/name 求和取模），
        # 保证真机壁纸与预览渲染同款；分档文件缺失回退旧的单档壁纸
        rid = sum(ord(ch) for ch in ((device.fingerprint or {}).get("seed", "") or device.name)) % 3
        wp = os.path.join(_SKIN_DIR, f"wallpaper_{theme}_{rid}.png")
        if not os.path.exists(wp):
            wp = os.path.join(_SKIN_DIR, f"wallpaper_{theme}.png")
        if not os.path.exists(wp):
            return
        cref = device.backend_ref or f"redroid_{device.id}"
        container = await asyncio.to_thread(self.docker.containers.get, cref)
        serial = self._serial(device)
        # 后端/VM 重启后 adb server 是空的，必须先 connect，否则 -s serial 的
        # pm/dumpsys 全部静默失败 → _ensure_launcher 拿不到 pkg → 网格/偏好被跳过；
        # 且必须先显式起 server（否则 connect 自动 fork 的 server 会挂死 _run）。
        # 预检：确认 adb 真正可达（容器刚重启/批量场景下 connect 可能要几秒），
        # 15s 内不可达则明确失败 —— 宁可让前端显示「换肤失败」重试，也不要
        # 静默降级成只落壁纸（会表现为"换肤没效果"）。
        await _adb_server_up()
        reachable = False
        for _ in range(5):
            await _run(settings.adb_path, "connect", serial)
            code, out, _ = await self._adb(device, "shell", "getprop", "sys.boot_completed")
            if code == 0 and out.strip() == b"1":
                reachable = True
                break
            await asyncio.sleep(3)
        if not reachable:
            raise TimeoutError(f"{serial} adb 不可达，换肤中止（设备未开机完成或 adb 连接异常）")

        # 1) iOS 风启动器（Lawnchair）就位并设为默认 HOME
        await _report("launcher")
        pkg = await self._ensure_launcher(device, container)

        # 2) iOS 网格/Dock：重排 launcher.db（失败不阻断壁纸流程）
        if pkg:
            await _report("grid")
            try:
                await self._populate_grid(device, container, pkg, theme)
            except Exception:  # noqa: BLE001
                pass

        # 3) 壁纸：打成 tar，put_archive 到 /data/system/users/0/（属主 1000:1000）
        await _report("wallpaper")
        with open(wp, "rb") as f:
            data = f.read()

        def _write_wallpaper() -> None:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                for member in ("wallpaper", "wallpaper_orig"):
                    ti = tarfile.TarInfo(member)
                    ti.size = len(data)
                    ti.mode = 0o600
                    ti.uid = ti.gid = 1000
                    tar.addfile(ti, io.BytesIO(data))
            container.put_archive("/data/system/users/0", buf.getvalue())

        await asyncio.to_thread(_write_wallpaper)

        # 4) 整机重启，开机时壁纸/网格一起加载；轮询开机完成 + 重连 adb（上限 ~120s）
        await _report("reboot")
        await asyncio.to_thread(container.restart)
        booted = False
        for _ in range(40):
            await asyncio.sleep(3)
            await _run(settings.adb_path, "connect", serial)
            code, out, _ = await self._adb(device, "shell", "getprop", "sys.boot_completed")
            if code == 0 and out.strip() == b"1":
                booted = True
                break
        if not booted:
            raise TimeoutError(f"{cref} 重启后 120s 内未完成开机")

        # 5) 开机后合并 Lawnchair 偏好（squircle/4列/Dock），并回到主屏呈现
        if pkg:
            await _report("prefs")
            # iOS 手势导航条：三键导航 → 手势小白条（更贴 iOS home indicator）。
            # overlay 状态写在 /data/system/overlays.xml，重启保持，幂等可重复执行。
            await self._adb(
                device, "shell", "cmd", "overlay", "enable",
                "com.android.internal.systemui.navbar.gestural",
            )
            await self._merge_launcher_prefs(container, pkg, device.width, device.height)
            # 网格补写：新装设备开机加载可能仍按旧 4x4 网格删掉 cellY>=4 的行
            # （pref_numRows 要等上面 prefs 合并后才生效），此处按最终 prefs 再写一遍
            try:
                await self._populate_grid(device, container, pkg, theme)
            except Exception:  # noqa: BLE001
                pass
            await self._adb(
                device, "shell", "am", "start",
                "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
            )

    async def _ensure_launcher(self, device: Device, container) -> str | None:
        """确保 Lawnchair 已安装并为默认 HOME；返回包名（无法就位则返回 None）。"""
        _, out, _ = await self._adb(device, "shell", "pm", "list", "packages")
        pkg = None
        for line in out.decode(errors="replace").splitlines():
            if "lawnchair" in line:
                pkg = line.strip().removeprefix("package:")
                break
        if pkg is None:
            apk = os.path.join(_SKIN_DIR, "lawnchair.apk")
            if not os.path.exists(apk):
                import logging

                logging.getLogger("redroid").warning(
                    "缺少 %s，本次换肤仅落地壁纸（补齐：deploy/ios-skin/fetch-lawnchair.sh）", apk
                )
                return None
            code, _, _ = await self._adb(device, "install", "-r", apk)
            if code != 0:
                return None
            pkg = "ch.deletescape.lawnchair"
        # 预授权存储权限，避免首启弹「允许访问照片/媒体」对话框挡住桌面
        for perm in ("android.permission.READ_EXTERNAL_STORAGE", "android.permission.WRITE_EXTERNAL_STORAGE"):
            await self._adb(device, "shell", "pm", "grant", pkg, perm)
        # 解析 HOME activity → 设为默认桌面 → 先跑一次生成 launcher.db/偏好
        _, out, _ = await self._adb(
            device, "shell", "cmd", "package", "resolve-activity",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME", pkg,
        )
        act = None
        for tok in out.decode(errors="replace").split():
            if tok.startswith("name="):
                act = tok[5:].strip()
                break
        if act:
            await self._adb(device, "shell", "cmd", "package", "set-home-activity", f"{pkg}/{act}")
            await self._adb(
                device, "shell", "am", "start",
                "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME",
            )
            # 等 Lawnchair 首次运行建库（新装设备 launcher.db 要跑一次才有）
            db = f"/data/data/{pkg}/databases/launcher.db"
            for _ in range(5):
                rc = await asyncio.to_thread(container.exec_run, ["sh", "-c", f"test -f {db}"])
                if rc.exit_code == 0:
                    break
                await asyncio.sleep(2)
        return pkg

    async def _populate_grid(self, device: Device, container, pkg: str, theme: str = "ios") -> None:
        """把设计稿桌面（ios_layout，20 条目全 itemType=1 + 图标 BLOB）写进 launcher.db。

        deploy/ios-skin/populate-grid.py 的进程内移植：容器 get_archive 拉 db →
        本地 sqlite3 重写 favorites → put_archive 推回（容器内 sqlite3 会 abort，不能用）。
        图标资产（app/skins/icons/{theme}/）缺失时回退旧的「真实应用铺网格」逻辑。
        """
        import re
        import sqlite3
        import tarfile
        import tempfile
        import time as _time

        from .ios_layout import build_favorites

        # 应用清单（排除启动器自身）：设计稿路径用于 app 条目降级判断；旧路径用于铺网格
        _, out, _ = await self._adb(
            device, "shell", "cmd", "package", "query-activities", "--brief",
            "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER",
        )
        comps = sorted(
            {
                m
                for m in re.findall(r"[a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+", out.decode(errors="replace"))
                if not m.startswith(f"{pkg}/")
            }
        )
        if not comps:
            return

        # 设计稿桌面行（图标 BLOB 已验证像素级呈现且免疫图标形状开关）；资产缺失 → None 走旧网格
        design_rows: list[dict] | None = None
        if os.path.isdir(os.path.join(_SKIN_DIR, "icons", theme)):
            try:
                design_rows = build_favorites(set(comps), os.path.join(_SKIN_DIR, "icons"), theme)
            except FileNotFoundError:
                design_rows = None

        apps: list[tuple[str, str]] = []
        if not design_rows:  # 旧逻辑才需要逐个 dumpsys 取标题
            for comp in comps:
                _, dout, _ = await self._adb(device, "shell", "dumpsys", "package", comp)
                m = re.search(rb"label=(\S+)", dout)
                title = m.group(1).decode(errors="replace") if m else comp.split("/")[0].rsplit(".", 1)[-1]
                apps.append((title, comp))

        db_remote = f"/data/data/{pkg}/databases/launcher.db"

        def _pull_db() -> bytes:
            import io as _io

            stream, _stat = container.get_archive(db_remote)
            with tarfile.open(fileobj=_io.BytesIO(b"".join(stream))) as tar:
                f = tar.extractfile(tar.getmembers()[0])
                assert f is not None
                return f.read()

        raw = await asyncio.to_thread(_pull_db)
        # 改库前停启动器，避免其进程持有旧数据回写
        await asyncio.to_thread(container.exec_run, ["sh", "-c", f"am force-stop {pkg}"])

        def _rewrite(raw_db: bytes) -> bytes:
            cols, start_row, dock_slots = 4, 1, 4  # 4 列贴近 iOS；第 0 行留给 QSB
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(raw_db)
                path = tmp.name
            try:
                conn = sqlite3.connect(path)
                cur = conn.cursor()
                cur.execute("DELETE FROM favorites")
                now = int(_time.time() * 1000)
                _id = 1

                def intent(comp: str) -> str:
                    p = comp.split("/")[0]
                    return (
                        "#Intent;action=android.intent.action.MAIN;"
                        "category=android.intent.category.LAUNCHER;launchFlags=0x10200000;"
                        f"package={p};component={comp};end"
                    )

                def ins(title: str, comp: str, cont: int, screen: int, cx: int, cy: int) -> None:
                    nonlocal _id
                    cur.execute(
                        "INSERT INTO favorites (_id,title,intent,container,screen,cellX,cellY,"
                        "spanX,spanY,itemType,appWidgetId,modified,restored,profileId,rank,options) "
                        "VALUES (?,?,?,?,?,?,?,1,1,0,-1,?,0,0,0,0)",
                        (_id, title, intent(comp), cont, screen, cx, cy, now),
                    )
                    _id += 1

                if design_rows:
                    # 设计稿桌面：全部 itemType=1 快捷方式 + 设计图标 BLOB（icon 列），
                    # 位置由 ios_layout 给定（主屏 cellY 1..4 共 4 行 + Dock screen 0..3）
                    for r in design_rows:
                        cur.execute(
                            "INSERT INTO favorites (_id,title,intent,container,screen,cellX,cellY,"
                            "spanX,spanY,itemType,appWidgetId,icon,modified,restored,profileId,rank,options) "
                            "VALUES (?,?,?,?,?,?,?,1,1,1,-1,?,?,0,0,0,0)",
                            (_id, r["title"], r["intent"], r["container"], r["screen"],
                             r["cellX"], r["cellY"], r["icon"], now),
                        )
                        _id += 1
                else:
                    for i, (title, comp) in enumerate(apps):
                        ins(title, comp, -100, 0, i % cols, start_row + i // cols)
                    for slot, (title, comp) in enumerate(apps[:dock_slots]):
                        ins(title, comp, -101, slot, 0, 0)
                # 清理 workspaceScreens：分辨率切换后可能残留旧的屏数记录，
                # 确保只有 _id=0 的主屏页（screenRank=0）存在，避免多屏空页导致图标跨页分散。
                cur.execute("DELETE FROM workspaceScreens WHERE _id != 0")
                row = cur.execute("SELECT 1 FROM workspaceScreens WHERE _id=0").fetchone()
                if row:
                    cur.execute("UPDATE workspaceScreens SET screenRank=0, modified=? WHERE _id=0", (now,))
                else:
                    cur.execute("INSERT INTO workspaceScreens (_id,screenRank,modified) VALUES (0,0,?)", (now,))
                conn.commit()
                conn.close()
                with open(path, "rb") as f:
                    return f.read()
            finally:
                os.unlink(path)

        new_db = await asyncio.to_thread(_rewrite, raw)

        def _push_db() -> None:
            import io as _io

            buf = _io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                ti = tarfile.TarInfo("launcher.db")
                ti.size = len(new_db)
                ti.mode = 0o660
                tar.addfile(ti, _io.BytesIO(new_db))
            container.put_archive(f"/data/data/{pkg}/databases", buf.getvalue())
            container.exec_run(
                [
                    "sh", "-c",
                    f"rm -f {db_remote}-journal; "
                    f"own=$(stat -c '%u:%g' /data/data/{pkg}/databases); "
                    f"chown $own {db_remote}; chmod 660 {db_remote}",
                ]
            )

        await asyncio.to_thread(_push_db)

    async def _merge_launcher_prefs(self, container, pkg: str, width: int = 0, height: int = 0) -> None:
        """合并 Lawnchair 偏好：4 列 + 动态行数 + Dock4 + squircle 圆角蒙版。

        根据新分辨率高度动态计算 pref_numRows：
        - 720p (1280) → 5 行
        - 1080p (1920) → 6 行
        - 1440p (2560+) → 7-8 行

        坑（apply-ios-skin.sh 验证过）：整体覆盖 XML 会被 Lawnchair 开机迁移重置，
        必须在 </map> 前「插入」；网格类 key 都是 String 型，写 int 会崩启动器。
        """
        # 动态计算行数：基于 1080p(1920)=6 行的基准
        # 720×1280 → 5 行, 1080×1920 → 6 行, 1080×2400 → 7 行, 1440×2560+ → 8 行
        if height > 0:
            if height <= 1280:
                rows = 5
            elif height <= 1920:
                rows = 6
            elif height <= 2400:
                rows = 7
            else:
                rows = 8
        else:
            rows = 6
        cols = 4
        squircle = "M50,0 C10,0 0,10 0,50 0,90 10,100 50,100 90,100 100,90 100,50 100,10 90,0 50,0 Z"
        prefs = f"/data/data/{pkg}/shared_prefs/{pkg}_preferences.xml"
        script = (
            f"am force-stop {pkg}\n"
            f"P='{prefs}'\n"
            "[ -f \"$P\" ] || printf \"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>"
            "\\n<map>\\n</map>\\n\" > \"$P\"\n"
            "sed -i '/name=\"pref_numRows\"/d;/name=\"pref_numCols\"/d;"
            "/name=\"pref_numHotseatIcons\"/d;/name=\"pref_override_icon_shape\"/d;"
            "/name=\"pref_showDateOrWeather\"/d;/name=\"pref_isHotseatTransparent\"/d;"
            "/name=\"pref_hotseatShouldUseExtractedColors\"/d;"
            "/name=\"pref_hotseatShouldUseCustomOpacity\"/d;"
            "/name=\"pref_hotseatShowArrow\"/d;"
            "/name=\"pref_hotseatCustomOpacity\"/d' \"$P\"\n"
            f"sed -i \"s#</map>#    <string name=\\\"pref_numRows\\\">{rows}</string>\\n"
            f"    <string name=\\\"pref_numCols\\\">{cols}</string>\\n"
            "    <string name=\\\"pref_numHotseatIcons\\\">4</string>\\n"
            f"    <string name=\\\"pref_override_icon_shape\\\">{squircle}</string>\\n"
            "    <boolean name=\\\"pref_showDateOrWeather\\\" value=\\\"false\\\" />\\n"
            "    <boolean name=\\\"pref_isHotseatTransparent\\\" value=\\\"true\\\" />\\n"
            "    <boolean name=\\\"pref_hotseatShouldUseExtractedColors\\\" value=\\\"false\\\" />\\n"
            "    <boolean name=\\\"pref_hotseatShouldUseCustomOpacity\\\" value=\\\"true\\\" />\\n"
            "    <boolean name=\\\"pref_hotseatShowArrow\\\" value=\\\"false\\\" />\\n"
            "    <float name=\\\"pref_hotseatCustomOpacity\\\" value=\\\"0.3\\\" />\\n</map>#\" \"$P\"\n"
            f"own=$(stat -c '%u:%g' /data/data/{pkg}/shared_prefs); chown $own \"$P\"; chmod 660 \"$P\"\n"
        )
        await asyncio.to_thread(container.exec_run, ["sh", "-c", script])

    async def prepare_scrcpy(self, device: Device) -> dict:
        """准备单设备 scrcpy 投屏所需信息。

        工作：
        1) ws_scrcpy_base 为空时按 redroid_host:8100 自动推导
        2) 对目标设备做 `adb forward tcp:8886 localabstract:scrcpy`
           （让 ws-scrcpy 能通过 proxy-adb 连到设备内的 scrcpy-server）
        3) 返回 iframe URL（前端弹窗中可直接嵌入 ws-scrcpy 单设备播放器）与
           proxy WebSocket URL（如需自研播放器可直连该 ws）
        """
        from urllib.parse import urlparse, quote

        # 推导 ws_scrcpy_base
        base = settings.ws_scrcpy_base or f"http://{settings.redroid_host}:8100"
        if base.endswith("/"):
            base = base.rstrip("/")

        # 设备 udid = ADB 序列号（ws-scrcpy 的 proxy-adb 按 udid 路由）
        udid = self._serial(device)  # e.g. "<REDROID_HOST>:5557"

        # 预检设备在线（不可达直接抛 503，给用户明确提示）
        await self._ensure_alive(device)

        # ADB forward：scrcpy-server 在设备侧监听 localabstract:scrcpy
        # ws-scrcpy 通过 udid + remote=tcp:8886 去连它，forward 把 UNIX socket 代理到 TCP。
        # 注：forward 是对 ADB server（这里是远程 <REDROID_HOST> 上的 adbd）生效的，
        # 所以 Windows 端执行 `adb forward` 也会在远程 ADB server 上注册转发。
        code, _, err = await self._adb(
            device, "forward", "tcp:8886", "localabstract:scrcpy"
        )
        if code != 0:
            # 不致命（可能已转发过 / scrcpy-server 稍后才起），记日志即可
            pass

        # 拼装 ws-scrcpy 单设备播放 URL：iframe 里打开它，就能获得
        # Broadway H.264 解码 + 触屏交互 + 键鼠等完整 ws-scrcpy 播放器
        #
        # ws-scrcpy 的 hash 路由约定：
        #   action=stream      -> 进入单设备播放页（不显示设备列表）
        #   udid=<device>      -> 指定要投屏的设备 ADB 序列号
        #   player=broadway    -> 用纯 JS Broadway 解码（兼容性最好，不需要 MSE/WebCodecs）
        #   ws=<innerWs>       -> 指向 proxy-adb 的 WebSocket 地址
        inner_ws_proto = "wss" if base.lower().startswith("https://") else "ws"
        parsed = urlparse(base)
        host_port = parsed.netloc or f"{settings.redroid_host}:8100"
        inner_ws = (
            f"{inner_ws_proto}://{host_port}/"
            f"?action=proxy-adb&remote=tcp:8886&udid={quote(udid)}"
        )
        q = render_quality_params(device.render_quality)
        iframe_url = (
            f"{base}/stream_only.html#!action=stream&udid={quote(udid)}"
            f"&player=broadway&ws={quote(inner_ws)}"
            f"&bitrate={q['bitrate']}&maxFps={q['max_fps']}"
            f"&iFrameInterval={q['i_frame_interval']}"
            f"&maxSize={max(device.width, device.height)}"
        )
        proxy_ws_url = inner_ws

        return {
            "ready": True,
            "ws_scrcpy_base": base,
            "udid": udid,
            "iframe_url": iframe_url,
            "proxy_ws_url": proxy_ws_url,
            "width": device.width,
            "height": device.height,
        }
