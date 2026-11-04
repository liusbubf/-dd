#!/usr/bin/env bash
# =============================================================================
# 把 Mac 前端接到 Lima VM 里的真机 redroid 后端（一条命令搞定）。
#   1) 在 VM 内启动/刷新平台后端（redroid 模式）
#   2) 停掉 Mac 上的 simulator 后端，腾出 8000
#   3) 建 SSH 隧道 Mac:8000 -> VM:8000（Lima 默认不转发 0.0.0.0 端口）
# 之后：cd frontend && npm run dev  ->  http://localhost:5173（admin/admin123）
#        Web 控制台里建机/预览/操控的就是 VM 里的真实 Android。
#
# 切回 simulator：./connect-vm-redroid.sh --revert
# =============================================================================
set -euo pipefail
VM="${VM:-redroid}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SSHCFG="$HOME/.lima/$VM/ssh.config"
NP="--noproxy 127.0.0.1"

if [[ "${1:-}" == "--revert" ]]; then
  echo "==> 关闭隧道，切回 simulator 后端"
  pkill -f "8000:127.0.0.1:8000" 2>/dev/null || true
  echo "   现在可在 Mac 上跑：cd backend && source .venv/bin/activate && uvicorn app.main:app --reload"
  exit 0
fi

command -v limactl >/dev/null || { echo "未装 Lima"; exit 1; }
limactl list 2>/dev/null | grep -q "^$VM .*Running" || { echo "VM '$VM' 未运行，先 limactl start $VM"; exit 1; }

echo "==> 1/3 在 VM 内启动 redroid 后端"
limactl shell "$VM" -- bash "$REPO/deploy/scripts/vm-run-backend.sh"

echo "==> 2/3 停 Mac simulator 后端 + 重建隧道"
pkill -f "uvicorn app.main" 2>/dev/null || true
pkill -f "8000:127.0.0.1:8000" 2>/dev/null || true
sleep 1
ssh -F "$SSHCFG" -L 127.0.0.1:8000:127.0.0.1:8000 -N -f "lima-$VM"
sleep 2

echo "==> 3/3 验证（backend 应为 redroid）"
curl -s $NP http://127.0.0.1:8000/ && echo
echo ""
echo "✅ 已接入真机。启动前端：cd frontend && npm run dev  ->  http://localhost:5173 (admin/admin123)"
echo "   在『设备管理』批量建机 = 在 VM 里真实 docker run redroid；多画面预览 = 真机截图轮询。"
echo "   切回模拟：$0 --revert"
