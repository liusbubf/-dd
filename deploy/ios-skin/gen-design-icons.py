#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成设计稿图标资产：3 主题（ios/sunset/glass）× 20 图标，与 preview.py 设计稿一模一样。

产物（可重复运行，覆盖旧文件）：
- backend/app/skins/icons/{theme}/{NN}.png : 256x256 RGBA、透明背景、无文字标签。
  NN=00..15 对应 preview._APPS 顺序，16..19 对应 preview._DOCK 顺序。
- backend/app/skins/icons/manifest.json    : [{"index":0,"title":"信息"},...] 共 20 条。

实现：直接 import backend/app/preview.py，复用 _squircle/_APPS/_DOCK/THEMES 和各图标
字形函数；每主题拼一张 4 列 × 5 行网格 SVG（1024x1280，每格 256x256），Chrome 无头
一次性渲染成大图（Chrome 启动慢，全程仅 3 次调用），再用 Pillow 裁切出 20 块保存。

用法: /Users/fodelf/git/cloud/backend/.venv/bin/python gen-design-icons.py
     （需要 Pillow；Chrome 路径可用环境变量 CHROME 覆盖）
"""
import json
import os
import subprocess
import sys
import tempfile
import time

from PIL import Image

# ---- 路径（以脚本位置定位仓库根，任意 cwd 下可重复运行） ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(SCRIPT_DIR))
sys.path.insert(0, os.path.join(REPO, "backend"))
from app import preview  # noqa: E402  复用设计稿源码，保证与设计一模一样

OUT_DIR = os.path.join(REPO, "backend", "app", "skins", "icons")
CHROME = os.environ.get(
    "CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)

# ---- 网格参数：4 列 × 5 行，每格 256x256 → 大图 1024x1280 ----
CELL = 256
COLS, ROWS = 4, 5
BIG_W, BIG_H = COLS * CELL, ROWS * CELL

# 20 个图标：00..15 主屏 _APPS 顺序，16..19 Dock _DOCK 顺序
ICONS = list(preview._APPS) + list(preview._DOCK)
assert len(ICONS) == COLS * ROWS == 20


def build_grid_svg(theme_key: str) -> str:
    """按主题拼 4x5 网格 SVG：每格一个设计稿图标（squircle 底 + 顶部高光 + 字形），
    不带文字标签；linearGradient id 每格唯一，避免跨格串色。"""
    th = preview.THEMES[theme_key]
    rr = th["radius"]
    glass = th.get("glass", False)
    defs, body = [], []
    for i, (_label, c1, c2, glyph) in enumerate(ICONS):
        col, row = i % COLS, i // COLS
        x, y = col * CELL, row * CELL
        s = float(CELL)
        cx, cy = x + s / 2, y + s / 2
        if glass:
            # glass 主题：半透明白底 + 白描边，不用渐变（与 preview._icon 的 glass 分支一致）。
            # 描边宽度按设计稿（62px 图标、1px 描边）等比放大；描边矩形内缩半个描边宽，
            # 保证描边完整落在本格内，裁切后不越界串格。
            sw = s / 62.0
            body.append(preview._squircle(x, y, s, "#ffffff", 'opacity="0.16"', rr))
            body.append(preview._squircle(
                x + sw / 2, y + sw / 2, s - sw, "none",
                f'stroke="#ffffff" stroke-opacity="0.22" stroke-width="{sw:.1f}"', rr))
        else:
            # 渐变底：顶色 c1 → 底色 c2 垂直渐变，id 每格唯一
            defs.append(
                f'<linearGradient id="g{i}" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/>'
                f'</linearGradient>')
            body.append(preview._squircle(x, y, s, f"url(#g{i})", "", rr))
        # 顶部高光（所有主题一致）
        body.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{s:.1f}" height="{s*0.5:.1f}" '
                    f'rx="{s*rr:.1f}" fill="#ffffff" opacity="0.08"/>')
        # 图标字形（居中，参数与设计稿相同）
        body.append(glyph(cx, cy, s))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{BIG_W}" height="{BIG_H}" '
            f'viewBox="0 0 {BIG_W} {BIG_H}" '
            f'font-family="-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif">'
            f'<defs>{"".join(defs)}</defs>{"".join(body)}</svg>')


def render_svg_to_png(svg_path: str, png_path: str, workdir: str) -> None:
    """Chrome 无头渲染 SVG → 透明背景 PNG（一次渲染整张大图）。

    注意：部分 Chrome 版本写完 --screenshot 后进程不退出，所以这里不等进程结束，
    而是轮询产物文件：出现且大小稳定后主动结束 Chrome。
    """
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    for attempt in (1, 2):  # 偶发启动失败（与其他 Chrome 实例竞争等）时重试一次
        profile = tempfile.mkdtemp(prefix="chrome-profile-", dir=workdir)
        log_path = png_path + f".chrome.{attempt}.log"
        cmd = [
            CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
            "--timeout=25000", f"--screenshot={png_path}",
            f"--window-size={BIG_W},{BIG_H}", "--default-background-color=00000000",
            f"--user-data-dir={profile}", f"file://{svg_path}",
        ]
        with open(log_path, "wb") as log:
            proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=log)
            try:
                last = -1
                for _ in range(90):  # 最多等 90 秒（Chrome 启动约 10~20 秒）
                    time.sleep(1)
                    if proc.poll() is not None:
                        break  # 进程自己退出（成功或失败，下面按产物判断）
                    if os.path.exists(png_path):
                        size = os.path.getsize(png_path)
                        if size > 0 and size == last:
                            break  # 文件大小已稳定，截图写完
                        last = size
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
        if os.path.exists(png_path) and os.path.getsize(png_path) > 0:
            return
        sys.stderr.write(f"[warn] Chrome 第 {attempt} 次渲染失败，日志: {log_path}\n")
        time.sleep(3)
    raise RuntimeError(f"Chrome 未产出 {png_path}（日志见 {png_path}.chrome.*.log）")


def main() -> None:
    workdir = tempfile.mkdtemp(prefix="design-icons-")
    # 1) 三个主题：拼大图 SVG → Chrome 渲染 → Pillow 裁切 20 块
    for theme_key in preview.THEMES:
        theme_dir = os.path.join(OUT_DIR, theme_key)
        os.makedirs(theme_dir, exist_ok=True)
        svg_path = os.path.join(workdir, f"grid_{theme_key}.svg")
        big_png = os.path.join(workdir, f"grid_{theme_key}.png")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(build_grid_svg(theme_key))
        render_svg_to_png(svg_path, big_png, workdir)
        img = Image.open(big_png).convert("RGBA")
        if img.size != (BIG_W, BIG_H):
            raise RuntimeError(f"{theme_key} 大图尺寸异常: {img.size}")
        for i in range(len(ICONS)):
            col, row = i % COLS, i // COLS
            box = (col * CELL, row * CELL, (col + 1) * CELL, (row + 1) * CELL)
            out_path = os.path.join(theme_dir, f"{i:02d}.png")
            img.crop(box).save(out_path)
        print(f"wrote {theme_dir}/00.png .. {len(ICONS)-1:02d}.png")
    # 2) manifest.json：index → 标签（00..15 取 _APPS，16..19 取 _DOCK）
    manifest = [{"index": i, "title": app[0]} for i, app in enumerate(ICONS)]
    mpath = os.path.join(OUT_DIR, "manifest.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {mpath} ({len(manifest)} entries)")


if __name__ == "__main__":
    main()
