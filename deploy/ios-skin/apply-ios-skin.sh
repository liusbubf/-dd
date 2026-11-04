#!/usr/bin/env bash
# =============================================================================
# 给真实 Redroid 实例套「皮肤级」iOS 桌面 —— 已在真机(device1, Android 12/arm64)跑通。
# 对应计划 D2 / CP-101「苹果 UI 基础」。产出效果见 docs/screenshots/真机_iOS皮肤.png。
#
# 实测能跑通的四件事（全部开源、无 Apple 私有资源）：
#   1) iOS 壁纸  ：无依赖 python 生成蓝紫粉渐变 PNG → 写进系统壁纸文件 → 重启实例加载
#   2) 圆角(squircle) 蒙版：写 Lawnchair V1 偏好 pref_override_icon_shape = 超椭圆 path
#                          （Android 12 系统默认蒙版本身就是圆角方形，两者叠加更稳）
#   3) 4 列网格 + Dock ：写 pref_numCols/numRows/numHotseatIcons，并重排 launcher.db
#   4) 默认启动器：装 Lawnchair → set-home-activity（若尚未设置）
#
# 关键坑（都踩过）：
#   * AOSP 没有 `adb set-wallpaper` CLI，本镜像 `cmd wallpaper` 也是空实现 → 只能写壁纸文件+重启。
#   * Lawnchair 偏好开机会跑一次「迁移」重写 XML：**整体覆盖会被重置**，必须**合并**(在 </map>
#     前插入 key)，且要在**壁纸重启完成之后**再写偏好，最后只重启启动器 → key 才留得住。
#   * 偏好里 numRows/numCols/numHotseatIcons/override_icon_shape **都是 String 型**，
#     写成 int 会 ClassCastException 崩启动器。
#   * 容器内 sqlite3 会 abort → 改 launcher.db 要把 db 拷到 VM 用 python3(自带 sqlite3) 改。
#
# 环境假设（可用同名环境变量覆盖）：
#   redroid 容器跑在 lima VM「redroid」；容器名 redroid_N；adb 在 VM 内，端口=5555+N；
#   adb shell 非 root，root 走 `sudo docker exec redroid_N`；/data 为持久 bind mount(重启不丢)；
#   SELinux=Disabled(permissive)。
#
# 用法：
#   ./apply-ios-skin.sh [device_index=1] [launcher.apk(可选)]
#
# 字体合规：禁止内置 Apple SF；用 HarmonyOS Sans / 思源黑体 / Inter（见 README.md）。
# iOS 图标包(iOS 字形美术)：暂缺开源且授权明确的成品 → 见 README「图标包」小节，手动/后补。
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# ---- 可覆盖的环境抽象 --------------------------------------------------------
DEVICE="${1:-${DEVICE:-1}}"
LAUNCHER_APK="${2:-}"
SERIAL="${SERIAL:-localhost:$((5555 + DEVICE))}"
CONTAINER="${CONTAINER:-redroid_${DEVICE}}"
LAUNCHER_PKG="${LAUNCHER_PKG:-ch.deletescape.lawnchair}"
PREFS="/data/data/${LAUNCHER_PKG}/shared_prefs/${LAUNCHER_PKG}_preferences.xml"
DB="/data/data/${LAUNCHER_PKG}/databases/launcher.db"

ADB="${ADB:-limactl shell redroid -- adb}"                              # adb 包装
ROOT="${ROOT:-limactl shell redroid -- sudo docker exec ${CONTAINER}}"  # 容器内 root
VMSH="${VMSH:-limactl shell redroid -- bash -c}"                        # VM 里跑 bash(有 python3+sqlite3)
DKR="${DKR:-limactl shell redroid -- sudo docker}"                     # docker(cp/restart)
WALLPAPER="${WALLPAPER:-$HERE/ios-wallpaper.png}"
# squircle 超椭圆 path（Launcher3 IconShapeOverride 标准值）
SQUIRCLE='M50,0 C10,0 0,10 0,50 0,90 10,100 50,100 90,100 100,90 100,50 100,10 90,0 50,0 Z'

say(){ echo "==> $*"; }
$ADB connect "$SERIAL" >/dev/null 2>&1 || true

# ---- 0) 壁纸不存在则生成（纯标准库，无需 PIL/imagemagick）-------------------
if [ ! -f "$WALLPAPER" ]; then
  say "生成 iOS 壁纸 → $WALLPAPER"; python3 "$HERE/gen-wallpaper.py" "$WALLPAPER"
fi

# ---- 1) （可选）安装启动器并设为默认 HOME -----------------------------------
if [ -n "$LAUNCHER_APK" ] && [ -f "$LAUNCHER_APK" ]; then
  say "安装启动器：$LAUNCHER_APK"; $ADB -s "$SERIAL" install -r "$LAUNCHER_APK"
