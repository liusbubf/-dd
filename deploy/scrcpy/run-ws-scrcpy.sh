#!/usr/bin/env bash
# =============================================================================
# 启动 ws-scrcpy，对已 adb 纳管的 Redroid 设备提供 H.264 低延迟 Web 投屏。
# 前置：先跑过 setup-ws-scrcpy.sh。
#   bash deploy/scrcpy/run-ws-scrcpy.sh          # 默认 :8100
#   PORT=8100 bash deploy/scrcpy/run-ws-scrcpy.sh
# 之后把该端口从 VM 隧道到 Mac：
#   ssh -F ~/.lima/redroid/ssh.config -L 127.0.0.1:8100:127.0.0.1:8100 -N -f lima-redroid
# 浏览器打开 http://localhost:8100 → 选设备 → 实时 H.264 投屏。
# =============================================================================
set -euo pipefail
WSDIR="${WSDIR:-$HOME/ws-scrcpy}"
PORT="${PORT:-8100}"   # 避开平台后端 8000

cd "$WSDIR"
[ -d dist ] || npm run dist

# 确保 redroid 设备已 adb 纳管（redroid 容器 5555 映射到宿主 5556..）
for p in $(seq 5556 5575); do adb connect "localhost:$p" >/dev/null 2>&1 || true; done
adb devices | grep 555 || echo "（未见 adb 设备，先确认 redroid 容器在跑）"

echo "==> ws-scrcpy 监听 :$PORT —— 浏览器打开后选设备即可 H.264 投屏"
WS_SCRCPY_PORT="$PORT" node dist/index.js
