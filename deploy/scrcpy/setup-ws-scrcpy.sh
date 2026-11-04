#!/usr/bin/env bash
# =============================================================================
# 部署 ws-scrcpy —— 对已 adb 纳管的 Redroid 设备做 H.264 低延迟 Web 投屏。
# 相比平台内置的截图轮询(~5-15fps PNG)，ws-scrcpy 走 scrcpy-server 的 H.264
# 编码 + 浏览器端解码(Broadway/MSE/WebCodecs)，更丝滑、更省带宽。
#
# 在 Linux 宿主机或 Lima VM 内运行：
#   bash deploy/scrcpy/setup-ws-scrcpy.sh
# 之后用 run-ws-scrcpy.sh 启动。
# =============================================================================
set -euo pipefail
WSDIR="${WSDIR:-$HOME/ws-scrcpy}"

echo "==> Node 20 + git"
command -v git  >/dev/null 2>&1 || sudo apt-get install -y -qq git
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
node --version

echo "==> 克隆 ws-scrcpy"
[ -d "$WSDIR/.git" ] || git clone --depth 1 https://github.com/NetrisTV/ws-scrcpy.git "$WSDIR"

echo "==> 安装依赖 + 构建(webpack，较久)"
cd "$WSDIR"
npm install --no-audit --no-fund
npm run dist

echo "✅ 完成：$WSDIR/dist —— 用 run-ws-scrcpy.sh 启动"
