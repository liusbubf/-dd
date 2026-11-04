#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成主题壁纸资产（与设计稿 backend/app/preview.py 同源，可重复运行）。

产物（720x1280，不透明 PNG）：
  backend/app/skins/wallpaper_{theme}_{rid}.png   3 主题 x rid 0..2 = 9 张
  backend/app/skins/wallpaper_{theme}.png         rid=0 的兼容旧名副本（覆盖）

视觉规格 = preview._wallpaper()（逐项复刻，取色直接 import THEMES 保证同源）：
  (a,b,c,d) = THEMES[theme]["palettes"][rid]
  全屏线性渐变 x1=0 y1=0 x2=0.4 y2=1，stops: a@0 / b@0.55 / c@1
  柔光团1：radial cx=0.2 cy=0.15 r=0.5，d 0.55->0，覆盖全屏
  柔光团2：radial cx=0.9 cy=0.8 r=0.6，c 0.5->0，覆盖全屏

实现：每主题拼一张 2160x1280 的三联 SVG（3 个 <svg x=i*720> 子画布并排，
各含自己的 defs，id 按 rid 唯一化避免冲突），Chrome 无头一次渲染，
再用 pillow 切成 3 块 —— 共 3 次 Chrome 调用（Chrome 启动慢，务必少调）。

用法：backend/.venv/bin/python deploy/ios-skin/gen-theme-wallpapers.py
（需要 pillow；TMPDIR 可指定中间文件目录）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

# ---- 路径 ----
REPO = Path(__file__).resolve().parents[2]          # .../git/cloud
BACKEND = REPO / "backend"
OUT_DIR = BACKEND / "app" / "skins"                 # 壁纸产物目录
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 同源取色：直接 import 设计稿的 THEMES，避免复制色值导致两处漂移
sys.path.insert(0, str(BACKEND))
from app.preview import THEMES  # noqa: E402

# ---- 单张壁纸尺寸与三联画布 ----
W, H = 720, 1280                # 单张壁纸（redroid 720x1280）
N = 3                           # 每主题 rid 0..2 三张
TRIPTYCH_W = W * N              # 2160


def _panel_svg(rid: int, palette: tuple[str, str, str, str]) -> str:
    """一个 rid 的子画布（<svg x=rid*720>，defs id 按 rid 唯一化）。

    结构逐项复刻 preview._wallpaper()：线性渐变 + 两个柔光团。
    """
    a, b, c, d = palette
    wp, b1, b2 = f"wp{rid}", f"blob1_{rid}", f"blob2_{rid}"
    return (
        f'<svg x="{rid * W}" y="0" width="{W}" height="{H}">'
        f'<defs>'
        # 全屏线性渐变：a@0 / b@0.55 / c@1，方向 (0,0)->(0.4,1)
        f'<linearGradient id="{wp}" x1="0" y1="0" x2="0.4" y2="1">'
        f'<stop offset="0" stop-color="{a}"/><stop offset="0.55" stop-color="{b}"/>'
        f'<stop offset="1" stop-color="{c}"/></linearGradient>'
        # 柔光团1：左上，d 色 0.55->0
        f'<radialGradient id="{b1}" cx="0.2" cy="0.15" r="0.5">'
        f'<stop offset="0" stop-color="{d}" stop-opacity="0.55"/>'
        f'<stop offset="1" stop-color="{d}" stop-opacity="0"/></radialGradient>'
        # 柔光团2：右下，c 色 0.5->0
        f'<radialGradient id="{b2}" cx="0.9" cy="0.8" r="0.6">'
        f'<stop offset="0" stop-color="{c}" stop-opacity="0.5"/>'
        f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient>'
        f'</defs>'
        f'<rect width="{W}" height="{H}" fill="url(#{wp})"/>'
        f'<rect width="{W}" height="{H}" fill="url(#{b1})"/>'
        f'<rect width="{W}" height="{H}" fill="url(#{b2})"/>'
        # Dock 毛玻璃底板 + 页面圆点：Lawnchair v1 没有「圆角半透明 Dock 容器」
        # 选项（真机探针结论），壁纸是静态的 —— 画进壁纸视觉等效设计稿。
        # 坐标全部走 _wx/_wy 逆变换，直接按「屏幕上想要的位置」书写（见 WP_ZOOM）。
        + _dock_plate_svg()
        + f'</svg>'
    )


# ---- 壁纸→屏幕的显示变换（真机标定，务必先读这段再改坐标）----------------
# Android 显示系统壁纸时并非 1:1 贴图，而是**放大 1.1 倍后居中裁剪**（给桌面
# 滚动留视差余量）。早期版本按 1:1 计算 Dock 底板坐标，结果底板左右溢出屏幕、
# 上下与图标错位（现象：底板像"整体往上偏"，图标挤在底板顶部）。
#
# 标定方法与实测结果（deploy/ios-skin 下抓真机截图，量壁纸里已知图元的落点）：
#   720x1280 设备：壁纸圆点 cy=978,r=5  → 屏幕实测 cy=1011,r≈5.5
#                  1011 = 978*1.1 - 64，64 = (1280*1.1-1280)/2   ✅
#   1080x1920 设备：同一张 720x1280 壁纸 → 屏幕实测 cy=1517,直径16
#                  1517 = 978*1.65 - 96，1.65 = 1.1*(1920/1280)  ✅
# 两种分辨率均吻合，故变换为：screen = wp*Z - (源尺寸*Z-源尺寸)/2，Z=1.1。
WP_ZOOM = 1.1


def _wx(screen_x: float) -> float:
    """屏幕 x → 壁纸 x（720 宽基准）。"""
    return (screen_x + (W * WP_ZOOM - W) / 2) / WP_ZOOM


