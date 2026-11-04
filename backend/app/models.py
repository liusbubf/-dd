"""数据模型：用户 / 分组 / 设备 / 脚本 / 脚本运行记录。"""
from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeviceStatus(str, enum.Enum):
    creating = "creating"
    running = "running"
    stopped = "stopped"
    error = "error"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="admin")
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    devices: Mapped[list["Device"]] = relationship(back_populates="group")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id"), nullable=True)
    status: Mapped[DeviceStatus] = mapped_column(
        Enum(DeviceStatus), default=DeviceStatus.stopped, index=True
    )

    # 编排后端引用（容器 id / 模拟器 id）与 adb 端口
    backend_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    adb_port: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 显示参数
    width: Mapped[int] = mapped_column(Integer, default=1080)
    height: Mapped[int] = mapped_column(Integer, default=1920)
    dpi: Mapped[int] = mapped_column(Integer, default=480)
    # 原始显示参数（V5）：切换前保存，用于「恢复原始分辨率/密度」；
    # 历史设备由 ensure_schema 回填为当前值。
    orig_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orig_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    orig_dpi: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 投屏渲染质量（V5）：low | medium | high。
    # 仅影响 scrcpy 投屏的 maxFps / bitrate；不做「旧版/新版渲染器」空开关。
    render_quality: Mapped[str] = mapped_column(String(16), default="medium")

    # 皮肤主题（一键换肤）：ios | sunset | glass
    skin: Mapped[str] = mapped_column(String(32), default="ios")

    # 当前浏览器页面（demo 主流程：每台开网页）
    current_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # 一机一码：设备标识 + 浏览器指纹 + 网络，整体存 JSON
    fingerprint: Mapped[dict] = mapped_column(JSON, default=dict)

    # 一键新机：累计次数 / 最近一次时间 / 当前状态（idle/renewing/failed）
    renew_count: Mapped[int] = mapped_column(Integer, default=0)
    last_renew_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    renew_state: Mapped[str] = mapped_column(String(16), default="idle")

    # 设备池占用：占用人 / 占用时间（设备农场多人协作时避免抢同一台）
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 到期时间：云机租期/测试期，前端按剩余时长展示与 24h 内提醒
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 绑定的 IP 资源（IP 资源池，NULL 表示未绑定）
    ip_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 设备归属者（V3）：共享操作的判定依据。历史设备的 owner_id 为空，
    # 视为平台设备，仅 admin+ 可管理共享；不提供转移归属接口。
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 租户字段预留（V3 决策：同租户共享先行，跨租户转移暂不实现，接口不开放）
    tenant_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    # 封禁状态：合规风控用
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    banned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    banned_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    group: Mapped[Group | None] = relationship(back_populates="devices")


class DeviceSnapshot(Base):
    """设备数据快照（应用/账号/文件），用于快速回滚与黄金模板。

    注意：快照只保存 /data 数据，不包含设备身份（props 在容器创建时注入）；
    恢复后身份仍以设备当前记录为准。
    """

    __tablename__ = "device_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="creating", index=True)
    # 后端引用：Redroid 为快照文件名，模拟器为内存 key
    backend_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DeviceShare(Base):
    """设备共享（V3）：同租户内把设备以 viewer 级授权给其他用户。

    撤销采用软删除（revoked_at 置位），撤销后立即失效；不提供跨租户转移接口。
    共享只记录授权关系，不改变任何写操作的角色门槛（写仍要求 operator+）。
    """

    __tablename__ = "device_shares"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    # 被共享用户 id
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 授予人（用户名快照，便于审计展示）
    granted_by: Mapped[str] = mapped_column(String(64), default="")
    granted_by_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # 撤销时间；NULL 表示仍有效
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    revoked_by: Mapped[str] = mapped_column(String(64), default="")


class DeviceResetEvent(Base):
    """测试环境重置流水（V3.1）：冷却、每日配额与审计的依据。

    只记录平台侧发起的重置/重建动作，用于防止误操作和批量滥用；
    不记录也不推断设备指纹与任何第三方检测结果。
    """

    __tablename__ = "device_reset_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class Script(Base):
    __tablename__ = "scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    # 步骤列表：[{action, ...params}]，对齐 Airtest .air 用例的抽象
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ScriptRun(Base):
    __tablename__ = "script_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("scripts.id"))
    status: Mapped[str] = mapped_column(String(32), default="running")  # running/success/failed
    # 逐设备结果：[{device_id, name, status, steps:[{action, ok, ts}]}]
    results: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CloudFile(Base):
    """云盘文件：共享空间里上传的资源，可一键下发到多台云机。"""

    __tablename__ = "cloud_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    # image/video/apk/document/other，前端按分类展示
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # 服务端落盘文件名（UUID 前缀，避免重名/路径穿越）
    stored_name: Mapped[str] = mapped_column(String(255), unique=True)
    uploaded_by: Mapped[str] = mapped_column(String(64), default="")
    # 归属用户：普通用户只能看到自己的文件；admin/superadmin 看全部
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    # 公共文件对所有登录用户可见（仅 admin+ 可设置）
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CloudPushJob(Base):
    """云盘下发任务：落库以便进程重启后仍能查历史与结果。

    进程重启时把残留 running 标记为 interrupted（见 database.init_db），
    而不是让任务凭空消失。
    """

    __tablename__ = "cloud_push_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # running / done / partial / failed / interrupted
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    done: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    remote_dir: Mapped[str] = mapped_column(String(512), default="/sdcard/Download")
    # 逐项结果：[{device_id, device_name, file_id, file_name, status, error}]
    items: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(64), default="", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class IpResource(Base):
    """IP 资源池：出口 IP / 代理端口，供设备绑定与连通性探测。"""

    __tablename__ = "ip_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    port: Mapped[int] = mapped_column(Integer, default=0)
    username: Mapped[str] = mapped_column(String(128), default="")
    password: Mapped[str] = mapped_column(String(255), default="")
    # available/in_use/disabled
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)
    group_name: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 最近一次连通性探测结果：unknown/ok/failed
    test_result: Mapped[str] = mapped_column(String(16), default="unknown")
    test_detail: Mapped[str] = mapped_column(Text, default="")
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class DownloadTask(Base):
    """下载中心任务（V2-3）：CSV 报表 / 批量截图 / logcat。

    生成物落云盘目录（复用 cloud_files 存储与下载接口），本表只记录任务元数据，
    因此不新造一套存储。任务同步生成，结束即 done / failed，不会出现半途 running。
    """

    __tablename__ = "download_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # report_csv / screenshots / logcat
    kind: Mapped[str] = mapped_column(String(16), index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    # done / failed
    status: Mapped[str] = mapped_column(String(16), default="done", index=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    # 生成物在云盘中的记录；失败时为 None。走既有 /cloud-disk/files/{id}/download 下载。
    cloud_file_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    # 生成参数（设备 id / logcat 行数），便于复盘与重新生成
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), default="", index=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
