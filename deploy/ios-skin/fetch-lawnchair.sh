#!/usr/bin/env bash
# =============================================================================
# 下载「一键换肤」用的 Lawnchair 启动器 APK（官方 GitHub Releases 原版）
# 到 backend/app/skins/lawnchair.apk（*.apk 不入 git，克隆后跑一次本脚本即可）。
#
# 版本锁定 1.2.0.1884 —— 与真机验证一致（包名 ch.deletescape.lawnchair，
# Android 12/arm64 redroid 实测可用；换版本前先在单机验证偏好 key 兼容性）。
# =============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:-$HERE/../../backend/app/skins/lawnchair.apk}"
URL="https://github.com/LawnchairLauncher/lawnchair/releases/download/1.2.0.1884/Lawnchair-1.2.0.1884.apk"

if [ -f "$DEST" ]; then
  echo "已存在：$DEST（如需重下先删除）"
  exit 0
fi
echo "==> 下载 $URL"
curl -sL --fail -o "$DEST" "$URL"
echo "✅ $(du -h "$DEST" | cut -f1)  $DEST"