def _wy(screen_y: float) -> float:
    """屏幕 y → 壁纸 y（1280 高基准）。"""
    return (screen_y + (H * WP_ZOOM - H) / 2) / WP_ZOOM


# ---- 屏幕上期望的位置（720x1280 真机实测的 Dock 图标带）--------------------
# 实测：Dock 图标 y=1042..1156（高 114），4 个图标横向 x=42..678
DOCK_ICON_TOP, DOCK_ICON_BOTTOM = 1042, 1156
DOCK_ICON_LEFT, DOCK_ICON_RIGHT = 42, 678
DOCK_PAD = 16          # 底板在图标外的留白
DOCK_RADIUS = 40       # 屏幕上的圆角
DOT_R = 5              # 屏幕上的圆点半径
DOT_Y = 1004           # 圆点在底板上方
PAGES = 1              # 主屏页数（ios_layout 里 16 个图标全在 screen=0，就 1 页）


def _dock_plate_svg() -> str:
    """按屏幕期望位置反算出壁纸坐标，画 Dock 底板 + 页面圆点。"""
    x0, x1 = _wx(DOCK_ICON_LEFT - DOCK_PAD), _wx(DOCK_ICON_RIGHT + DOCK_PAD)
    y0, y1 = _wy(DOCK_ICON_TOP - DOCK_PAD), _wy(DOCK_ICON_BOTTOM + DOCK_PAD)
    w, h, rx = x1 - x0, y1 - y0, DOCK_RADIUS / WP_ZOOM
    parts = [
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'rx="{rx:.1f}" fill="#ffffff" opacity="0.16"/>',
        f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" '
        f'rx="{rx:.1f}" fill="none" stroke="#ffffff" stroke-opacity="0.14"/>',
    ]
    # 页面圆点按真实页数画：只有 1 页就只画 1 个，别让用户去左右滑一个不存在的页
    r, gap = DOT_R / WP_ZOOM, 22 / WP_ZOOM
    cy = _wy(DOT_Y)
    cx0 = _wx(W / 2) - (PAGES - 1) * gap / 2
    for i in range(PAGES):
        op = "" if i == 0 else ' opacity="0.4"'
        parts.append(f'<circle cx="{cx0 + i * gap:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#ffffff"{op}/>')
    return "".join(parts)


def _triptych_svg(theme: str) -> str:
    """一张 2160x1280 三联 SVG：rid 0..2 并排。"""
    panels = "".join(_panel_svg(rid, THEMES[theme]["palettes"][rid]) for rid in range(N))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{TRIPTYCH_W}" height="{H}" '
        f'viewBox="0 0 {TRIPTYCH_W} {H}">{panels}</svg>'
    )


def _render_svg(svg_path: Path, png_path: Path, tmp: Path, wait_s: int = 90) -> None:
    """Chrome 无头渲染 SVG -> PNG（去代理环境变量，独立 user-data-dir）。

    注意：Chrome 偶尔写完截图后卡在退出阶段（如磁盘紧张时持久化 profile 失败），
    所以不等它自然退出 —— 轮询截图文件，出现且体积稳定后直接杀掉 Chrome，
    并立刻删除本次 profile 释放磁盘。
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
    profile = tempfile.mkdtemp(dir=tmp, prefix="chrome-profile-")
    cmd = [
        CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
        "--hide-scrollbars", "--timeout=25000",
        f"--screenshot={png_path}", f"--window-size={TRIPTYCH_W},{H}",
        f"--user-data-dir={profile}", f"file://{svg_path}",
    ]
    proc = subprocess.Popen(cmd, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        last = -1
        deadline = time.time() + wait_s
        while time.time() < deadline:
            time.sleep(1.0)
            if png_path.exists():
                size = png_path.stat().st_size
                if size > 0 and size == last:
                    break  # 截图已写完且体积稳定
                last = size
            if proc.poll() is not None:
                break  # Chrome 自己退出了
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)
    if not png_path.exists() or png_path.stat().st_size == 0:
        raise RuntimeError(f"Chrome 未产出截图: {png_path}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="theme-wallpapers-"))
    written: list[Path] = []
    try:
        for theme in THEMES:  # ios / sunset / glass
            svg_path = tmp / f"triptych_{theme}.svg"
            big_png = tmp / f"triptych_{theme}.png"
            svg_path.write_text(_triptych_svg(theme), encoding="utf-8")
            # 每主题 1 次 Chrome 调用；偶发失败（磁盘紧张等）重试一次
            for attempt in (1, 2):
                try:
                    _render_svg(svg_path, big_png, tmp)
                    break
                except RuntimeError:
                    if attempt == 2:
                        raise
                    time.sleep(3)

            img = Image.open(big_png)
            if img.size != (TRIPTYCH_W, H):
                raise RuntimeError(f"{theme} 三联图尺寸异常: {img.size}，期望 {(TRIPTYCH_W, H)}")
            for rid in range(N):
                piece = img.crop((rid * W, 0, (rid + 1) * W, H)).convert("RGB")  # 壁纸不透明
                out = OUT_DIR / f"wallpaper_{theme}_{rid}.png"
                piece.save(out, "PNG")
                written.append(out)
            # 兼容旧名：rid=0 复制为 wallpaper_{theme}.png（覆盖现有）
            legacy = OUT_DIR / f"wallpaper_{theme}.png"
            shutil.copyfile(OUT_DIR / f"wallpaper_{theme}_0.png", legacy)
            written.append(legacy)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for p in written:
        print(f"wrote {p} ({p.stat().st_size} bytes)")
    print(f"done: {len(written)} files")


if __name__ == "__main__":
    main()
