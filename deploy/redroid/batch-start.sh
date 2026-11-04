#!/usr/bin/env bash
# =============================================================================
# 批量启动 N 台 Redroid 实例（对应计划 D4「批量起 N 台」/ D10 密度实测的基础）
#
# 每台分配互不相同的：端口(5555+i) / 数据目录(inst{i}) / 机型 / 序列号，
# 从而演示「一机一码」下的批量建机。调用 start-instance.sh 逐台起。
#
# 用法：
#   ./batch-start.sh                 # 默认起 10 台，720p，guest 渲染
#   ./batch-start.sh -n 20           # 起 20 台
#   ./batch-start.sh -n 20 --start-id 0 --width 720 --height 1280 --dpi 320 --gpu-mode host
#
# 记得赋予可执行权限：chmod +x batch-start.sh
# =============================================================================
set -euo pipefail

COUNT=10
START_ID=0
WIDTH=720
HEIGHT=1280
DPI=320
GPU_MODE="${GPU_MODE:-guest}"
DATA_DIR="${DATA_DIR:-/data/redroid}"

# 机型库：批量建机时循环取用，制造设备多样性（与 fingerprint.py 机型库同源思路）
MODELS=(
  "google|Google|Pixel 6"
  "samsung|Samsung|SM-G991B"
  "Xiaomi|Xiaomi|M2101K9G"
  "OnePlus|OnePlus|NE2213"
  "vivo|vivo|V2254A"
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--count)   COUNT="$2"; shift 2;;
    --start-id)   START_ID="$2"; shift 2;;
    --width)      WIDTH="$2"; shift 2;;
    --height)     HEIGHT="$2"; shift 2;;
    --dpi)        DPI="$2"; shift 2;;
    --gpu-mode)   GPU_MODE="$2"; shift 2;;
    --data-dir)   DATA_DIR="$2"; shift 2;;
    -h|--help)    echo "用法见脚本头部注释"; exit 0;;
    *) echo "未知参数：$1" >&2; exit 1;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
START_ONE="${SCRIPT_DIR}/start-instance.sh"
[[ -x "$START_ONE" ]] || { echo "找不到可执行的 start-instance.sh：$START_ONE"; exit 1; }

END_ID=$((START_ID + COUNT - 1))
echo "==> 批量启动 ${COUNT} 台：ID ${START_ID}..${END_ID}，分辨率 ${WIDTH}x${HEIGHT}@${DPI}，GPU=${GPU_MODE}"

for i in $(seq "$START_ID" "$END_ID"); do
  # 轮询取机型
  idx=$(( i % ${#MODELS[@]} ))
  IFS='|' read -r BRAND MANUFACTURER MODEL <<< "${MODELS[$idx]}"

  echo ""
  echo "----- [$((i - START_ID + 1))/${COUNT}] 启动实例 id=${i}（${BRAND}/${MODEL}）-----"
  GPU_MODE="$GPU_MODE" DATA_DIR="$DATA_DIR" \
  "$START_ONE" \
    --id "$i" \
    --brand "$BRAND" \
    --manufacturer "$MANUFACTURER" \
    --model "$MODEL" \
    --width "$WIDTH" \
    --height "$HEIGHT" \
    --dpi "$DPI" \
    --gpu-mode "$GPU_MODE"
done

echo ""
echo "==> 批量启动完成。当前 redroid 容器："
docker ps --filter "name=redroid_" --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
echo ""
echo "提示：资源实测请运行 deploy/scripts/density-test.sh（docker stats + free -h）"
