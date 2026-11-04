# 后端 · X86 云手机平台 API

FastAPI + SQLAlchemy(async) + WebSocket。支持两种设备后端：
- `simulator`（默认）：无需 Docker，任意平台可跑通全部主流程，用于 demo 演示。
- `redroid`：真实 Docker + Redroid + adb，仅 Linux 宿主机。

## 快速启动（simulator，任意平台）

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt         # 或最小集见下
uvicorn app.main:app --reload
# 文档: http://localhost:8000/docs
# 初始管理员: admin / admin123
```

最小依赖（仅 simulator）：`fastapi uvicorn[standard] sqlalchemy[asyncio] aiosqlite pydantic pydantic-settings PyJWT python-multipart httpx`

## 端到端冒烟测试（覆盖验收清单 8 条）

```bash
# 另开一个终端，后端已启动的前提下：
source .venv/bin/activate
python -m tests.smoke
```

## 切到真实 Redroid（Linux）

```bash
export CLOUD_DEVICE_BACKEND=redroid
export CLOUD_REDROID_GPU_MODE=host      # Intel/AMD 核显；NVIDIA 用 guest
# 需已安装 docker、adb，并加载 binder 内核模块（见 deploy/scripts/host-setup.sh）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 主要 API

| 分组 | 端点 |
|---|---|
| 鉴权 | `POST /api/auth/login`、`GET /api/auth/me` |
| 设备 | `GET/POST /api/devices`、`POST /api/devices/batch`、`{id}/start|stop|restart`、`{id}/screenshot` |
| 分组 | `GET/POST /api/groups` |
| 单机操控 | `POST /api/devices/{id}/control/{open_url|tap|swipe|text|key|install}` |
| 批量 | `POST /api/batch/{open_url|tap|swipe|text|key|install}` |
| 脚本 | `GET/POST /api/scripts`、`POST /api/scripts/{id}/run` |
| 实时 | `WS /api/ws`（订阅预览帧 + 状态/进度广播）|

配置项见 `.env.example`（环境变量前缀 `CLOUD_`）。
