"""平台配置。所有可调项集中在此，通过环境变量或 .env 覆盖。"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv

# 加载 .env 全部变量到 os.environ（DOCKER_HOST 等非 CLOUD_ 前缀的也需要）
load_dotenv()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLOUD_", extra="ignore")

    # --- 基础 ---
    app_name: str = "X86 云手机平台"
    api_prefix: str = "/api"
    debug: bool = True
    # 生产（debug=False）下遇到默认密钥/口令直接拒绝启动；如需临时跳过设为 false
    strict_security: bool = True

    # --- 数据库 ---
    # dev 默认 SQLite（零依赖）；生产改为 postgresql+asyncpg://user:pass@host/db
    database_url: str = "sqlite+aiosqlite:///./cloud_platform.db"

    # --- 鉴权（JWT）---
    jwt_secret: str = "change-me-in-production-please"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # --- 登录防护（V2-1）---
    # 图形验证码默认开启（5 分钟、一次性）；自动化测试通过 CLOUD_LOGIN_CAPTCHA_ENABLED=false 关闭
    login_captcha_enabled: bool = True
    # 同一「用户名 + IP」窗口内失败次数与锁定时长
    login_fail_limit: int = 5
    login_fail_window: int = 900
    login_lock_seconds: int = 300

    # --- 初始管理员（首启动自动播种）---
    # 默认 admin/admin123 仅为本地演示用；生产必须通过环境变量覆盖（debug=False 时未改会拒绝启动）
    admin_username: str = "admin"
    admin_password: str = "admin123"

    # --- 预置用户（首次启动自动创建，团队共享）---
    # JSON 数组格式，如: [{"username":"op1","password":"pwd","role":"operator"},...]
    # role 可选: superadmin / admin / operator / viewer
    # 默认预留一个演示账号，便于本地前端快速体验。
    seed_users: list[dict] = [{
        "username": "demo",
        "password": "demo123",
        "role": "operator",
    }]

    # --- 设备编排后端 ---
    # simulator：无需 Docker，可在任意平台跑 demo（macOS/Windows/Linux）
    # redroid：真实 Docker + Redroid，仅 Linux 宿主机
    # physical：纳管真实手机（USB / 无线调试），用于 QA 设备池与远程操控
    device_backend: Literal["simulator", "redroid", "physical"] = "simulator"

    # Redroid 后端参数（device_backend=redroid 时生效）
    redroid_image: str = "redroid/redroid:12.0.0_64only-latest"
    redroid_data_dir: str = "/data/redroid"
    redroid_base_adb_port: int = 5555
    redroid_gpu_mode: str = "guest"  # host=宿主 GPU 加速(Intel/AMD)，guest=软件渲染
    redroid_host: str = "localhost"  # Redroid 服务器地址（本地开发时指向远程服务器）
    adb_path: str = "adb"  # ADB 可执行文件路径
    adb_timeout: float = 15.0  # 单条 adb 命令超时（秒），防止挂死耗尽线程池

    # --- 批量操作 ---
    # 同时下发的设备数上限：500 台规模下无上限会瞬间打爆 adb/docker
    batch_concurrency: int = 8
    # 一键新机并发：每台要删容器/清数据/重建/等开机，默认 2 台
    renew_concurrency: int = 2

    # --- 测试环境重置治理（V3.1）---
    # 仅约束平台自身的重置/重建操作：按设备冷却 + 按用户每日配额 + 归属校验 + 审计。
    # 不涉及设备指纹算法，也不改变任何第三方检测行为。
    reset_governance_enabled: bool = True
    reset_cooldown_seconds: int = 60
    reset_daily_quota: int = 20

    # --- 输入校验 ---
    # APK 下载地址主机白名单；空列表 = 允许任意 http/https 主机
    apk_url_allow_hosts: list[str] = []

    # --- ws-scrcpy 投屏 ---
    # ws-scrcpy 服务地址（默认与 redroid_host 同机，端口 8100）
    # 前端 iframe / WebSocket 直接连接它拉 H.264 流
    ws_scrcpy_base: str = ""  # 空 => 自动填 "http://{redroid_host}:8100"

    # --- 网络/代理位（一机一码：独立出口 IP）---
    # 代理池，形如 ["socks5://1.2.3.4:1080", "http://5.6.7.8:8080"]
    proxy_pool: list[str] = []

    # --- CORS ---
    # 默认只放行本地前端开发端口；生产按实际域名配置，不要用 "*"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:4173"]

    # --- 日志 ---
    # INFO / WARNING / DEBUG；不会打印请求体，避免口令与 token 落日志
    log_level: str = "INFO"
    # 云盘文件落盘目录（空=默认 backend/cloud_disk_storage），可用绝对路径指向挂载盘
    cloud_disk_dir: str = ""

    # --- 到期自动回收（默认关闭，避免误伤演示环境）---
    # 开启后按 interval 扫描 expires_at 已到期的设备：停机 + 释放 IP + 写审计
    expire_sweep_enabled: bool = False
    expire_sweep_interval: int = 300

    # --- 设备同步（从服务器自动同步设备列表）---
    # 配置后，本地作为从节点，定期轮询服务器 API 自动同步设备
    sync_server: str = ""  # 服务器 API 地址，如 http://<SYNC_HOST>:8000/api；空=禁用
    sync_interval: int = 30  # 同步间隔（秒）
    sync_username: str = "admin"  # 服务器登录用户名
    sync_password: str = "admin123"  # 服务器登录密码


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# 出厂默认值：生产环境仍在使用即视为不安全
_DEFAULT_JWT_SECRET = "change-me-in-production-please"
_DEFAULT_ADMIN_PASSWORD = "admin123"


def enforce_security() -> list[str]:
    """检查默认凭据并返回告警列表。

    - 开发模式（debug=True）：只返回告警，不影响本地演示。
    - 生产模式（debug=False）：默认密钥/口令未修改时直接抛错拒绝启动。
    """
    problems: list[str] = []
    if settings.jwt_secret == _DEFAULT_JWT_SECRET:
        problems.append("CLOUD_JWT_SECRET 仍是默认值")
    if settings.admin_password == _DEFAULT_ADMIN_PASSWORD:
        problems.append("CLOUD_ADMIN_PASSWORD 仍是默认值 admin123")
    if settings.sync_server and settings.sync_password == _DEFAULT_ADMIN_PASSWORD:
        problems.append("CLOUD_SYNC_PASSWORD 仍是默认值 admin123")
    if "*" in settings.cors_origins:
        problems.append("CLOUD_CORS_ORIGINS 含通配符 *（已自动关闭 credentials）")

    if problems and not settings.debug and settings.strict_security:
        raise RuntimeError("检测到不安全的默认配置，拒绝启动：\n- " + "\n- ".join(problems))
    return problems
