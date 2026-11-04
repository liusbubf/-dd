#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把外部设计师（ChatGPT）产出的 SVG 资产解析、校验、渲染成真机可用的 PNG。

输入 = 一个或多个「GPT 回复原文」文本/markdown 文件，格式见同目录 GPT设计需求.md §4：
  <!-- icon 00 信息 -->        + ```svg …```      × 20   （viewBox 0 0 256 256）
  <!-- wallpaper ios 0 -->     + ```svg …```      × 9    （720×1280）
  ```json …```                 变体色板规则（sunset 替换表 / glass 毛玻璃参数）

产物与 gen-design-icons.py / gen-theme-wallpapers.py 完全一致（换肤引擎直接可用）：
  backend/app/skins/icons/{theme}/{NN}.png     256×256 RGBA
  backend/app/skins/icons/manifest.json
  backend/app/skins/wallpaper_{theme}_{rid}.png 720×1280（+ rid0 覆盖旧名）

用法：
  # 只校验不渲染（快，先确认 GPT 产出合格）
  backend/.venv/bin/python deploy/ios-skin/import-gpt-assets.py gpt回复.md --dry-run
  # 校验 + 渲染 + 写入资产目录
  backend/.venv/bin/python deploy/ios-skin/import-gpt-assets.py gpt回复*.md
  # 渲染到别处试看（不碰线上资产）
  backend/.venv/bin/python deploy/ios-skin/import-gpt-assets.py gpt回复.md --out-dir /tmp/try

设计要点：
- 单个 SVG 的 id 会被加前缀隔离（icon00_xxx），避免拼进大画布后 id 撞车导致渐变错乱。
- Chrome 启动一次要 10~20s，所以图标拼 4×5 网格、壁纸拼三联，一次渲染再切割。
- 校验不通过的条目会指名报错（哪个编号、什么问题），便于让设计师按编号重画单个。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

ICON_N, ICON_PX = 20, 256          # 20 个图标，每个 256×256
GRID_COLS, GRID_ROWS = 4, 5        # 拼图网格
WP_W, WP_H, WP_N = 720, 1280, 3    # 壁纸 720×1280，每主题 3 张
THEMES = ("ios", "sunset", "glass")

# 图标标题（顺序即编号，与 preview._APPS + _DOCK、换肤引擎 ios_layout 严格一致）
TITLES = [
    "信息", "日历", "照片", "相机", "时钟", "地图", "天气", "备忘录",
    "提醒", "股市", "钱包", "设置", "App Store", "音乐", "播客", "文件",
    "电话", "Safari", "信息", "音乐",
]

_ICON_RE = re.compile(
    r"<!--\s*icon\s+(\d{2})[^>]*-->\s*```(?:svg|xml|html)?\s*(.*?)```",
    re.S | re.I,
)
_WP_RE = re.compile(
    r"<!--\s*wallpaper\s+(ios|sunset|glass)\s+([0-2])\s*-->\s*```(?:svg|xml|html)?\s*(.*?)```",
    re.S | re.I,
)
_JSON_RE = re.compile(r"```json\s*(.*?)```", re.S | re.I)


# ---------------------------------------------------------------- 解析 + 校验
def _strip_decl(svg: str) -> str:
    """去掉 XML 声明/DOCTYPE（嵌套进大画布时不能带）。"""
    svg = re.sub(r"<\?xml[^>]*\?>", "", svg)
    svg = re.sub(r"<!DOCTYPE[^>]*>", "", svg)
    return svg.strip()


