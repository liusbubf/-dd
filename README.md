# X86 云手机平台 · 主流程 Demo

> 作者：顺天 ｜ 版权：Copyright (c) 2026 顺天（见 [LICENSE](LICENSE) 与 [AUTHORS](AUTHORS)）

依据《X86云手机平台_本月Demo详细计划_主流程跑通.md》实现的可运行 demo：
**x86 虚拟云手机 + 苹果 UI + 群控投屏 + App 客户端 + 网站登录及管理系统，类魔云腾**。

本仓库把甲方五要素做成端到端能演示的一条闭环，并且**在没有 Docker/Redroid 的机器上也能直接跑通**
（simulator 后端），迁到 Linux 宿主机再切 redroid 后端即为真实云手机。

```
登录 Web 管理系统 → 批量建 N 台云手机（iOS 皮肤）→ 每台浏览器开网页
→ 每台独立设备标识/出口 IP/浏览器指纹 → Web & PC 多画面预览 + 单台实时操控
→ 一键全部开同一网页 / 同步操控（1 控 N）→ App 端看设备并操控 → 录脚本跨设备回放
```

## 目录结构

| 目录 | 内容 | 甲方要素 |
|---|---|---|
| `backend/` | FastAPI + WebSocket，设备编排/鉴权/一机一码/批量/脚本；后端可插拔（simulator ↔ redroid） | 平台底座 |
| `frontend/` | Vue3 + Element Plus 管理控制台（登录/设备/多画面/批量/脚本） | 网站管理系统 + Web 群控 |
| `deploy/` | docker-compose、Redroid 启动脚本、STF 集成、宿主机准备、密度压测、iOS 皮肤流程 | x86 云手机 + 苹果 UI |
| `ws-scrcpy/` | 网页 H.264 投屏（vendor 上游 NetrisTV/ws-scrcpy 0.9.0-dev，MIT） | 低延迟投屏 |
| `pc-client/` | Electron 封装 Web 端出 Windows 客户端（对齐魔云腾） | PC 群控客户端 |
| `app-client/` | 安卓 App（Kotlin+Compose）：登录/设备列表/投屏/批量 | App 客户端 |
| `docs/` | 架构说明 + 逐日计划映射 | — |

## 5 分钟跑通（simulator，macOS/Windows/Linux 通用，无需 Docker）

```bash
# 1) 后端
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" aiosqlite pydantic pydantic-settings PyJWT python-multipart httpx
uvicorn app.main:app --reload            # http://localhost:8000/docs

# 2) 前端（另开终端；用 pnpm，仓库锁文件是 pnpm-lock.yaml。Node 需 ≥ 22.13）
cd frontend && corepack enable && pnpm install && pnpm run dev # http://localhost:5173  登录 admin/admin123

# 3) 一键验证 8 条验收（后端已启动的前提下）
cd backend && source .venv/bin/activate && python -m tests.smoke
```

`tests/smoke.py` 会自动跑完登录→建 10 台→抽查指纹→预览→单机操控→批量同步→分组→脚本回放，全绿即主流程跑通。

> 首次部署（非临时演示）请先初始化 4 个角色的正式账号：
> `python tools/seed_rbac.py`。口令可从 `CLOUD_SEED_PWD_*` 环境变量读取；未提供时脚本用 `secrets`
> 生成强口令并写入本地未跟踪文件 `.seed_passwords.json`（**不得提交**）。角色边界见
> [`docs/RBAC权限矩阵.md`](docs/RBAC权限矩阵.md)。

> ⚠️ `tests/smoke.py` 会**批量创建 10 台设备**，只适合 simulator。真机（redroid）环境请用
> **非破坏性**的 `python acceptance_live.py`：不建机不删机、只用现有在跑的设备核验，
> 跑完还原设备原来打开的网页；并会检出「有画面但设备其实已失联」的伪装情况。

## 一条命令起整套（Docker Compose）

```bash
docker compose up -d --build          # postgres + backend + frontend（redis 预留，默认不启动）
# 打开 http://localhost 登录 admin/admin123
```

## 切换到真实 Redroid（Linux 宿主机）

