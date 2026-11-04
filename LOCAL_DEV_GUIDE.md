# 云手机平台 - 本地开发指南

> 本文件中的服务器地址、账号、口令均为占位符。**本地配置请复制 `backend/.env.example` 为 `backend/.env` 后自行填写**，不要把真实凭据写回本文件。

## 前置条件

1. **Python 3.11+** - [下载地址](https://www.python.org/downloads/)
2. **Node.js 18+ 与 pnpm** - [Node](https://nodejs.org/) / `npm i -g pnpm`
3. **ADB (Android Platform Tools)** - [下载地址](https://developer.android.com/tools/releases/platform-tools)
4. **能访问你的 Redroid / 真机服务器**（地址见 `.env` 中的 `CLOUD_REDROID_HOST`）

## 快速开始

### 后端

```bash
cd backend

# 1. 创建虚拟环境
python -m venv .venv-local

# 2. 激活虚拟环境
.venv-local\Scripts\activate    # Windows
# source .venv-local/bin/activate  # macOS/Linux

# 3. 安装依赖
pip install -r requirements.txt
pip install docker  # requirements.txt 中 docker 包带 Linux 平台条件，Windows 需手动安装
pip install -e .    # 可选：安装本工程（含 tools/ 命令行）

# 4. 复制配置模板并填写自己的值
copy .env.example .env
# 按需修改 CLOUD_ADB_PATH / CLOUD_REDROID_HOST / CLOUD_DATABASE_URL / DOCKER_HOST

# 5. 启动后端
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> 数据库默认使用本地 SQLite（`cloud_platform.db`），零依赖即可跑通 simulator 演示；
> 团队协作请把 `CLOUD_DATABASE_URL` 指向共享 PostgreSQL，并填写你自己的连接串（模板见 `.env.example`）。

### 前端

```bash
cd frontend
pnpm install
pnpm dev
```

访问 http://localhost:5173 。包管理器统一使用 **pnpm**（与 `frontend/Dockerfile` 一致），仓库只保留 `pnpm-lock.yaml`。

## 账号

| 姓名 | 用户名 | 密码 | 角色 |
|------|--------|------|------|
| 演示管理员 | `admin` | `admin123` | 超级管理员 |

> `admin / admin123` 仅为**演示默认值**，生产部署必须通过 `CLOUD_ADMIN_PASSWORD` 修改。
> 其他成员账号请登录后在「用户管理」页面创建，不要再写进文档或代码里。

## 设备

设备地址由 `.env` 中的 `CLOUD_REDROID_HOST` 与每台设备的 `adb_port` 组合得到，例如：

```bash
adb connect <DEVICE_HOST>:<ADB_PORT>
```

具体端口请以「设备列表」页面显示为准。设备清单属于部署环境信息，请记录在本地 `.env` 或私有文档中，不要提交到仓库。

## 常见问题

**Q: 前端显示 "No Data"**
→ 检查后端是否启动成功，访问 http://localhost:8000/docs 确认 API 可用

**Q: 操控页面点击无反应**
→ 检查 ADB 是否已连接对应设备 (`adb devices`)，确保端口可达

**Q: 截图不更新**
→ 确认设备状态为 running，ADB 连接正常

**Q: pip install 报错找不到 docker 包**
→ Windows 上需要手动 `pip install docker`（requirements.txt 中该包有 Linux 平台条件）

**Q: 切回本地 SQLite**
→ 修改 `.env` 中 `CLOUD_DATABASE_URL` 为 SQLite 地址，取消 seed_users 和 sync 注释，重启后端即可

**Q: 想恢复演示数据**
→ 参见 `_attic/README.md`：从 `_attic/cloud_platform.db` 取回演示库，或用 `backend/app/seed.py` 的播种逻辑重新生成。