def _check_common(svg: str, who: str) -> list[str]:
    """所有 SVG 的共同硬约束：合法 XML、无文字、无外部引用。"""
    errs: list[str] = []
    try:
        ET.fromstring(svg)
    except ET.ParseError as e:
        errs.append(f"{who}: XML 不合法（{e}）")
        return errs  # 解析失败后续检查无意义
    if re.search(r"<text[\s>]|<tspan[\s>]", svg, re.I):
        errs.append(f"{who}: 含 <text>/<tspan>（资产内不允许文字，标签由启动器绘制）")
    if re.search(r"<image[\s>]", svg, re.I):
        errs.append(f"{who}: 含 <image>（禁止位图嵌入/外链）")
    for m in re.finditer(r'(?:href|xlink:href)\s*=\s*"([^"]+)"', svg, re.I):
        if not m.group(1).startswith("#"):
            errs.append(f"{who}: 含外部引用 href={m.group(1)}")
    if re.search(r"@import|https?://(?!www\.w3\.org)", svg, re.I):
        errs.append(f"{who}: 含外链资源（必须自包含）")
    ids = re.findall(r'\bid="([^"]+)"', svg)
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        errs.append(f"{who}: id 重复 {sorted(dup)}")
    return errs


def _check_icon(svg: str, nn: str) -> list[str]:
    errs = _check_common(svg, f"icon {nn}")
    if not errs:
        vb = (ET.fromstring(svg).get("viewBox") or "").replace(",", " ").split()
        if [float(v) for v in vb] != [0, 0, ICON_PX, ICON_PX] if len(vb) == 4 else True:
            errs.append(f"icon {nn}: viewBox 应为 '0 0 {ICON_PX} {ICON_PX}'，实际 '{' '.join(vb)}'")
    return errs


def _check_wallpaper(svg: str, key: str) -> list[str]:
    errs = _check_common(svg, f"wallpaper {key}")
    if not errs:
        root = ET.fromstring(svg)
        w, h = root.get("width", ""), root.get("height", "")
        if str(w).rstrip("px") != str(WP_W) or str(h).rstrip("px") != str(WP_H):
            errs.append(f"wallpaper {key}: 尺寸应为 {WP_W}×{WP_H}，实际 {w}×{h}")
    return errs


_FILE_ICON_RE = re.compile(r"^(\d{2})[-_]", re.I)
_FILE_WP_RE = re.compile(r"^wallpaper[-_](ios|sunset|glass)[-_]([0-2])\b", re.I)


def _scan_dir(d: Path, icons: dict[str, str], walls: dict[str, str]) -> dict | None:
    """目录模式：直接收 NN-*.svg / wallpaper-{theme}-{rid}.svg / *.json。

    设计方常按文件交付（比贴代码块更省事），此处与代码块模式等价支持。
    """
    palette = None
    for f in sorted(d.iterdir()):
        if f.suffix.lower() == ".svg":
            if m := _FILE_ICON_RE.match(f.name):
                icons[m.group(1)] = _strip_decl(f.read_text(encoding="utf-8", errors="replace"))
            elif m := _FILE_WP_RE.match(f.name):
                key = f"{m.group(1).lower()}_{m.group(2)}"
                walls[key] = _strip_decl(f.read_text(encoding="utf-8", errors="replace"))
        elif f.suffix.lower() == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and ("sunset" in data or "glass" in data):
                palette = data
    return palette


def parse_sources(paths: list[Path]) -> tuple[dict[str, str], dict[str, str], dict | None]:
    """从多个回复文件/资产目录里汇总图标/壁纸/色板。

    后出现的同编号覆盖先出现的，便于「只重画某几个」时补发文件叠加进来。
    """
    icons: dict[str, str] = {}
    walls: dict[str, str] = {}
    palette: dict | None = None
    for p in paths:
        if p.is_dir():
            if (pal := _scan_dir(p, icons, walls)) is not None:
                palette = pal
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for nn, svg in _ICON_RE.findall(text):
            icons[nn] = _strip_decl(svg)
        for theme, rid, svg in _WP_RE.findall(text):
            walls[f"{theme}_{rid}"] = _strip_decl(svg)
        for blob in _JSON_RE.findall(text):
            try:
                data = json.loads(blob)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and ("sunset" in data or "glass" in data):
                palette = data
    return icons, walls, palette


