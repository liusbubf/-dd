#!/usr/bin/env bash
# =============================================================================
# 启动单台 Redroid 云手机实例（含一机一码 props 注入）
# 对应计划 D1/D3（起容器 + 看画面）、D3（一机一码）、D9（设备标识注入对照）
#
# 该脚本刻意与后端 RedroidBackend 行为对齐：
#   - 容器命名   redroid_{DEVICE_ID}
#   - 宿主端口   5555 + DEVICE_ID
#   - 数据目录   {DATA_DIR}/inst{DEVICE_ID}
#   - 注入 props ro.product.* / ro.serialno / androidboot.redroid_*（同 fingerprint.py）
#
# 用法：
#   ./start-instance.sh --id 0 --model "Pixel 6" --brand google --width 720 --height 1280 --dpi 320
#   ./start-instance.sh --env inst0.env          # 从 props-template.env 复制的实例配置读取
#   GPU_MODE=host ./start-instance.sh --id 1     # 用环境变量覆盖
#
# 记得赋予可执行权限：chmod +x start-instance.sh
# =============================================================================
set -euo pipefail

# ---- 默认值（可被 env 文件 / 命令行 flag 覆盖）----
DEVICE_ID="${DEVICE_ID:-0}"
MODEL="${MODEL:-Pixel 6}"
BRAND="${BRAND:-google}"
MANUFACTURER="${MANUFACTURER:-Google}"
PRODUCT_NAME="${PRODUCT_NAME:-}"
SERIALNO="${SERIALNO:-}"
ANDROID_ID="${ANDROID_ID:-}"
WIDTH="${WIDTH:-720}"
HEIGHT="${HEIGHT:-1280}"
DPI="${DPI:-320}"
GPU_MODE="${GPU_MODE:-guest}"
PROXY="${PROXY:-}"
DATA_DIR="${DATA_DIR:-/data/redroid}"
REDROID_IMAGE="${REDROID_IMAGE:-redroid/redroid:12.0.0_64only-latest}"
ENV_FILE=""

# ---- 解析命令行参数 ----
usage() {
  grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'
  exit "${1:-0}"
}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --id)            DEVICE_ID="$2"; shift 2;;
    --model)         MODEL="$2"; shift 2;;
    --brand)         BRAND="$2"; shift 2;;
    --manufacturer)  MANUFACTURER="$2"; shift 2;;
    --serialno)      SERIALNO="$2"; shift 2;;
    --width)         WIDTH="$2"; shift 2;;
    --height)        HEIGHT="$2"; shift 2;;
    --dpi)           DPI="$2"; shift 2;;
    --gpu-mode)      GPU_MODE="$2"; shift 2;;
    --proxy)         PROXY="$2"; shift 2;;
    --data-dir)      DATA_DIR="$2"; shift 2;;
    --image)         REDROID_IMAGE="$2"; shift 2;;
    --env)           ENV_FILE="$2"; shift 2;;
    -h|--help)       usage 0;;
    *) echo "未知参数：$1" >&2; usage 1;;
  esac
done

