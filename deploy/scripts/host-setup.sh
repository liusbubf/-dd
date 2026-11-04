#!/usr/bin/env bash
# =============================================================================
# 宿主机环境就绪脚本（Ubuntu 22.04/24.04）—— 对应 PoC D2
# 装齐 Redroid 运行前提：binder/ashmem 内核模块 + Docker + adb + scrcpy，并做模块校验。
#
# 用法（需 sudo）：
#   sudo ./host-setup.sh
# 记得赋予可执行权限：chmod +x host-setup.sh
#
# 说明：仅适用于 Linux 宿主机；simulator demo 无需本脚本（任意平台 docker compose 即可）。
# =============================================================================
set -euo pipefail

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "本脚本仅适用于 Linux 宿主机（Redroid 依赖 Linux 内核 binder 模块）。"
  echo "若只做 simulator demo，直接用仓库根目录的 docker compose 即可。"
  exit 1
fi

# 需要 root（modprobe / apt / docker 安装）
if [[ "${EUID}" -ne 0 ]]; then
  echo "请用 sudo 运行：sudo $0"
  exit 1
fi

echo "==================================================================="
echo "  X86 云手机平台 · 宿主机环境就绪（PoC D2）"
echo "==================================================================="

# ---- 1. 内核模块（Redroid 依赖 binder/ashmem）----
echo "==> [1/4] 安装内核附加模块 + adb + scrcpy"
apt-get update
apt-get install -y "linux-modules-extra-$(uname -r)" adb scrcpy || {
  echo "⚠️  linux-modules-extra-$(uname -r) 安装失败（可能内核版本无对应包）。"
  echo "    若后续 modprobe binder_linux 失败，需换发行版内核（见 PoC D2 红线项）。"
}

echo "==> 加载 binder / ashmem 模块"
modprobe binder_linux devices="binder,hwbinder,vndbinder" || {
  echo "❌ binder_linux 加载失败：内核未编译 binder。"
  echo "   这是 Redroid 的硬前提，过不去请换发行版内核或自编内核（PoC D2 红线项 1）。"
  exit 1
}
# 新内核(5.x+) ashmem 已被 memfd 取代，加载失败可忽略
modprobe ashmem_linux 2>/dev/null || echo "   (ashmem_linux 不可用属正常，新内核走 memfd，忽略)"

# 让 binder 开机自动加载
echo "binder_linux" > /etc/modules-load.d/redroid-binder.conf
echo "options binder_linux devices=binder,hwbinder,vndbinder" > /etc/modprobe.d/redroid-binder.conf

# ---- 2. 模块校验（PoC D2 通过判据）----
echo "==> [2/4] 校验内核模块"
if lsmod | grep -qE 'binder'; then
  echo "   ✅ lsmod 可见 binder 模块"
else
  echo "   ⚠️  lsmod 未见 binder，可能已内建入内核（binder 直接编入时 lsmod 不显示）"
fi
if ls -l /dev/binderfs 2>/dev/null || ls -l /dev/binder* 2>/dev/null; then
  echo "   ✅ 存在 /dev/binderfs 或 /dev/binder*"
else
  echo "   ⚠️  未发现 /dev/binder*，起容器若失败请回看本步（PoC D2）"
fi

# ---- 3. Docker（若未装）----
echo "==> [3/4] 检查 / 安装 Docker"
if command -v docker >/dev/null 2>&1; then
  echo "   已安装：$(docker --version)"
else
  echo "   安装 Docker（get.docker.com）..."
  curl -fsSL https://get.docker.com | sh
fi
docker version >/dev/null 2>&1 && echo "   ✅ docker 可用" || echo "   ⚠️  docker 命令异常，检查 dockerd 是否启动"
# 把执行 sudo 的原用户加入 docker 组，免 sudo 用 docker
if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "$SUDO_USER" || true
  echo "   已将用户 ${SUDO_USER} 加入 docker 组（重新登录后生效）"
fi

# ---- 4. adb / scrcpy 校验 ----
echo "==> [4/4] 校验 adb / scrcpy"
command -v adb    >/dev/null 2>&1 && echo "   ✅ $(adb --version | head -1)" || echo "   ❌ adb 未安装"
command -v scrcpy >/dev/null 2>&1 && echo "   ✅ $(scrcpy --version | head -1)" || echo "   ⚠️  scrcpy 未安装（看画面用，可选）"

echo ""
echo "==================================================================="
echo "  ✅ 宿主机就绪。下一步："
echo "     1) 起单台：  deploy/redroid/start-instance.sh --id 0"
echo "     2) 批量：    deploy/redroid/batch-start.sh -n 10"
echo "     3) 群控：    deploy/stf/docker-compose.stf.yml"
echo "     4) 后端切 redroid：CLOUD_DEVICE_BACKEND=redroid（见 deploy/README.md）"
echo "==================================================================="