# ------------------------------------------------------------ 主题变体（套规则）
def _apply_sunset(svg: str, colors: list[str]) -> str:
    """sunset 变体：把底色渐变（id=base）的 stops 依次换成暖色三色。"""
    m = re.search(r'<linearGradient id="base".*?</linearGradient>', svg, re.S | re.I)
    if not m:
        return svg
    block = new_block = m.group(0)
    for stop, color in zip(re.findall(r"<stop\b[^>]*/?>", block), colors):
        new_block = new_block.replace(
            stop, re.sub(r'stop-color="[^"]*"', f'stop-color="{color}"', stop), 1
        )
    return svg.replace(block, new_block, 1)


def _apply_glass(svg: str, rule: dict) -> str:
    """glass 变体：底色渐变填充 → 半透明白 + 描边（毛玻璃质感，字形保持原样）。"""
    b = rule.get("base", {})
    fill = (
        f'fill="{b.get("fill", "#FFFFFF")}" fill-opacity="{b.get("fill_opacity", 0.16)}" '
        f'stroke="{b.get("stroke", "#FFFFFF")}" stroke-opacity="{b.get("stroke_opacity", 0.22)}" '
        f'stroke-width="3"'
    )
    return svg.replace('fill="url(#base)"', fill, 1)


def build_variants(icons: dict[str, str], palette: dict | None) -> dict[str, dict[str, str]]:
    """由 ios 原稿 + 色板规则派生 sunset / glass 两套图标 SVG。"""
    out: dict[str, dict[str, str]] = {"ios": dict(icons)}
    if not palette:
        return out
    if sun := palette.get("sunset"):
        table = sun.get("icons", {})
        out["sunset"] = {
            nn: _apply_sunset(svg, table[nn]) if nn in table else svg
            for nn, svg in icons.items()
        }
    if glass := palette.get("glass"):
        out["glass"] = {nn: _apply_glass(svg, glass) for nn, svg in icons.items()}
    return out


# ---------------------------------------------------------------- 渲染
def _namespace_ids(svg_body: str, prefix: str) -> str:
    """给单个 SVG 内的 id 加前缀并同步引用 —— 拼进大画布时防 id 撞车。

    精确匹配 id="X" / url(#X) / href="#X"，故 g1 不会误伤 g10。
    """
    for i in sorted(set(re.findall(r'\bid="([^"]+)"', svg_body)), key=len, reverse=True):
        e = re.escape(i)
        svg_body = re.sub(rf'id="{e}"', f'id="{prefix}{i}"', svg_body)
        svg_body = re.sub(rf"url\(#{e}\)", f"url(#{prefix}{i})", svg_body)
        svg_body = re.sub(rf'href="#{e}"', f'href="#{prefix}{i}"', svg_body)
    return svg_body


def _inner(svg: str) -> str:
    """取 <svg> 根标签内部内容（含 defs），用于嵌套。"""
    m = re.search(r"<svg[^>]*>(.*)</svg\s*>", svg, re.S | re.I)
    return m.group(1) if m else svg


