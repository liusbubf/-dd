#!/usr/bin/env bash
# =============================================================================
# Redroid 真实性能基准（自包含，仅依赖 docker + adb）
# 在真实 Linux 宿主机（或 arm64 Ubuntu VM）上运行，产出真实 Android 性能数据：
#   1) 单实例冷启动耗时（docker run → sys.boot_completed=1）
#   2) Android 版本 / CPU ABI（确认原生 arm64，无转译）/ GL 渲染器
#   3) adb 往返延迟（N 次 shell 调用均值）
#   4) 打开网页链路（VIEW intent 是否可解析并拉起）
#   5) 密度：批量起 N 台，docker stats 每实例 CPU/内存 + 宿主余量，外推单机台数
#
# 用法：
#   sudo ./redroid-benchmark.sh                 # 默认：1 台深度指标 + 5 台密度
#   sudo ./redroid-benchmark.sh -n 10           # 密度阶段起 10 台
#   sudo ./redroid-benchmark.sh --image redroid/redroid:13.0.0-latest
#   sudo ./redroid-benchmark.sh --cleanup       # 仅清理本脚本容器
# =============================================================================
set -uo pipefail

# 默认用 64 位专用镜像：Apple Silicon / 无 32 位 ARM 支持的宿主必须用 _64only，
# 否则 32 位 zygote 会 "Exec format error" 崩溃循环、永远 boot 不完。
IMAGE="${IMAGE:-redroid/redroid:12.0.0_64only-latest}"
N=5
W=720; H=1280; DPI=320
GPU_MODE="${GPU_MODE:-guest}"
BASE_PORT=5555
PREFIX="rdbench"
DATA_DIR="${DATA_DIR:-$HOME/redroid-bench}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--count) N="$2"; shift 2;;
    --image) IMAGE="$2"; shift 2;;
    --gpu-mode) GPU_MODE="$2"; shift 2;;
    --cleanup) docker rm -f $(docker ps -aq --filter "name=${PREFIX}") 2>/dev/null; echo "已清理"; exit 0;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "未知参数 $1"; exit 1;;
  esac
done

command -v docker >/dev/null || { echo "缺 docker"; exit 1; }
command -v adb    >/dev/null || { echo "缺 adb"; exit 1; }
adb start-server >/dev/null 2>&1

hr() { printf '%.0s─' {1..67}; echo; }
now_ms() { date +%s%3N; }

wait_boot() { # $1=容器名  返回：启动秒数（失败返回 -1）
  # 用 docker exec getprop 轮询（比启动期的 adb 更稳、更快）
  local name="$1" start end bc
  start=$(date +%s)
  for _ in $(seq 1 150); do
    bc=$(docker exec "$name" getprop sys.boot_completed 2>/dev/null | tr -d '\r')
    [[ "$bc" == "1" ]] && { end=$(date +%s); echo $((end-start)); return; }
    sleep 2
  done
  echo "-1"
}

launch() { # $1=index
  local i="$1"
  local port=$((BASE_PORT+i))
  docker rm -f "${PREFIX}_${i}" >/dev/null 2>&1
  docker run -itd --privileged --name "${PREFIX}_${i}" \
    -v "${DATA_DIR}/${i}:/data" -p "${port}:5555" \
    "$IMAGE" \
    androidboot.redroid_width=$W androidboot.redroid_height=$H \
    androidboot.redroid_dpi=$DPI androidboot.redroid_gpu_mode=$GPU_MODE >/dev/null
}

echo "==================================================================="
echo "  Redroid 真实性能基准"
echo "  镜像=$IMAGE  分辨率=${W}x${H}@${DPI}  GPU=$GPU_MODE"
echo "  宿主：$(uname -m) $(nproc)核 $(free -h | awk '/Mem/{print $2}')  内核 $(uname -r)"
echo "==================================================================="

