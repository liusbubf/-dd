"""异步 SQLAlchemy 引擎与会话。"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(settings.database_url, echo=False, future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


# 老库补列：create_all 只建新表，不会 ALTER 已有表，这里逐条补齐（重复执行无副作用）。
_ADD_COLUMNS = (
    "ALTER TABLE devices ADD COLUMN skin VARCHAR(32) DEFAULT 'ios'",
    "ALTER TABLE devices ADD COLUMN renew_count INTEGER DEFAULT 0",
    "ALTER TABLE devices ADD COLUMN last_renew_at {ts}",
    "ALTER TABLE devices ADD COLUMN renew_state VARCHAR(16) DEFAULT 'idle'",
    "ALTER TABLE devices ADD COLUMN claimed_by VARCHAR(64)",
    "ALTER TABLE devices ADD COLUMN claimed_at {ts}",
    "ALTER TABLE devices ADD COLUMN expires_at {ts}",
    "ALTER TABLE devices ADD COLUMN ip_id INTEGER",
    "ALTER TABLE devices ADD COLUMN owner_id INTEGER",
    "ALTER TABLE devices ADD COLUMN tenant_id INTEGER",
    "ALTER TABLE devices ADD COLUMN orig_width INTEGER",
    "ALTER TABLE devices ADD COLUMN orig_height INTEGER",
    "ALTER TABLE devices ADD COLUMN orig_dpi INTEGER",
    "ALTER TABLE devices ADD COLUMN render_quality VARCHAR(16) DEFAULT 'medium'",
    "ALTER TABLE devices ADD COLUMN is_banned BOOLEAN DEFAULT FALSE",
    "ALTER TABLE devices ADD COLUMN banned_at {ts}",
    "ALTER TABLE devices ADD COLUMN banned_reason VARCHAR(512)",
    "ALTER TABLE cloud_files ADD COLUMN owner_id INTEGER",
    "ALTER TABLE cloud_files ADD COLUMN is_public BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN last_login_at {ts}",
    "ALTER TABLE users ADD COLUMN last_login_ip VARCHAR(64)",
    "ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE",
    "ALTER TABLE users ADD COLUMN banned_at {ts}",
    "ALTER TABLE users ADD COLUMN banned_reason VARCHAR(512)",
)

# 常用查询字段索引：设备列表按分组过滤、设备池按占用人过滤、到期提醒按到期时间过滤。
# status 已在 models.py 用 index=True 建过；这里只补尚未覆盖的。
_ADD_INDEXES = (
    "CREATE INDEX IF NOT EXISTS ix_devices_group_id ON devices (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_devices_claimed_by ON devices (claimed_by)",
    "CREATE INDEX IF NOT EXISTS ix_devices_expires_at ON devices (expires_at)",
    "CREATE INDEX IF NOT EXISTS ix_devices_owner_id ON devices (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_devices_tenant_id ON devices (tenant_id)",
    "CREATE INDEX IF NOT EXISTS ix_cloud_files_owner_id ON cloud_files (owner_id)",
    "CREATE INDEX IF NOT EXISTS ix_users_is_banned ON users (is_banned)",
)


async def ensure_schema() -> None:
    """幂等补列 + 补索引。

    每条 DDL 必须独立事务：Postgres 下任何语句报错都会作废整个事务，
    而 COMMIT 会被静默降级为 ROLLBACK（不抛异常）。若与上面的 create_all 同事务，
    全新库上这条 ALTER 必因“列已存在”失败（models.py 已定义 skin），
    连带把刚建好的表一起回滚掉，随后 seed() 会报 relation "users" does not exist。
    """
    ts_type = "TIMESTAMP WITH TIME ZONE" if engine.dialect.name == "postgresql" else "DATETIME"
    for ddl in _ADD_COLUMNS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl.format(ts=ts_type)))
        except Exception:
            pass  # 列已存在 / 不支持——忽略
    for ddl in _ADD_INDEXES:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(ddl))
        except Exception:
            pass  # 索引已存在 / 不支持——忽略


async def init_db() -> None:
    # demo 阶段直接建表；生产用 Alembic 迁移（见 docs/已知限制与待办.md）。
    from . import models  # noqa: F401  确保模型已注册到 Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await ensure_schema()

    # V5：历史设备的原始显示参数回填为当前值（只回填一次，幂等）。
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE devices SET orig_width=width, orig_height=height, orig_dpi=dpi "
                "WHERE orig_width IS NULL"
            )
        )

    # 进程重启会丢掉内存里的新机队列：把残留的“新机中”复位，避免永久卡在中间态。
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE devices SET renew_state='idle' WHERE renew_state='renewing'")
        )
    # 下发任务已迁到数据库：重启后把残留的“进行中”标记为中断，保留历史可查。
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE cloud_push_jobs SET status='interrupted', error='服务重启，任务中断' WHERE status='running'")
        )