```bash
sudo bash deploy/scripts/host-setup.sh        # binder 内核模块 + docker + adb（PoC D2）
export CLOUD_DEVICE_BACKEND=redroid
export CLOUD_REDROID_GPU_MODE=host            # Intel/AMD 核显；NVIDIA 用 guest（见下）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> ⚠️ 关键坑（来自方案包）：Redroid 硬件渲染走 Intel/AMD 的 Mesa `/dev/dri` 路径，
> **NVIDIA 闭源驱动不支持此路径**——别照抄甲方的 8×L40S 做渲染。详见 `docs/architecture.md`。

## 文档导航

| 文档 | 内容 |
|---|---|
| **[`STATUS.md`](STATUS.md)** | **进度跟踪**：验收进度、与目标差距、已实现/待办、当前运行态（先看这个）|
| **[`docs/部署搭建手册_x86服务器.md`](docs/部署搭建手册_x86服务器.md)** | **交付部署首选**：x86 服务器选型红线（核显/NVIDIA/ARM 转译）、内核 binder、国内镜像加速与离线部署、三条部署路径、生产加固、FAQ |
| **[`docs/技术文档.md`](docs/技术文档.md)** | **完整技术手册**（新人从此上手）：项目概述、系统架构、技术栈、目录结构、快速开始、完整 API 参考、一机一码、设备编排、实时预览与操控、部署、真机实测、计划验收、排障 FAQ、合规边界 |
| [`docs/architecture.md`](docs/architecture.md) | 架构分层图与数据流速览 |
| [`docs/RBAC权限矩阵.md`](docs/RBAC权限矩阵.md) | 角色 × 资源 × 操作矩阵，superadmin/admin 差异 |
| [`docs/改造计划.md`](docs/改造计划.md) | 分批改造清单（批次 0–3）与验证方式 |
| [`docs/plan-mapping.md`](docs/plan-mapping.md) | 8 条验收清单 + D1–D20 逐日任务映射 |
| [`docs/验收报告.md`](docs/验收报告.md) | **交付验收报告**：8 条验收逐条判据+证据 + 已实现/待实现清单 |
| [`docs/扩展功能.md`](docs/扩展功能.md) | 扩展模块：看板/告警/任务/详情/报表/日志/RBAC/应用/分组/投屏/CP-007 |
| [`docs/高级增强能力.md`](docs/高级增强能力.md) | 商业级增强方案：独享网络、随机化设备标识、秒级刷机、WebRTC 高密度并发 |
| [`docs/合规安全架构.md`](docs/合规安全架构.md) | 合规、可审计、可验证的云手机安全架构（不提供绕过检测能力） |
| [`docs/架构图.md`](docs/架构图.md) | 系统架构图 + 真机部署拓扑（mermaid） |
| [`docs/演示脚本.md`](docs/演示脚本.md) | 演示彩排逐步脚本（D18/D20） |
| [`docs/三端联调.md`](docs/三端联调.md) | Web/PC/App 三端连同一后端 runbook |
| [`docs/规模化方案.md`](docs/规模化方案.md) | 500 台规模化 k8s 预研（架构/容量估算/BOM/迁移路径）|
| [`docs/redroid-real-benchmark.md`](docs/redroid-real-benchmark.md) | 真实 Redroid Android 实测报告 |
| [`docs/已知限制与待办.md`](docs/已知限制与待办.md) | **能力边界**：哪些是演示级、哪些尚未实现（交付前必读）|
| [`docs/安全与凭据说明.md`](docs/安全与凭据说明.md) | 必须由部署者配置的凭据项、演示默认值与轮换建议 |
| [`docs/代码修改授权说明.md`](docs/代码修改授权说明.md) | 本地改代码口令门禁的用法与原理 |

## 与计划的对应

- 8 条验收清单 → 见 `docs/plan-mapping.md` 的「验收对照」。
- D1–D20 逐日任务 → 见 `docs/plan-mapping.md` 的「逐日映射」，标注每日产物落在哪个文件。

## 合规边界

本仓库交付的是**云手机群控平台技术底座**（等同魔云腾/河马等商用产品形态）。设备指纹隔离、独立 IP 属平台通用能力；
目标网站的账号合规、反作弊对抗、业务合法性由使用方承担。ARM 转译库（libndk/libhoudini）商用授权需另行确认。
