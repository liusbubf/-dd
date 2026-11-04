#!/usr/bin/env bash
# =============================================================================
# 在 Linux VM（或宿主机）内启动平台后端 —— redroid 真机模式。
# 通常由 Mac 侧 connect-vm-redroid.sh 经 `limactl shell` 调用；也可单独跑。
# 幂等：可反复执行（同步代码、装依赖、重启服务）。
# =============================================================================
set -euo pipefail

# 后端源码目录：默认取本脚本相对仓库位置（经 Lima 挂载时即 Mac 上的仓库路径）
SRC_BACKEND="${SRC_BACKEND:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../backend" && pwd)}"
BE="$HOME/cloud-backend"
IMAGE="${CLOUD_REDROID_IMAGE:-redroid/redroid:12.0.0_64only-latest}"

echo "==> 依赖（python venv/pip）"
command -v pip3 >/dev/null 2>&1 || sudo apt-get install -y -qq python3-venv python3-pip

echo "==> 同步后端代码到 $BE"
mkdir -p "$BE"
sudo rm -rf "$BE/app"   # 清掉上次以 root 运行时生成的 __pycache__，避免 cp 权限报错/旧代码残留
cp -r "$SRC_BACKEND/app" "$BE/"
cp "$SRC_BACKEND/requirements.txt" "$BE/" 2>/dev/null || true

echo "==> venv + 依赖（含 docker SDK，用于 redroid 模式）"
[ -x "$BE/.venv/bin/python" ] || python3 -m venv "$BE/.venv"
"$BE/.venv/bin/pip" install -q --upgrade pip
"$BE/.venv/bin/pip" install -q fastapi "uvicorn[standard]" "sqlalchemy[asyncio]" \
  aiosqlite pydantic pydantic-settings PyJWT python-multipart httpx docker

echo "==> binder 内核模块 + 数据目录"
sudo modprobe binder_linux devices="binder,hwbinder,vndbinder" 2>/dev/null || true
sudo mkdir -p /root/redroid-data /root/cloud-data

echo "==> 以 systemd 瞬态服务启动后端（root，可访问 docker.sock + adb）"
sudo systemctl stop cloudbe 2>/dev/null || true
sudo systemctl reset-failed cloudbe 2>/dev/null || true
sudo systemd-run --unit=cloudbe --collect --working-directory="$BE" \
  --setenv=CLOUD_DEVICE_BACKEND=redroid \
  --setenv=CLOUD_REDROID_IMAGE="$IMAGE" \
  --setenv=CLOUD_REDROID_GPU_MODE=guest \
  --setenv=CLOUD_REDROID_DATA_DIR=/root/redroid-data \
  --setenv=CLOUD_DATABASE_URL=sqlite+aiosqlite:////root/cloud-data/cloud.db \
  "$BE/.venv/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000

sleep 6
echo -n "==> 状态："; systemctl is-active cloudbe
curl -s --noproxy 127.0.0.1 http://127.0.0.1:8000/api/health && echo
echo "   日志：sudo journalctl -u cloudbe -f"
