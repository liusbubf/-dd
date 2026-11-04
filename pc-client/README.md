# PC 群控客户端（Electron）

X86 云手机平台的 Windows/PC 端群控客户端，对齐魔云腾 Windows 客户端形态（本月计划 **D16**）。

## 定位：封装，不是重写

本客户端把 **Web 管理端（`../frontend`，Vue + Vite）整体封装成桌面应用**：

- 登录、设备列表、多画面网格预览、单台操控、批量下发、脚本回放等能力全部来自 Web 端，无二次开发；
- Web / PC / App 三端连**同一套 FastAPI 后端**（`http://<host>:8000/api`，JWT 鉴权 + WebSocket 推送），任何一端的操作在其他两端实时一致（计划 **D17** 全链路联调的前提）;
- Electron 层只负责：桌面窗口（1400×900）、中文原生菜单、外链转系统浏览器、单实例锁、安全基线（`contextIsolation: true` + `nodeIntegration: false` + sandbox，preload 仅暴露版本号/平台/openExternal 最小桥）。

```
┌────────────────────────────┐
│  Electron 壳（main.js）     │
│  ┌──────────────────────┐  │      HTTP + WS
│  │  Web 管理端 (Vue)     │──┼──────────────────►  FastAPI 后端 :8000
│  │  frontend/dist        │  │   /api/* + /api/ws
│  └──────────────────────┘  │
└────────────────────────────┘
```

## 目录结构

```
pc-client/
├── package.json           # electron + electron-builder，dev/start/build/dist 脚本
├── main.js                # 主进程：窗口、菜单、加载策略、IPC
├── preload.js             # contextBridge 最小桥（window.cloudPhoneDesktop）
├── electron-builder.yml   # 打包配置（win: nsis + portable；mac: dmg 可选）
└── README.md
```

## 开发调试

前置：Node.js ≥ 18。三个终端依次起后端、前端、客户端：

```bash
# 1. 起后端（默认账号 admin / admin123）
cd backend && uvicorn app.main:app --reload --port 8000

# 2. 起 Web 前端 dev server（Vite，默认 5173 端口；frontend 用 pnpm，Node ≥ 22.13）
cd frontend && corepack enable && pnpm install && pnpm run dev

# 3. 起 PC 客户端（加载 http://localhost:5173，自动开 DevTools）
#    pc-client 自身仍是 npm 工程（带 package-lock.json）
cd pc-client && npm install && npm run dev
```

Vite 端口不是 5173 时：`ELECTRON_START_URL=http://localhost:<port> npm start`。

## 打包出 Windows exe

```bash
cd pc-client
npm run dist        # = 先构建 ../frontend（pnpm run build），再 electron-builder --win
                    # 需宿主已装 pnpm：corepack enable
```

产物在 `pc-client/release/`：

| 产物 | 说明 |
|---|---|
| `云手机群控客户端-0.1.0-win-x64.exe`（nsis） | 标准安装包，装完有桌面/开始菜单快捷方式 |
| `云手机群控客户端-0.1.0-portable.exe` | 免安装单文件，拷到演示机双击即用 |

打包时 `frontend/dist` 会作为 `extraResources` 一并打入安装包（运行时从 `resources/frontend/index.html` 加载），**exe 自带前端页面，演示机只需能访问后端 8000 端口**。

> 提示：在 macOS/Linux 上交叉打 Windows 包需要 wine/mono，建议直接在 Windows 机器上执行 `npm run dist`；macOS 演示包用 `npm run dist:mac` 出 dmg。

## 后端地址

前端构建产物中 API 地址由 `frontend` 自身的配置决定（开发态走 Vite 代理，生产态指向部署的后端地址）。若打包后需要指向演示服务器，请在构建前端前配置好其后端地址，再执行 `npm run dist`。

## 已实现 / 后续

- ✅ 桌面封装、原生中文菜单、安全 preload 桥、nsis + portable 双产物、单实例锁
- ⏭ 后续（demo 之外）：自动更新（electron-updater）、多窗口拆屏投屏、自定义标题栏、系统托盘常驻