fi
if $ADB -s "$SERIAL" shell pm list packages 2>/dev/null | grep -q "$LAUNCHER_PKG"; then
  ACT="$($ADB -s "$SERIAL" shell cmd package resolve-activity -a android.intent.action.MAIN \
        -c android.intent.category.HOME "$LAUNCHER_PKG" 2>/dev/null | tr -d '\r' \
        | grep -oE 'name=[^ ]+' | head -1 | cut -d= -f2)"
  [ -n "$ACT" ] && { say "设为默认桌面：$LAUNCHER_PKG/$ACT"; \
      $ADB -s "$SERIAL" shell cmd package set-home-activity "$LAUNCHER_PKG/$ACT" || true; }
fi

# ---- 2) 重排 launcher.db：应用铺进 4 列网格 + 填满 Dock（会随重启一起生效）--
say "重排桌面网格 launcher.db"
APPS_TSV="$($ADB -s "$SERIAL" shell cmd package query-activities --brief \
  -a android.intent.action.MAIN -c android.intent.category.LAUNCHER 2>/dev/null \
  | grep -oE '[a-zA-Z0-9_.]+/[a-zA-Z0-9_.]+' | grep -v "^${LAUNCHER_PKG}/" | sort -u \
  | while read -r comp; do
      lbl="$($ADB -s "$SERIAL" shell dumpsys package "$comp" 2>/dev/null \
             | grep -m1 -oE 'label=[^ ]+' | cut -d= -f2 | tr -d '\r')"
      printf '%s\t%s\n' "${lbl:-${comp%%/*}}" "$comp"
    done)"
if [ -n "$APPS_TSV" ]; then
  $ROOT am force-stop "$LAUNCHER_PKG"
  $DKR cp "$CONTAINER":"$DB" /tmp/launcher.db
  $VMSH "sudo chmod 666 /tmp/launcher.db; printf '%s' \"$APPS_TSV\" | python3 '$HERE/populate-grid.py' /tmp/launcher.db"
  $DKR cp /tmp/launcher.db "$CONTAINER":"$DB"
  $ROOT sh -c "rm -f ${DB}-journal; own=\$(stat -c '%u:%g' /data/data/$LAUNCHER_PKG/databases); chown \$own '$DB'; chmod 660 '$DB'"
fi

# ---- 3) 壁纸：写进系统壁纸文件（AOSP 无 adb set-wallpaper CLI）--------------
say "铺 iOS 壁纸 → /data/system/users/0/wallpaper"
$ADB -s "$SERIAL" push "$WALLPAPER" /sdcard/ios-wallpaper.png >/dev/null 2>&1 || true
$DKR cp "$WALLPAPER" "$CONTAINER":/data/system/users/0/wallpaper
$ROOT sh -c "
  cp /data/system/users/0/wallpaper /data/system/users/0/wallpaper_orig
  chown 1000:1000 /data/system/users/0/wallpaper /data/system/users/0/wallpaper_orig
  chmod 600 /data/system/users/0/wallpaper /data/system/users/0/wallpaper_orig
"

# ---- 4) 重启实例：壁纸+网格随开机加载；开机迁移也在此发生（之后再写偏好才留得住）
say "重启实例 $CONTAINER 加载壁纸/网格…"
$DKR restart "$CONTAINER" >/dev/null
say "等待开机完成…"
until [ "$($ADB -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; do
  $ADB connect "$SERIAL" >/dev/null 2>&1 || true; sleep 3
done

# ---- 5) 写 Lawnchair 偏好：4 列网格 + Dock4 + squircle 圆角 -----------------
# 必须「合并」(往 Lawnchair 已生成的 XML 里插 key)，且在开机迁移之后；否则会被重置。
say "合并偏好(网格/Dock/圆角) → $PREFS"
$ROOT sh -c "
  am force-stop $LAUNCHER_PKG
  P='$PREFS'
  # 若 Lawnchair 还没生成偏好文件，先建一个最小骨架
  [ -f \"\$P\" ] || printf \"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map>\n</map>\n\" > \"\$P\"
  # 幂等：先删掉旧的同名 key，再在 </map> 前插入
  sed -i '/name=\"pref_numRows\"/d;/name=\"pref_numCols\"/d;/name=\"pref_numHotseatIcons\"/d;/name=\"pref_override_icon_shape\"/d' \"\$P\"
  sed -i \"s#</map>#    <string name=\\\"pref_numRows\\\">6</string>\n    <string name=\\\"pref_numCols\\\">4</string>\n    <string name=\\\"pref_numHotseatIcons\\\">4</string>\n    <string name=\\\"pref_override_icon_shape\\\">$SQUIRCLE</string>\n</map>#\" \"\$P\"
  own=\$(stat -c '%u:%g' /data/data/$LAUNCHER_PKG/shared_prefs); chown \$own \"\$P\"; chmod 660 \"\$P\"
"
$ADB -s "$SERIAL" shell am start -a android.intent.action.MAIN -c android.intent.category.HOME >/dev/null 2>&1 || true

echo "✅ 完成。截图核验："
echo "   $ADB -s $SERIAL exec-out screencap -p | base64 > /tmp/s.b64   # 再 base64 -d 存到 docs/screenshots/"
echo "   参考成品：docs/screenshots/真机_iOS皮肤.png"
