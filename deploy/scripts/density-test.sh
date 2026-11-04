#!/usr/bin/env bash
# =============================================================================
# 密度实测：批量起 20 台 720p 实例，打印 docker stats + free -h
# 对应 PoC D10「密度实测」与计划 D19（demo 规模压测）。
#
# 目的：压真实资源，据此外推单机可稳跑台数，修正服务器数量与硬件预算。
#
# 用法：
#   ./density-test.sh                # 默认 20 台，720p，guest 渲染
#   ./density-test.sh -n 20 --gpu-mode host --warmup 60
#   ./density-test.sh --cleanup      # 仅清理本脚本起的实例（不新建）
#
# 记得赋予可执行权限：chmod +x density-test.sh
# =============================================================================
set -euo pipefail

COUNT=20
GPU_MODE="${GPU_MODE:-guest}"
WARMUP=60
CLEANUP_ONLY=0
DATA_DIR="${DATA_DIR:-/data/redroid}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--count)  COUNT="$2"; shift 2;;
    --gpu-mode)  GPU_MODE="$2"; shift 2;;
    --warmup)    WARMUP="$2"; shift 2;;
    --data-dir)  DATA_DIR="$2"; shift 2;;
    --cleanup)   CLEANUP_ONLY=1; shift;;
    -h|--help)   echo "用法见脚本头部注释"; exit 0;;
    *) echo "未知参数：$1" >&2; exit 1;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATCH="${SCRIPT_DIR}/../redroid/batch-start.sh"

cleanup() {
  echo "==> 清理 redroid_ 实例..."
  mapfile -t names < <(docker ps -a --filter "name=redroid_" --format '{{.Names}}')
  if [[ ${#names[@]} -gt 0 ]]; then
    docker rm -f "${names[@]}" >/dev/null
    echo "   已移除 ${#names[@]} 个容器"
  else
    echo "   无 redroid_ 容器"
  fi
}

if [[ "$CLEANUP_ONLY" -eq 1 ]]; then
  cleanup
  exit 0
fi

command -v docker >/dev/null 2>&1 || { echo "缺少 docker，请先运行 host-setup.sh"; exit 1; }
[[ -x "$BATCH" ]] || { echo "找不到可执行的 batch-start.sh：$BATCH"; exit 1; }

echo "==================================================================="
echo "  密度实测：${COUNT} 台 · 720x1280@320 · GPU=${GPU_MODE}（PoC D10）"
echo "==================================================================="

# ---- 批量起 N 台 720p（对齐 PoC D10 的 720/1280/320 参数）----
GPU_MODE="$GPU_MODE" DATA_DIR="$DATA_DIR" \
"$BATCH" -n "$COUNT" --width 720 --height 1280 --dpi 320 --gpu-mode "$GPU_MODE"

echo ""
echo "==> 预热 ${WARMUP}s 让所有实例进入稳态..."
sleep "$WARMUP"

# ---- 资源汇总 ----
echo ""
echo "===================== docker stats（每实例 CPU/内存）====================="
docker stats --no-stream --format \
  'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' \
  $(docker ps --filter "name=redroid_" --format '{{.Names}}')

echo ""
echo "===================== free -h（宿主机内存余量）====================="
free -h

echo ""
echo "===================== 汇总 ====================="
RUNNING=$(docker ps --filter "name=redroid_" --format '{{.Names}}' | wc -l | tr -d ' ')
echo "   目标台数: ${COUNT}   实际运行: ${RUNNING}"
echo "   结论口径：据上表外推单机可稳跑台数，回填 PoC 结论汇总表『修正后单机密度/BOM』。"
echo "   清理：./density-test.sh --cleanup"
echo "==================================================================="
