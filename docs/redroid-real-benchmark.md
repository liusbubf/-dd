# 真实 Redroid Android 实测报告

> 本文是在**真实 Android 实例**（非 simulator）上跑出来的实测数据，用于验证"真机能跑通 + 相对性能"。
> 环境：Apple Silicon Mac（M 系列，16G）→ Lima/Apple 虚拟化起 **arm64 Ubuntu VM**（6 vCPU / 8G）→ Docker + Redroid。
> ⚠️ VM + 软件渲染下的数值**不代表生产裸机**；真实密度/GPU 以 Intel/AMD 裸机 + host GPU 复测为准。

## 环境与关键坑

| 项 | 实测 |
|---|---|
| 宿主 | Apple Silicon arm64，macOS 26 |
| Linux VM | Ubuntu（Lima, vmType=vz），内核含 `binder_linux`，`modprobe binder_linux` **成功** |
| Docker / adb | Docker 29.6，adb 1.0.41 |
| 镜像 | **`redroid/redroid:12.0.0_64only-latest`**（arm64，606MB）|

**❗ Apple Silicon 必用 64only 镜像**：M 系列 CPU **不支持 32 位 ARM 执行**。混合镜像（`12.0.0-latest`）里的 32 位 `app_process32`/`mediaserver` 等会 `Exec format error`（实测 227 次），导致 **zygote 崩溃循环、永远 boot 不完**。换 `_64only` 镜像后一次点亮（这也正是仓库 `config.py` 的默认值）。

## 实测数据（Android 12, arm64-v8a）

| 指标 | 实测值 | 说明 |
|---|---|---|
| **启动** | boot_completed=1，Android 12 | 真机完整启动 |
| **CPU 架构** | ABI=`arm64-v8a`，`native.bridge=0` | **原生 arm 执行，零转译**（无 libndk/houdini） |
| **单实例内存** | **~555–580 MiB** | 稳态 RSS |
| **单实例 idle CPU** | 0.4–1.4% | 空闲极低 |
| **冷启动** | 秒级（热镜像）/ 约 30–60s（首次冷启，dex 优化） | 5 台并发起（热）18s 全就绪 |
| **5 台并发密度** | 5×~580MiB = 3.9G / 7.7G，余 3.9G | 内存维度宽裕；启动瞬时 CPU load 冲高（dex2oat） |
| **CPU 微基准** | sha256 计算 200MB = **0.18s** | 原生 arm64，有硬件加速 |
| **adb 往返延迟** | **7 ms/次** | 控制通道低延迟 |
| **input tap 注入** | **33 ms/次** | 触控注入实时 |
| **GL 渲染器** | ANGLE / Vulkan(**SwiftShader**) / OpenGL ES 3.1 | **软件渲染**（VM 无 GPU 直通）|
| **浏览器/开网页** | `am start VIEW` 成功；内置 **Chromium WebView 125** + `webview_shell` + `htmlviewer` | **demo 核心用例达标** |

单实例内存外推：按 ~580MiB/台，8G VM 留 20% 余量约可跑 **11–12 台**（仅内存维度；实际受 CPU/IO 限制更低）。生产裸机（更大内存 + Intel/AMD host GPU）密度显著更高。

## 复现步骤（在本机 Mac 上）

```bash
# 1) 起 arm64 Ubuntu VM（已装 Lima）
limactl start --tty=false --name=redroid \
  --set '.vmType="vz" | .cpus=6 | .memory="8GiB" | .disk="30GiB"' template://ubuntu

# 2) VM 内：加载 binder + 装 Docker/adb
limactl shell redroid -- sudo modprobe binder_linux devices="binder,hwbinder,vndbinder"
limactl shell redroid -- bash -c 'curl -fsSL https://get.docker.com | sudo sh; sudo apt-get install -y adb'

# 3) 跑基准（脚本默认已用 64only 镜像）
limactl shell redroid -- sudo bash -s -- -n 5 < deploy/scripts/redroid-benchmark.sh

# 管理 VM
limactl list                 # 查看
limactl stop redroid         # 停
limactl delete redroid       # 删
```

## 把平台后端接到真机（已验证）

架构：后端跑在 **VM 内**（与 docker+adb+redroid 同处），Lima 用 SSH 隧道把 VM:8000 转回 Mac:8000，
Mac 前端 vite 代理 `/api` 命中它。于是 Web 控制台里建机=真实 `docker run redroid`，多画面=真机截图。

```bash
# 一条命令接入（VM 已起的前提下）
bash deploy/scripts/connect-vm-redroid.sh
# 然后启动前端
cd frontend && npm run dev        # http://localhost:5173  admin/admin123
# 切回 simulator
bash deploy/scripts/connect-vm-redroid.sh --revert
```

实测已跑通全链路（截图见仓库根 `真机截图_经平台API.png`、`演示截图_多画面预览.png`）：
- 登录 → 后端 `backend=redroid`
- 批量建 2 台 → 后端在 VM 里 `docker run` 出 `redroid_1/redroid_2`，等 `boot_completed=1`
- 每台 `am start VIEW` 用 **Chromium WebView 125** 打开 example.com，真实渲染
- Web 控制台多画面预览显示两台真机画面；批量 open_url 一键让两台导航到新网页（2/2 成功）

关键代码：`backend/app/orchestrator/redroid.py`（Docker SDK 起容器 + adb 控制 + `screencap` 真机截图，`start()` 会等 `sys.boot_completed`）；开关仅 `CLOUD_DEVICE_BACKEND=redroid`。

## 结论

- ✅ **真机 Android 12 在本 Mac 上成功跑起来**（arm64 原生、零转译、可开网页、控制低延迟）。
- ✅ Redroid 技术路线在 Apple Silicon 上可行（须用 64only 镜像）。
- ⚠️ 图形是软件渲染（VM 限制）；**生产 GPU 加速要 Intel/AMD 裸机走 Mesa `/dev/dri`**（方案文档已明确，NVIDIA 不走此路）。
- ⚠️ VM 密度/性能不代表生产；正式容量以目标裸机 + host GPU 复测 `deploy/scripts/redroid-benchmark.sh` 为准。
