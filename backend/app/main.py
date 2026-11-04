"""FastAPI 应用入口。

启动：uvicorn app.main:app --reload  （在 backend/ 目录下）
文档：http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy import text

from .config import enforce_security, settings
from .database import SessionLocal, init_db
from .orchestrator.base import DeviceCommandError, DeviceUnreachable
from .routers import (
    alerts,
    apps,
    audit,
    auth,
    batch,
    cloud_disk,
    control,
    device_detail,
    devices,
    downloads,
    files,
    groups,
    ips,
    logs,
    metrics,
    reports,
    scripts,
    skin,
    tasks,
    users,
    ws,
)
from .seed import seed
from .sync import device_sync_loop, router as sync_router
from .ws_manager import manager

_log = logging.getLogger("app")

# 统一日志格式与级别（CLOUD_LOG_LEVEL 可配）。只记路由/状态/耗时，不记请求体，
# 避免口令、JWT、设备口令被日志落盘。
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from .expiry import expire_sweep_loop
    from .routers.tasks import scheduler_loop

    problems = enforce_security()
    if problems:
        _log.warning("安全配置告警：%s", "；".join(problems))

    await init_db()
    await seed()
    # 启动定时任务调度器（后台协程）
    asyncio.create_task(scheduler_loop())
    # 启动设备同步（后台协程，配置 CLOUD_SYNC_SERVER 后生效）
    asyncio.create_task(device_sync_loop())
    # 到期回收（默认关闭，CLOUD_EXPIRE_SWEEP_ENABLED=true 才真正扫描）
    asyncio.create_task(expire_sweep_loop(settings.expire_sweep_interval))
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="X86 云手机平台后端：设备编排、鉴权、批量控制、脚本回放、实时预览与审计管理。",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "认证", "description": "登录、鉴权、当前用户信息"},
        {"name": "设备", "description": "设备列表、创建、状态、截图和实时控制"},
        {"name": "分组", "description": "分组管理与设备归属"},
        {"name": "批量", "description": "批量创建、批量开网页、批量输入与同步操控"},
        {"name": "脚本", "description": "脚本录制、回放和任务编排"},
        {"name": "监控", "description": "指标、日志、告警和报表"},
        {"name": "应用", "description": "应用安装、卸载、启动和文件管理"},
        {"name": "用户", "description": "用户管理、角色和审计"},
        {"name": "控制", "description": "单机投屏、输入、按键与屏幕参数"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # 通配符与 credentials 不能共存：通配符场景下关闭 credentials（本平台用 Bearer 头，不依赖 Cookie）
    allow_credentials="*" not in settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(DeviceUnreachable)
async def _device_unreachable_handler(request: Request, exc: DeviceUnreachable) -> JSONResponse:
    """设备控制通道不可用 → 503，并带上排障线索。

    宁可让调用方看到明确的失败，也不返回一张「看着正常」的皮肤图/假成功。
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": str(exc),
            "device_id": exc.device_id,
            "serial": exc.serial,
            "unreachable": True,
            "hint": f"设备失联。检查容器是否在跑，并执行 adb connect {exc.serial}",
        },
    )


@app.exception_handler(DeviceCommandError)
async def _device_command_error_handler(request: Request, exc: DeviceCommandError) -> JSONResponse:
    """设备命令失败（路径不存在 / 无权限等）→ 502，带上原始报错。

    同样禁止静默返回空结果：「读不到」必须和「本来就没有」区分开。
    """
    return JSONResponse(
        status_code=502,
        content={
            "detail": str(exc),
            "device_id": exc.device_id,
            "what": exc.what,
            "command_failed": True,
        },
    )


@app.exception_handler(Exception)
async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底 500：响应只给可读文案，堆栈只进服务端日志。

    避免把内部路径、SQL、库版本等细节泄漏给调用方；排障看后端日志的 traceback。
    """
    _log.exception("未处理异常：%s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请联系管理员", "internal_error": True},
    )


api = settings.api_prefix
app.include_router(auth.router, prefix=api)
app.include_router(groups.router, prefix=api)
app.include_router(devices.router, prefix=api)
app.include_router(control.router, prefix=api)
app.include_router(batch.router, prefix=api)
app.include_router(scripts.router, prefix=api)
app.include_router(metrics.router, prefix=api)
app.include_router(alerts.router, prefix=api)
app.include_router(tasks.router, prefix=api)
app.include_router(device_detail.router, prefix=api)
app.include_router(reports.router, prefix=api)
app.include_router(logs.router, prefix=api)
app.include_router(files.router, prefix=api)
app.include_router(cloud_disk.router, prefix=api)
app.include_router(downloads.router, prefix=api)
app.include_router(ips.router, prefix=api)
# 自助端点（/users/me、/users/me/password）不带 admin 依赖，必须单独挂载
app.include_router(users.me_router, prefix=api)
app.include_router(users.router, prefix=api)
app.include_router(audit.router, prefix=api)
app.include_router(apps.router, prefix=api)
app.include_router(skin.router, prefix=api)
app.include_router(ws.router, prefix=api)
app.include_router(sync_router, prefix=api)


@app.get("/")
async def root() -> dict:
    return {
        "name": settings.app_name,
        "backend": settings.device_backend,
        "docs": "/docs",
        "ws_clients": manager.count,
    }


@app.get(f"{api}/health")
async def health() -> dict:
    """健康检查：DB 可连 + 当前设备后端。

    Docker/adb 的可用性按设备逐个探测成本高，不放进这个高频探针；
    真机排障请用 `/api/devices` 的 status 与 `docs/已知限制与待办.md` 里的命令。
    """
    db_ok = False
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # noqa: BLE001  健康检查需要吞掉异常并返回 degraded
        _log.warning("health: 数据库不可用：%s", exc)
    return {
        "status": "ok" if db_ok else "degraded",
        "backend": settings.device_backend,
        "database": "ok" if db_ok else "unavailable",
        "device_backend": settings.device_backend,
    }
