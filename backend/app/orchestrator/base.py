"""设备编排后端抽象。

两种实现：
- SimulatorBackend：无需 Docker，任意平台可跑（macOS 上直接演示主流程）。
- RedroidBackend：真实 Docker + Redroid，仅 Linux 宿主机。

上层（routers）只依赖此抽象，切换后端只改配置 CLOUD_DEVICE_BACKEND。
"""
from __future__ import annotations

import abc
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..models import Device


def pick_proxy(current: str | None = None) -> str | None:
    """从代理池里换一个不同出口；池为空时保留原代理。"""
    from ..config import settings

    pool = [p for p in settings.proxy_pool if p]
    if not pool:
        return current
    candidates = [p for p in pool if p != current] or pool
    return random.choice(candidates)


# 投屏渲染质量（V5）：只影响 scrcpy 的帧率上限与码率。
# 本项目没有「旧版/新版渲染器」实现，因此不提供渲染模式切换空开关。
RENDER_QUALITY_PRESETS: dict[str, dict[str, int]] = {
    "low": {"max_fps": 15, "bitrate": 2_000_000, "i_frame_interval": 2},
    "medium": {"max_fps": 30, "bitrate": 8_000_000, "i_frame_interval": 1},
    "high": {"max_fps": 60, "bitrate": 20_000_000, "i_frame_interval": 1},
}


def render_quality_params(quality: str | None) -> dict[str, int]:
    """取渲染质量对应的 scrcpy 参数；未知值回落到 medium。"""
    return RENDER_QUALITY_PRESETS.get(quality or "medium", RENDER_QUALITY_PRESETS["medium"])


class DeviceUnreachable(RuntimeError):
    """设备控制通道不可用（容器停了 / adb 没连上 / 设备 offline）。

    存在的意义是**禁止静默降级**：这类故障过去被各处 `await self._adb(...)` 吞掉，
    表现为「预览有画面、批量报全部成功」，但设备其实早已失联（真实事故）。
    任何拿不到设备的场景都必须抛它，由路由层转成 503 并把设备标记为异常。
    """

    def __init__(self, device_id: int, serial: str = "", detail: str = "") -> None:
        self.device_id = device_id
        self.serial = serial
        self.detail = detail
        msg = f"设备 {device_id} 控制通道不可用"
        if serial:
            msg += f"（{serial}）"
        if detail:
            msg += f"：{detail}"
        super().__init__(msg)


class DeviceCommandError(RuntimeError):
    """设备可达，但这条命令失败了（路径不存在、无权限、pm 报错等）。

    与 DeviceUnreachable 的区别：设备本身是活的。同样**不许静默返回空结果** ——
    过去 list_apps/list_logcat/list_files 失败都返回 []，前端会显示成
    「没有应用 / 没有日志 / 空目录」，把「读不到」伪装成「没有」。
    """

    def __init__(self, device_id: int, what: str, detail: str = "") -> None:
        self.device_id = device_id
        self.what = what
        self.detail = detail
        super().__init__(f"设备 {device_id} {what}失败" + (f"：{detail}" if detail else ""))


@dataclass
class Provisioned:
    """create() 的返回：后端引用 + adb 端口。"""
    backend_ref: str
    adb_port: int


@dataclass
class SnapshotResult:
    """snapshot() 的返回：后端引用（文件名/key）与压缩后大小。"""
    backend_ref: str
    size_bytes: int | None = None


@dataclass
class RenewResult:
    """renew() 的返回：够上层写审计与展示，不包含整份指纹。"""
    device_id: int
    mode: str
    fingerprint_changed: bool = False
    proxy: str | None = None
    current_url: str | None = None
    duration_s: float = 0.0
    warnings: list[str] = field(default_factory=list)


# 新机阶段回调：stopping/wiping/fingerprint/creating/booting/skin/url
RenewProgress = Callable[[str], Awaitable[None]]


