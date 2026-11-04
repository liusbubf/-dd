"""Pydantic 请求/响应模型（API 契约）。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .config import settings
from .models import DeviceStatus


def _validate_apk_url(url: str) -> str:
    """APK 地址只允许 http/https，且可配置主机白名单。

    安装接口会把 URL 交给设备内组件下载，放任任意 scheme/host 等于开放 SSRF/本地文件访问。
    """
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("apk_url 必须是合法的 http/https 地址")
    allowed = settings.apk_url_allow_hosts
    if allowed and parsed.hostname not in allowed:
        raise ValueError(f"apk_url 主机不在白名单内: {parsed.hostname}")
    return url


def _validate_http_url(url: str) -> str:
    """通用 http/https 校验（用于开网页等），限制长度避免超长串落库。"""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("url 必须是合法的 http/https 地址")
    if len(url) > 2048:
        raise ValueError("url 过长（上限 2048）")
    return url


# --------- 鉴权 ---------
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    captcha_id: str | None = Field(None, max_length=64)
    captcha_code: str | None = Field(None, max_length=8)


class CaptchaOut(BaseModel):
    captcha_id: str
    image: str
    expires_in: int


class LastLoginInfo(BaseModel):
    at: str
    ip: str | None = None
    location: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    is_banned: bool = False
    banned_at: datetime | None = None
    banned_reason: str | None = None

    class Config:
        from_attributes = True


class BanUserRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class UnbanUserRequest(BaseModel):
    pass


class BanDeviceRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class UnbanDeviceRequest(BaseModel):
    pass


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    last_login: LastLoginInfo | None = None


# --------- 分组 ---------
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    parent_id: int | None = Field(None, ge=1)


class GroupOut(BaseModel):
    id: int
    name: str
    parent_id: int | None
    device_count: int = 0

    class Config:
        from_attributes = True


# --------- 设备 ---------
class DeviceCreate(BaseModel):
    name: str | None = Field(None, max_length=128)
    group_id: int | None = Field(None, ge=1)
    width: int = Field(1080, ge=320, le=2160)
    height: int = Field(1920, ge=480, le=3840)
    dpi: int = Field(480, ge=120, le=640)
    target_url: str | None = Field(None, max_length=2048)
    proxy: str | None = Field(None, max_length=512)
    fingerprint_mode: Literal["commercial", "qa"] = "commercial"
    region: str | None = Field(None, max_length=64)


class DeviceBatchCreate(BaseModel):
    count: int = Field(ge=1, le=100)
    name_prefix: str = Field("云手机", min_length=1, max_length=64)
    group_id: int | None = Field(None, ge=1)
    width: int = Field(720, ge=320, le=2160)
    height: int = Field(1280, ge=480, le=3840)
    dpi: int = Field(320, ge=120, le=640)
    target_url: str | None = Field(None, max_length=2048)
    auto_start: bool = True
    fingerprint_mode: Literal["commercial", "qa"] = "commercial"
    region: str | None = Field(None, max_length=64)


class DeviceUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    group_id: int | None = Field(None, ge=1)
    # 到期时间：传 null 表示清空；传时间表示续期/设置租期
    expires_at: datetime | None = None


class DeviceAdopt(BaseModel):
    """纳管一台已连接的真实手机（ADB 序列号来自 /devices/discover）。"""

    serial: str = Field(min_length=1, max_length=128)
    name: str | None = Field(None, max_length=128)
    group_id: int | None = Field(None, ge=1)


class DeviceOut(BaseModel):
    id: int
    name: str
    group_id: int | None
    status: DeviceStatus
    adb_port: int | None
    width: int
    height: int
    dpi: int
    # V5：原始显示参数（用于恢复默认）与投屏渲染质量
    orig_width: int | None = None
    orig_height: int | None = None
    orig_dpi: int | None = None
    render_quality: str = "medium"
    skin: str = "ios"
    current_url: str | None
    fingerprint: dict
    renew_count: int = 0
    last_renew_at: datetime | None = None
    renew_state: str = "idle"
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    expires_at: datetime | None = None
    ip_id: int | None = None
    # 设备归属者（V3 共享判定依据）；历史平台设备为 null
    owner_id: int | None = None
    # 封禁状态
    is_banned: bool = False
    banned_at: datetime | None = None
    banned_reason: str | None = None
    # 以下两项由后端按 expires_at 现算，前端直接展示
    remaining_seconds: int | None = None
    is_expiring_soon: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _fill_remaining(self) -> "DeviceOut":
        if self.expires_at is None:
            return self
        exp = self.expires_at
        if exp.tzinfo is None:  # SQLite 存的是无时区时间，按 UTC 解释
            exp = exp.replace(tzinfo=timezone.utc)
        remaining = (exp - datetime.now(timezone.utc)).total_seconds()
        self.remaining_seconds = max(0, int(remaining))
        self.is_expiring_soon = remaining <= 86400
        return self


class RenewCmd(BaseModel):
    """一键新机参数。

    - hard：清空应用/数据并更换设备身份（Android ID/序列号/IMEI/MAC 全部变化）；
    - clear_data：清空数据但保留设备身份，适合「恢复出厂」但维持账号设备绑定。
    """
    mode: Literal["hard", "clear_data"] = "hard"
    rotate_proxy: bool = False
    keep_url: bool = False


class BatchRenew(RenewCmd):
    device_ids: list[int] = Field(min_length=1)


# --------- 重置两入口（V3） ---------
class ResetConfirm(BaseModel):
    """重置类破坏性操作必须输入设备名二次确认，后端同样校验，避免绕过前端误操作。"""

    confirm_name: str = Field(min_length=1, max_length=128)


# --------- 设备共享（V3，同租户） ---------
class DeviceShareCreate(BaseModel):
    user_id: int = Field(ge=1)


class DeviceShareOut(BaseModel):
    id: int
    device_id: int
    user_id: int
    username: str = ""
    role: str = ""
    granted_by: str
    granted_by_id: int | None = None
    created_at: datetime
    revoked_at: datetime | None = None
    revoked_by: str = ""
    active: bool = True


class ShareCandidateOut(BaseModel):
    id: int
    username: str
    role: str


# --------- 设备快照 ---------
class SnapshotCreate(BaseModel):
    name: str = Field("", max_length=64)


class SnapshotOut(BaseModel):
    id: int
    device_id: int
    name: str
    status: str
    size_bytes: int | None
    note: str
    created_at: datetime

    class Config:
        from_attributes = True


# --------- 单机操控 ---------
class TapCmd(BaseModel):
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)


class SwipeCmd(BaseModel):
    x1: int = Field(ge=0, le=20000)
    y1: int = Field(ge=0, le=20000)
    x2: int = Field(ge=0, le=20000)
    y2: int = Field(ge=0, le=20000)
    duration_ms: int = Field(300, ge=0, le=60000)


class TextCmd(BaseModel):
    text: str = Field(max_length=2000)
    append: bool = False  # True=拼接到输入框已有文字后面，False=直接替换


class KeyCmd(BaseModel):
    key: str = Field(min_length=1, max_length=32)  # back / home / menu / power / volume_up / volume_down / enter


class OpenUrlCmd(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


class InstallCmd(BaseModel):
    apk_url: str

    @field_validator("apk_url")
    @classmethod
    def _check_apk_url(cls, v: str) -> str:
        return _validate_apk_url(v)


class DisplayCmd(BaseModel):
    width: int = Field(ge=320, le=4096)
    height: int = Field(ge=480, le=7680)
    dpi: int = Field(ge=120, le=640)

    @model_validator(mode="after")
    def _limit_pixels_and_ratio(self) -> "DisplayCmd":
        # 非 16:9 允许，但必须有上限：总像素不超过 2160×3840，宽高比限制在 1:4 ~ 4:1。
        if self.width * self.height > 2160 * 3840:
            raise ValueError("分辨率过大：总像素不得超过 2160×3840")
        ratio = self.width / self.height
        if ratio < 0.25 or ratio > 4.0:
            raise ValueError("宽高比超出允许范围（1:4 ~ 4:1）")
        return self


class RenderQualityCmd(BaseModel):
    """投屏渲染质量：low | medium | high。

    说明：本项目没有「旧版/新版渲染器」分支，视频里的渲染模式切换用本项替代；
    它只调整 scrcpy 的 maxFps / bitrate，不改变设备内渲染实现。
    """

    quality: Literal["low", "medium", "high"]


# --------- 输入法管理 ---------
class InputMethodCmd(BaseModel):
    action: str  # list / set / disable / enable
    ime_id: str | None = None  # set 时必填，如 "com.android.adbkeyboard/.AdbKeyboard"


# --------- scrcpy 投屏管理 ---------
class ScrcpyCmd(BaseModel):
    action: str = "prepare"  # prepare / health


# --------- 批量操作 ---------
class BatchTargets(BaseModel):
    # 500 台是文档里的设计规模上限；空列表直接拒绝，避免「批量成功 0 台」的假反馈
    device_ids: list[int] = Field(min_length=1, max_length=500)


class BatchOpenUrl(BatchTargets):
    url: str

    @field_validator("url")
    @classmethod
    def _check_url(cls, v: str) -> str:
        return _validate_http_url(v)


class BatchTap(BatchTargets):
    x: int = Field(ge=0, le=20000)
    y: int = Field(ge=0, le=20000)
    # 主控设备实际分辨率（可选）：传入时按真实分辨率折算，缺省回落 1080×1920 基准
    source_width: int | None = Field(None, ge=200, le=8192)
    source_height: int | None = Field(None, ge=200, le=8192)


class BatchSwipe(BatchTargets):
    x1: int = Field(ge=0, le=20000)
    y1: int = Field(ge=0, le=20000)
    x2: int = Field(ge=0, le=20000)
    y2: int = Field(ge=0, le=20000)
    duration_ms: int = Field(300, ge=0, le=60000)
    source_width: int | None = Field(None, ge=200, le=8192)
    source_height: int | None = Field(None, ge=200, le=8192)


class BatchText(BatchTargets):
    text: str = Field(max_length=2000)


class BatchKey(BatchTargets):
    key: str = Field(min_length=1, max_length=32)


class BatchInstall(BatchTargets):
    apk_url: str

    @field_validator("apk_url")
    @classmethod
    def _check_apk_url(cls, v: str) -> str:
        return _validate_apk_url(v)


class BatchResult(BaseModel):
    total: int
    ok: int
    failed: int
    details: list[dict]


# --------- 脚本录制/回放 ---------
class ScriptStep(BaseModel):
    action: str  # open_url / tap / swipe / text / key / wait
    params: dict = {}


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field("", max_length=2000)
    steps: list[ScriptStep] = Field(default_factory=list, max_length=500)


class ScriptOut(BaseModel):
    id: int
    name: str
    description: str
    steps: list
    created_at: datetime

    class Config:
        from_attributes = True


class ScriptRunRequest(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=500)


class ScriptRunOut(BaseModel):
    id: int
    script_id: int
    status: str
    results: list
    created_at: datetime

    class Config:
        from_attributes = True


# --- 云盘 / 云端下发 ---------------------------------------------------------

CLOUD_CATEGORIES = ("image", "video", "apk", "document", "other")


class CloudFileOut(BaseModel):
    id: int
    name: str
    category: str
    size_bytes: int
    uploaded_by: str
    owner_id: int | None = None
    is_public: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CloudFileUpdate(BaseModel):
    """仅 admin+ 可改：把文件设为公共（或收回）。"""

    is_public: bool


class CloudPushRequest(BaseModel):
    """批量下发：最多 20 个文件 × 500 台设备，避免一次点爆后端。"""

    file_ids: list[int] = Field(min_length=1, max_length=20)
    device_ids: list[int] = Field(min_length=1, max_length=500)
    remote_dir: str = Field("/sdcard/Download", min_length=1, max_length=512)


# --- 下载中心 ---------------------------------------------------------------

DOWNLOAD_KINDS = ("report_csv", "screenshots", "logcat")


class DownloadCreate(BaseModel):
    """创建下载任务：报表不需要设备；截图/日志必须选设备（上限见路由内校验）。"""

    kind: Literal["report_csv", "screenshots", "logcat"]
    device_ids: list[int] = Field(default_factory=list, max_length=50)
    lines: int = Field(200, ge=1, le=1000, description="logcat 拉取行数")
    title: str = Field("", max_length=64)


class DownloadTaskOut(BaseModel):
    id: int
    kind: str
    title: str
    status: str
    filename: str
    size_bytes: int
    error: str
    device_ids: list[int] = Field(default_factory=list)
    created_by: str
    owner_id: int | None = None
    cloud_file_id: int | None = None
    # 前端直接用它调既有云盘下载接口，不在下载中心另开下载出口
    download_url: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --- IP 资源池 ---------------------------------------------------------------

IP_STATUSES = ("available", "in_use", "disabled")


def _validate_ip(ip: str) -> str:
    import ipaddress

    try:
        ipaddress.ip_address((ip or "").strip())
    except ValueError as exc:
        raise ValueError("ip 必须是合法的 IPv4/IPv6 地址") from exc
    return ip.strip()


class IpResourceCreate(BaseModel):
    ip: str = Field(min_length=1, max_length=64)
    port: int = Field(0, ge=0, le=65535)
    username: str = Field("", max_length=128)
    password: str = Field("", max_length=255)
    status: Literal["available", "in_use", "disabled"] = "available"
    group_name: str = Field("", max_length=64)
    note: str = Field("", max_length=2000)
    expires_at: datetime | None = None

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str) -> str:
        return _validate_ip(v)


class IpResourceUpdate(BaseModel):
    ip: str | None = Field(None, min_length=1, max_length=64)
    port: int | None = Field(None, ge=0, le=65535)
    username: str | None = Field(None, max_length=128)
    password: str | None = Field(None, max_length=255)
    status: Literal["available", "in_use", "disabled"] | None = None
    group_name: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=2000)
    expires_at: datetime | None = None

    @field_validator("ip")
    @classmethod
    def _check_ip(cls, v: str | None) -> str | None:
        return _validate_ip(v) if v is not None else None


class IpResourceOut(BaseModel):
    id: int
    ip: str
    port: int
    username: str
    password: str = ""
    has_password: bool = False
    status: str
    group_name: str
    note: str
    expires_at: datetime | None = None
    test_result: str
    test_detail: str
    last_tested_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="after")
    def _mask_password(self) -> "IpResourceOut":
        """接口不回传完整口令，只回显掩码；绑定由后端直接读库，不影响功能。"""
        if self.password:
            p = self.password
            self.has_password = True
            self.password = (p[:2] + "****" + p[-2:]) if len(p) >= 8 else "****"
        return self


class IpBindRequest(BaseModel):
    device_id: int = Field(ge=1)
    # 绑定后把这台设备的出口 IP 写进指纹，保持与一键新机/代理逻辑一致
    apply_to_fingerprint: bool = True
