# 前端 · 云手机管理控制台

Vue 3 + Vite + Element Plus + Pinia。对应甲方要素「网站登录及管理系统」+「群控投屏客户端（Web）」。

## 开发

本工程用 **pnpm**（锁文件是 `pnpm-lock.yaml`，没有 `package-lock.json`）。
用 `npm install` 会绕开锁文件、装出与 CI/镜像不一致的版本树，请勿混用。
Node 需 **≥ 22.13**（pnpm 11 依赖 `node:sqlite` 内置模块）。

```bash
cd frontend
corepack enable && corepack prepare pnpm@11.8.0 --activate   # 仅首次
pnpm config set registry https://registry.npmmirror.com      # 国内网络，可选
pnpm install
pnpm run dev         # http://localhost:5173
```

开发服务器已把 `/api`（含 WebSocket）反代到后端 `http://127.0.0.1:8000`（见 `vite.config.js`），
因此先启动后端再启动前端即可，无需改地址。默认登录 `admin / admin123`。

## 构建

```bash
pnpm run build       # 产物在 dist/，由 nginx 提供并反代 /api（见 deploy/nginx/default.conf）
pnpm run preview     # 本地预览构建产物
```

`frontend/Dockerfile` 用同一套 pnpm + `--frozen-lockfile` 构建，因此镜像内版本与本地一致。

## 页面对应主流程

| 页面 | 路由 | 对应验收 |
|---|---|---|
| 登录 | `/login` | §1 登录 |
| 设备管理 | `/devices` | §2 批量建机 / §3 独立身份（指纹抽屉）/ 分组 / 搜索 / 启停 |
| 多画面预览 | `/grid` | §5 投屏预览（2×2/3×3/4×4 实时网格）|
| 单机操控 | `/device/:id` | §6 单台操控 + 录制脚本 |
| 批量操控 | `/batch` | §7 批量同步（一键开网页 / 1 控 N）|
| 脚本回放 | `/scripts` | §8 脚本跨设备回放 |

预览帧与设备状态经 `WS /api/ws` 实时推送（`src/api/ws.js` + `src/stores/devices.js`）。