# ---- 若指定 env 文件则加载（命令行 flag 已解析，故 env 文件作为基线；此处按需 source）----
if [[ -n "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

# ---- 派生值 ----
ADB_PORT=$((5555 + DEVICE_ID))                 # 与后端一致：5555 + device.id
CONTAINER="redroid_${DEVICE_ID}"               # 与后端一致：redroid_{id}
INST_DATA="${DATA_DIR}/inst${DEVICE_ID}"       # 与后端一致：{data_dir}/inst{id}
PRODUCT_NAME="${PRODUCT_NAME:-$MODEL}"
# 序列号留空 -> 随机生成，保证一机一码
if [[ -z "$SERIALNO" ]]; then
  SERIALNO="SN$(openssl rand -hex 4 | tr 'a-f' 'A-F')"
fi

echo "==> 启动实例 ${CONTAINER}"
echo "    机型: ${BRAND}/${MODEL}  序列号: ${SERIALNO}"
echo "    分辨率: ${WIDTH}x${HEIGHT} @${DPI}dpi  GPU: ${GPU_MODE}"
echo "    宿主端口: ${ADB_PORT}  数据目录: ${INST_DATA}"
[[ -n "$PROXY" ]] && echo "    出口代理: ${PROXY}"

# ---- 前置检查 ----
command -v docker >/dev/null 2>&1 || { echo "缺少 docker，请先运行 deploy/scripts/host-setup.sh"; exit 1; }
command -v adb    >/dev/null 2>&1 || { echo "缺少 adb，请先运行 deploy/scripts/host-setup.sh"; exit 1; }
mkdir -p "$INST_DATA"

# 若同名容器已存在则清理
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "==> 已存在同名容器，先移除：$CONTAINER"
  docker rm -f "$CONTAINER" >/dev/null
fi

# ---- GPU 加速：host 模式需要挂 render node ----
DRI_ARGS=()
if [[ "$GPU_MODE" == "host" ]]; then
  if ls /dev/dri/renderD* >/dev/null 2>&1; then
    DRI_ARGS=(--device /dev/dri:/dev/dri)
  else
    echo "⚠️  gpu_mode=host 但宿主无 /dev/dri render node，退回软件渲染（guest）" >&2
    GPU_MODE=guest
  fi
fi

# ---- 代理注入（一机一码独立出口 IP）----
PROXY_ARGS=()
if [[ -n "$PROXY" ]]; then
  PROXY_ARGS=(-e "HTTP_PROXY=${PROXY}" -e "HTTPS_PROXY=${PROXY}")
fi

# ---- 起容器（props 注入方式与后端 fingerprint.redroid_props() 完全一致）----
echo "==> docker run ..."
docker run -itd --privileged \
  --name "$CONTAINER" \
  -v "${INST_DATA}:/data" \
  -p "${ADB_PORT}:5555" \
  "${DRI_ARGS[@]}" \
  "${PROXY_ARGS[@]}" \
  "$REDROID_IMAGE" \
  androidboot.redroid_gpu_mode="$GPU_MODE" \
  androidboot.redroid_width="$WIDTH" \
  androidboot.redroid_height="$HEIGHT" \
  androidboot.redroid_dpi="$DPI" \
  ro.product.brand="$BRAND" \
  ro.product.manufacturer="$MANUFACTURER" \
  ro.product.model="$MODEL" \
  ro.product.name="$PRODUCT_NAME" \
  ro.serialno="$SERIALNO" \
  androidboot.serialno="$SERIALNO"

# ---- 等待启动并纳管 ----
echo "==> 等待安卓启动（约 30s）..."
sleep 30

echo "==> adb connect localhost:${ADB_PORT}"
adb connect "localhost:${ADB_PORT}"
adb -s "localhost:${ADB_PORT}" wait-for-device

# android_id 无法用 prop 改，启动后写入 settings 才能做到一机一码
if [[ -n "$ANDROID_ID" ]]; then
  echo "==> 写入 android_id=${ANDROID_ID}"
  adb -s "localhost:${ADB_PORT}" shell settings put secure android_id "$ANDROID_ID" || true
fi

# ---- 校验（对应 PoC D3/D9 判据）----
echo "==> 校验设备标识："
echo -n "    ro.build.version.release = "; adb -s "localhost:${ADB_PORT}" shell getprop ro.build.version.release || true
echo -n "    ro.product.model         = "; adb -s "localhost:${ADB_PORT}" shell getprop ro.product.model || true
echo -n "    ro.serialno              = "; adb -s "localhost:${ADB_PORT}" shell getprop ro.serialno || true
echo -n "    android_id               = "; adb -s "localhost:${ADB_PORT}" shell settings get secure android_id || true

echo "✅ 实例 ${CONTAINER} 就绪。看画面：scrcpy -s localhost:${ADB_PORT}"
