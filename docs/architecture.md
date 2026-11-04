# 架构说明

## 分层

```
┌─────────────────────────────────────────────────────────────┐
│  接入端                                                       │
│  Web 控制台(Vue)   PC 客户端(Electron)   App 客户端(Kotlin)   │
└───────────────┬───────────────┬───────────────┬─────────────┘
                │ REST /api      │ 同一套 API     │
                │ WS   /api/ws   │               │
┌───────────────▼───────────────────────────────▼─────────────┐
│  平台后端 (FastAPI)                                           │
│  鉴权(JWT) · 设备/分组 CRUD · 一机一码 · 单机操控 · 批量 ·    │
│  脚本录制回放 · WebSocket(状态/进度/预览帧广播)               │
└───────────────┬─────────────────────────────────────────────┘
                │ DeviceBackend 抽象（可插拔）
        ┌───────┴────────┬───────────────┐
        ▼                ▼               ▼
  SimulatorBackend   RedroidBackend   PhysicalBackend
  (内存态+SVG预览)    (Docker+adb)     (adb 纳管真机，后加)
        │                │               │
        ▼                ▼               ▼
   任意平台           Linux 宿主机      已连接的 USB/TCP 真机
   (演示/开发)        (真实 x86 实例)    (真机验收)
```

关键设计：上层只依赖 `orchestrator/base.py` 的 `DeviceBackend` 抽象。切换后端只改一个
环境变量 `CLOUD_DEVICE_BACKEND`（`simulator` / `redroid` / `physical`），其余代码零改动。

> **`physical` 为后加模块**（`orchestrator/physical.py`，复用 `redroid.py` 的 adb 助手），
> 早期架构图与部分技术文档未覆盖；它走纯 adb（不改 IMEI/serial），适合真机验收与演示。
> 三者的能力差异（快照、换肤、容器隔离）以各实现类为准。

## 数据流

- **建机**：`POST /devices/batch` → `services.create_device` 生成一机一码(`fingerprint.py`) → `backend.create/start` → 落库 → WS 广播 `device_status`。
- **预览**：前端 WS 发 `subscribe{device_ids,fps}` → 后端 `routers/ws.py` 周期性 `backend.screenshot()` 渲染帧 → 推 `preview`。simulator 渲染 SVG(`preview.py`)，redroid 用 `adb exec-out screencap`（生产替换为 minicap/scrcpy 低延迟流）。
- **批量/同步**：`POST /batch/*` → 并发对选中设备执行 → 每台完成推 `batch_progress`。同步操控做了跨分辨率坐标折算(`batch._scale`)。
- **脚本**：录制在前端把单机操作序列收集为 `steps`；`POST /scripts/{id}/run` 把步骤在多台设备上并发回放，产出逐设备逐步骤报告。

## 投屏的两条链路

| 链路 | 入口 | 实现 | 现状 |
|---|---|---|---|
| 截图推流（默认） | WS `/api/ws` → `subscribe{device_ids,fps}` | `preview_hub.py` 周期取帧（1–12 fps），simulator 渲染 SVG（`preview.py`），redroid/physical 用 `adb exec-out screencap` JPEG | 可用；带宽/帧率一般，~400ms 延迟 |
| ws-scrcpy H.264 | 前端 `ScrcpyPlayer.vue` iframe → `ws-scrcpy:8100` | 后端 `redroid.prepare_scrcpy()` 只拼装 iframe 地址；ws-scrcpy 是 vendor 上游（MIT，0.9.0-dev） | 高清低延迟；**未做同源反代与统一鉴权，8100 绕过 JWT** |

两条链路并存属**阶段性冗余**：截图链路保证任何后端形态都能预览，ws-scrcpy 负责高清操控。
规模化时应收敛为「同域反代 + 统一鉴权 + 单链路」，见 `docs/已知限制与待办.md`。

## 鉴权与权限落点

- 认证：`auth.py`（JWT HS256 + PBKDF2），所有 router 在 `APIRouter(dependencies=[Depends(get_current_user)])` 层统一要求登录。
- 授权：`rbac.py` 的 `require_role()` 工厂，提供 `require_viewer / require_operator / require_admin` 三个命名依赖，
  在**路由装饰器** `dependencies=[...]` 上按「读=viewer、写=operator、用户与审计/同步配置=admin」施加，不在路由内手写 if 判断。
- 审计：`record_audit()` 由写操作调用，落 `audit_logs` 表，`/api/audit` 仅 admin 可查/导出。

## 一机一码（fingerprint.py）

每台设备用一个稳定 seed 派生三组互不相同的字段，重启保持一致、设备间互不相同：

- **设备标识**：brand/manufacturer/model/android_id/serialno/imei/mac —— 作为 Redroid 启动 props 注入（`redroid_props()`）。
- **浏览器指纹**：UA/分辨率/DPI/DPR/时区/语言/WebGL vendor+renderer/Canvas 噪声种子/硬件并发/内存 —— 注入 Chromium。
- **网络**：独立出口 IP + 代理位（从 `CLOUD_PROXY_POOL` 分配）。

对应验收「抽查 3 台，设备标识/出口 IP/浏览器指纹各不相同」。

## 真实 Redroid 落地要点（来自方案包，避坑）

1. **GPU**：硬件渲染走 Intel/AMD 的 Mesa `/dev/dri/render*`（`gpu_mode=host`）。**NVIDIA 闭源驱动不支持此路径**，只能软件渲染(guest)或 QEMU+virtio-gpu（性能损耗大）。硬件选型据此定，别照抄 8×L40S。
2. **内核模块**：Redroid 依赖 `binder_linux`，这是硬前提，过不去要换发行版内核（见 `deploy/scripts/host-setup.sh`）。
3. **STF 纳管**：STF 原为 USB 物理机设计，接 redroid 需让 provider 走 `adb connect ip:5555` 的 TCP 纳管（`deploy/stf/`）。
4. **投屏低延迟**：demo 用截图轮询；生产换 minicap / ws-scrcpy(H.264 over WebSocket)。
5. **一机一码深度**：prop 能改机型/序列号/AndroidID；IMEI 与更深改机需 Magisk/LSPosed 模块，属长期运维项。
6. **ARM 转译授权**：libndk/libhoudini 为专有库，规模化商用需书面确认授权责任（合规边界）。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · SQLAlchemy(async) · aiosqlite/asyncpg · PyJWT · WebSocket |
| 前端 | Vue3 · Vite · Element Plus · Pinia · vue-router · axios |
| 云手机 | Redroid(Docker) · Chromium · Lawnchair(iOS 皮肤) |
| 群控 | STF/DeviceFarmer · minicap · minitouch · adbkit |
| 脚本 | Airtest + Poco（步骤模型已抽象，后端可直连 Airtest 运行时）|
| PC 端 | Electron |
| App 端 | Kotlin + Jetpack Compose + Retrofit |
| 编排 | Docker Compose（demo 规模）· k8s（规模化留后续）|