class DeviceBackend(abc.ABC):
    name: str = "base"

    @abc.abstractmethod
    async def create(self, device: Device) -> Provisioned:
        """按设备的指纹/显示参数创建实例（不一定启动）。"""

    @abc.abstractmethod
    async def start(self, device: Device) -> None: ...

    @abc.abstractmethod
    async def stop(self, device: Device) -> None: ...

    @abc.abstractmethod
    async def destroy(self, device: Device) -> None: ...

    async def check_health(self, device: Device) -> bool | None:
        """巡检控制通道是否可用；None = 该后端不支持（巡检时跳过）。"""
        return None

    @abc.abstractmethod
    async def renew(
        self,
        device: Device,
        *,
        mode: str = "hard",
        rotate_proxy: bool = False,
        keep_url: bool = False,
        progress: RenewProgress | None = None,
    ) -> RenewResult:
        """一键新机。

        - mode="hard"：清空数据 + 重新生成设备身份（新 seed），等价于换一台新手机；
        - mode="clear_data"：清空数据但保留设备身份（Android ID/序列号/MAC 不变）。

        两种模式都必须真正重建实例：Redroid 的 ro.* 与代理环境变量只在容器创建时
        注入，改库不重建不会生效。
        """

    # --- 快照 / 恢复 ---
    @abc.abstractmethod
    async def snapshot(self, device: Device, snapshot_id: int) -> SnapshotResult:
        """保存设备当前数据，返回可再次定位它的 backend_ref。"""

    @abc.abstractmethod
    async def restore_snapshot(self, device: Device, backend_ref: str) -> None:
        """用快照覆盖设备当前数据并重启到可用状态。"""

    @abc.abstractmethod
    async def delete_snapshot(self, device: Device, backend_ref: str) -> None:
        """删除快照数据（DB 记录由服务层删除）。"""

    # --- 操控 ---
    @abc.abstractmethod
    async def open_url(self, device: Device, url: str) -> None: ...

    @abc.abstractmethod
    async def tap(self, device: Device, x: int, y: int) -> None: ...

    @abc.abstractmethod
    async def swipe(self, device: Device, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None: ...

    @abc.abstractmethod
    async def input_text(self, device: Device, text: str, append: bool = False) -> None: ...

    @abc.abstractmethod
    async def key(self, device: Device, key: str) -> None: ...

    async def unlock(self, device: Device) -> None:
        """清除设备屏幕锁（keyguard）。

        默认实现直接返回成功（Simulator 无真实锁屏）；Redroid / 实体机各自覆盖为
        真实 adb 命令。失败必须抛异常，禁止静默成功。
        """

    @abc.abstractmethod
    async def install(self, device: Device, apk_url: str) -> None: ...

    @abc.abstractmethod
    async def screenshot(self, device: Device) -> str:
        """返回一帧画面的 data URL。"""

    # --- 已装应用（GM-003 设备详情聚合）---
    async def list_apps(self, device: Device) -> list[str]:
        """返回设备已安装应用的包名列表。

        默认实现返回空列表（具体后端可覆盖），确保未实现的后端不会报错。
        """
        return []

    # --- 设备日志（7.5.3 logcat）---
    async def list_logcat(self, device: Device, lines: int = 200) -> list[str]:
        """返回最近 N 行 logcat；默认空（具体后端覆盖）。"""
        return []

    # --- 分辨率/DPI 运行时切换（CP-007）---
    async def set_display(self, device: Device, width: int, height: int, dpi: int) -> None:
        """运行时切换分辨率/DPI；默认仅更新记录（具体后端覆盖以真正下发）。"""
        device.width, device.height, device.dpi = width, height, dpi

    # --- 应用管理（GM-101/102/103/106）---
    async def uninstall_app(self, device: Device, package: str) -> None:
        """卸载应用；默认空实现。"""

    async def launch_app(self, device: Device, package: str) -> None:
        """启动应用；默认空实现。"""

    async def stop_app(self, device: Device, package: str) -> None:
        """强停应用；默认空实现。"""

    async def clear_app(self, device: Device, package: str) -> None:
        """清除应用数据；默认空实现。"""

    # --- 文件互传（PC-104 / 7.2.4）---
    async def list_files(self, device: Device, path: str = "/sdcard/") -> list[dict]:
        """列目录：返回 [{name, is_dir}]；默认空。"""
        return []

    async def push_file(self, device: Device, local_path: str, remote_path: str) -> None:
        """上传本地文件到设备；默认空。"""

    async def pull_file(self, device: Device, remote_path: str, local_path: str) -> bool:
        """下载设备文件到本地；成功返回 True；默认 False。"""
        return False

    async def delete_file(self, device: Device, remote_path: str) -> None:
        """删除设备文件/目录；默认空。"""

    async def apply_skin(self, device: Device, theme: str, progress=None) -> None:
        """把皮肤主题真正落到设备（如装启动器/换壁纸并重启）；默认空（模拟后端无真机）。

        progress: 可选 async 回调 progress(phase: str)，用于向前端上报落地进度
        （phase 取值见 redroid 实现：launcher/grid/wallpaper/reboot/prefs）。
        注意：真机实现通常耗时（含重启），应由调用方作为后台任务运行。
        """

    # --- scrcpy 低延迟投屏 ---
    async def prepare_scrcpy(self, device: Device) -> dict:
        """准备单设备 scrcpy 投屏所需信息。

        返回 { ready, ws_scrcpy_base, udid, iframe_url, proxy_ws_url, width, height }
        ready=False 表示 ws-scrcpy 服务未启动或设备不在线；前端据此提示/禁用。
        默认实现返回 ready=False（模拟后端无真机）。
        """
        return {
            "ready": False,
            "ws_scrcpy_base": "",
            "udid": "",
            "iframe_url": "",
            "proxy_ws_url": "",
            "width": device.width,
            "height": device.height,
        }


def get_backend() -> DeviceBackend:
    from ..config import settings

    if settings.device_backend == "redroid":
        from .redroid import RedroidBackend

        return RedroidBackend()
    if settings.device_backend == "physical":
        from .physical import PhysicalBackend

        return PhysicalBackend()
    from .simulator import SimulatorBackend

    return SimulatorBackend()