def _render(svg_path: Path, png_path: Path, w: int, h: int, tmp: Path, wait_s: int = 90) -> None:
    """Chrome 无头渲染（与 gen-theme-wallpapers.py 同源：截图写完即杀，防卡退出）。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")}
    profile = tempfile.mkdtemp(dir=tmp, prefix="chrome-profile-")
    proc = subprocess.Popen(
        [CHROME, "--headless", "--no-sandbox", "--disable-gpu", "--no-first-run",
         "--hide-scrollbars", "--timeout=25000", f"--screenshot={png_path}",
         f"--window-size={w},{h}", "--default-background-color=00000000",
         f"--user-data-dir={profile}", f"file://{svg_path}"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        last, deadline = -1, time.time() + wait_s
        while time.time() < deadline:
            time.sleep(1.0)
            if png_path.exists():
                size = png_path.stat().st_size
                if size > 0 and size == last:
                    break
                last = size
            if proc.poll() is not None:
                break
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
        shutil.rmtree(profile, ignore_errors=True)
    if not png_path.exists() or png_path.stat().st_size == 0:
        raise RuntimeError(f"Chrome 未产出截图: {png_path}")


def render_icons(icons: dict[str, str], out_dir: Path, tmp: Path, theme: str = "ios") -> list[str]:
    """20 个图标拼 4×5 网格一次渲染再切割；返回警告（如四角不透明）。"""
    warn: list[str] = []
    gw, gh = GRID_COLS * ICON_PX, GRID_ROWS * ICON_PX
    cells = []
    for idx in range(ICON_N):
        nn = f"{idx:02d}"
        body = _namespace_ids(_inner(icons[nn]), f"i{nn}_")
        x, y = (idx % GRID_COLS) * ICON_PX, (idx // GRID_COLS) * ICON_PX
        cells.append(
            f'<svg x="{x}" y="{y}" width="{ICON_PX}" height="{ICON_PX}" '
            f'viewBox="0 0 {ICON_PX} {ICON_PX}">{body}</svg>'
        )
    svg_path, png_path = tmp / f"icons_grid_{theme}.svg", tmp / f"icons_grid_{theme}.png"
    svg_path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{gw}" height="{gh}" '
        f'viewBox="0 0 {gw} {gh}">{"".join(cells)}</svg>',
        encoding="utf-8",
    )
    _render(svg_path, png_path, gw, gh, tmp)

    big = Image.open(png_path).convert("RGBA")
    if big.size != (gw, gh):
        raise RuntimeError(f"图标网格尺寸异常 {big.size}，期望 {(gw, gh)}")
    theme_dir = out_dir / "icons" / theme
    theme_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(ICON_N):
        x, y = (idx % GRID_COLS) * ICON_PX, (idx // GRID_COLS) * ICON_PX
        piece = big.crop((x, y, x + ICON_PX, y + ICON_PX))
        # 四角必须透明（squircle 之外透出壁纸）
        corners = [piece.getpixel(p)[3] for p in ((0, 0), (ICON_PX - 1, 0),
                                                 (0, ICON_PX - 1), (ICON_PX - 1, ICON_PX - 1))]
        if max(corners) > 8:
            warn.append(f"{theme} icon {idx:02d}: 四角不透明（alpha={corners}），squircle 外应透明")
        piece.save(theme_dir / f"{idx:02d}.png", "PNG")
    (out_dir / "icons" / "manifest.json").write_text(
        json.dumps([{"index": i, "title": t} for i, t in enumerate(TITLES)],
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return warn


# Dock 毛玻璃底板 + 双页圆点：Lawnchair v1 无「圆角半透明 Dock 容器」选项（真机探针
# 结论），故画进静态壁纸；坐标按 720×1280 真机 hotseat 实测锚定（与 gen-theme-
# wallpapers.py 一致）。设计方只需保证壁纸底部干净，不必画底板。
_DOCK_OVERLAY = (
    '<rect x="26" y="1010" width="668" height="170" rx="48" fill="#ffffff" opacity="0.16"/>'
    '<rect x="26" y="1010" width="668" height="170" rx="48" fill="none" stroke="#ffffff" stroke-opacity="0.14"/>'
    '<circle cx="349" cy="978" r="5" fill="#ffffff"/>'
    '<circle cx="371" cy="978" r="5" fill="#ffffff" opacity="0.4"/>'
)


def render_wallpapers(walls: dict[str, str], out_dir: Path, tmp: Path) -> None:
    """每主题 3 张拼三联一次渲染再切割。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        keys = [f"{theme}_{r}" for r in range(WP_N)]
        if not all(k in walls for k in keys):
            continue
        panels = "".join(
            f'<svg x="{r * WP_W}" y="0" width="{WP_W}" height="{WP_H}" '
            f'viewBox="0 0 {WP_W} {WP_H}">'
            f'{_namespace_ids(_inner(walls[f"{theme}_{r}"]), f"w{theme}{r}_")}'
            f"{_DOCK_OVERLAY}</svg>"
            for r in range(WP_N)
        )
        tw = WP_W * WP_N
        svg_path, png_path = tmp / f"wp_{theme}.svg", tmp / f"wp_{theme}.png"
        svg_path.write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{tw}" height="{WP_H}" '
            f'viewBox="0 0 {tw} {WP_H}">{panels}</svg>',
            encoding="utf-8",
        )
        _render(svg_path, png_path, tw, WP_H, tmp)
        big = Image.open(png_path)
        for r in range(WP_N):
            piece = big.crop((r * WP_W, 0, (r + 1) * WP_W, WP_H)).convert("RGB")
            piece.save(out_dir / f"wallpaper_{theme}_{r}.png", "PNG")
        shutil.copyfile(out_dir / f"wallpaper_{theme}_0.png", out_dir / f"wallpaper_{theme}.png")


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser(description="导入 GPT 产出的 iOS 皮肤设计资产")
    ap.add_argument("sources", nargs="+", type=Path, help="GPT 回复原文或资产目录（可多个）")
    ap.add_argument("--dry-run", action="store_true", help="只解析校验，不渲染不写文件")
    ap.add_argument("--out-dir", type=Path, default=BACKEND / "app" / "skins",
                    help="资产输出目录（默认 backend/app/skins，测试时可指向别处）")
    args = ap.parse_args()

    icons, walls, palette = parse_sources(args.sources)
    print(f"解析：图标 {len(icons)}/{ICON_N}，壁纸 {len(walls)}/{len(THEMES) * WP_N}，"
          f"色板 {'有' if palette else '无'}")

    errs: list[str] = []
    for idx in range(ICON_N):
        nn = f"{idx:02d}"
        if nn not in icons:
            errs.append(f"icon {nn}（{TITLES[idx]}）: 缺失")
        else:
            errs += _check_icon(icons[nn], nn)
    for theme in THEMES:
        for r in range(WP_N):
            key = f"{theme}_{r}"
            if key not in walls:
                errs.append(f"wallpaper {key}: 缺失")
            else:
                errs += _check_wallpaper(walls[key], key)

    if errs:
        print(f"\n✗ 校验未通过（{len(errs)} 项），把下列条目按编号退回重画：")
        for e in errs:
            print(f"  - {e}")
        # 图标齐全时仍可继续渲染已有部分，但缺失/非法就停下，避免半套资产上机
        sys.exit(1)
    print("✓ 校验通过：XML 合法 / 尺寸正确 / 无文字 / 无外链 / id 无冲突")

    if args.dry_run:
        print("（--dry-run：未渲染、未写文件）")
        return

    by_theme = build_variants(icons, palette)
    print(f"主题：{'/'.join(by_theme)}（sunset/glass 由 ios 原稿套色板规则派生）")

    tmp = Path(tempfile.mkdtemp(prefix="gpt-assets-"))
    warn: list[str] = []
    try:
        for theme, theme_icons in by_theme.items():
            warn += render_icons(theme_icons, args.out_dir, tmp, theme)
        render_wallpapers(walls, args.out_dir, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if palette is not None:
        (args.out_dir / "icons" / "palette.json").write_text(
            json.dumps(palette, ensure_ascii=False, indent=1), encoding="utf-8")
    for w in warn:
        print(f"⚠ {w}")
    print(f"✓ 资产已写入 {args.out_dir}")
    print("  下一步：部署 VM 后对设备换肤验证 —— "
          "limactl shell redroid -- bash deploy/scripts/vm-run-backend.sh")


if __name__ == "__main__":
    main()