# ---------- 阶段 1：单实例深度指标 ----------
hr; echo "【阶段 1】单实例冷启动 + 指标"; hr
launch 0
BOOT=$(wait_boot "${PREFIX}_0")
if [[ "$BOOT" == "-1" ]]; then
  echo "❌ 单实例未在 300s 内启动完成，查看：docker logs ${PREFIX}_0"
  docker logs --tail 20 "${PREFIX}_0" 2>&1 | sed 's/^/   /'
  exit 1
fi
S="localhost:$BASE_PORT"
adb connect "$S" >/dev/null 2>&1; sleep 2
echo "  冷启动到 boot_completed：${BOOT}s"
echo "  Android 版本：$(adb -s $S shell getprop ro.build.version.release | tr -d '\r')"
echo "  CPU ABI：     $(adb -s $S shell getprop ro.product.cpu.abilist | tr -d '\r')"
echo "  转译桥：      $(adb -s $S shell getprop ro.dalvik.vm.native.bridge | tr -d '\r')  (0 或空=原生 arm，无需转译)"
GLES=$(adb -s $S shell dumpsys SurfaceFlinger 2>/dev/null | grep -i 'GLES:' | head -1 | tr -d '\r')
echo "  GL 渲染器：   ${GLES:-（未取到，可能画面未起）}"

# adb 往返延迟
echo -n "  adb 往返延迟（10 次均值）："
t0=$(now_ms); for _ in $(seq 1 10); do adb -s $S shell true >/dev/null 2>&1; done; t1=$(now_ms)
echo " $(( (t1-t0)/10 )) ms"

# 打开网页链路
echo -n "  打开网页（VIEW intent）："
OUT=$(adb -s $S shell am start -a android.intent.action.VIEW -d 'https://example.com' 2>&1 | tr -d '\r')
if echo "$OUT" | grep -qi 'Starting'; then
  echo " ✅ 可拉起（$(echo "$OUT" | grep -i cmp | head -1)）"
else
  echo " ⚠️ 无浏览器处理该 intent（AOSP 无 GApps/浏览器时正常；生产镜像内置 Chromium/WebView）"
fi

# ---------- 阶段 2：密度 ----------
hr; echo "【阶段 2】密度：并发起 ${N} 台"; hr
LAUNCH_START=$(date +%s)
for i in $(seq 1 $((N-1))); do launch "$i"; done
echo "  已下发 ${N} 台（含阶段1的 1 台），等待全部 boot_completed..."
OK=1
for i in $(seq 1 $((N-1))); do
  b=$(wait_boot "${PREFIX}_${i}")
  [[ "$b" != "-1" ]] && OK=$((OK+1))
done
LAUNCH_END=$(date +%s)
echo "  ${OK}/${N} 台启动成功，总耗时 $((LAUNCH_END-LAUNCH_START))s"
echo ""
echo "  ---- docker stats（每实例 CPU/内存实测）----"
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}' \
  $(docker ps --filter "name=${PREFIX}_" --format '{{.Names}}')
echo ""
echo "  ---- 宿主内存余量 ----"; free -h
echo ""
# 外推
TOTALMEM_KB=$(awk '/MemTotal/{print $2}' /proc/meminfo)
AVGMEM_MB=$(docker stats --no-stream --format '{{.MemUsage}}' $(docker ps --filter "name=${PREFIX}_" --format '{{.Names}}') \
  | awk '{v=$1; if(v ~ /GiB/){gsub(/GiB/,"",v); print v*1024} else {gsub(/MiB/,"",v); print v}}' \
  | awk '{s+=$1; n++} END{if(n>0) printf "%.0f", s/n}')
hr; echo "【外推】"
echo "  单实例平均内存：约 ${AVGMEM_MB:-?} MiB"
if [[ -n "${AVGMEM_MB:-}" && "${AVGMEM_MB}" -gt 0 ]]; then
  echo "  按内存粗估单机可跑：约 $(( TOTALMEM_KB/1024 * 8/10 / AVGMEM_MB )) 台（留 20% 余量，仅内存维度）"
fi
echo "  注：VM/软件渲染下的数值不代表生产裸机；真实密度以 Intel/AMD 裸机 + host GPU 复测为准。"
hr
echo "清理：sudo $0 --cleanup"
