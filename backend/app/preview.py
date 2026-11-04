"""预览帧渲染 —— 高保真「iOS 设计语言」原创皮肤（SVG，base64 data URL）。

设计合规：本模块全部为**原创矢量素材**，忠实还原 iOS 的设计语言（灵动岛、状态栏
字形、超椭圆图标、毛玻璃 Dock/控制中心、锁屏大时钟等），**不使用 Apple 的实际
图标美术 / 壁纸 / SF 字体**。字体用系统栈（由查看端渲染，不打包）。

Simulator 后端用它把设备状态渲染成手机画面；也用于「iOS 皮肤查看器」展示主屏/锁屏/
控制中心三套界面。RedroidBackend 的真实 screencap 优先，取不到时回退本渲染。
"""
from __future__ import annotations

import base64
import datetime
import html

W, H = 440, 820  # 预览画布（点）

# ---- 通用色 ----
TXT = "#ffffff"


def _esc(s) -> str:
    return html.escape(str(s))


def _squircle(x: float, y: float, s: float, fill: str, extra: str = "", rr: float = 0.225) -> str:
    """iOS 超椭圆图标底（用大圆角矩形逼近，圆角比例 rr）。"""
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{s:.1f}" height="{s:.1f}" rx="{s*rr:.1f}" fill="{fill}" {extra}/>'


# ============================================================================
# 图标字形（原创、通用符号）——参数为图标中心 cx,cy 与图标边长 s
# ============================================================================
def _g_message(cx, cy, s):
    r = s * 0.30
    return (f'<g fill="#fff"><path d="M{cx-r:.1f},{cy-r*0.8:.1f} '
            f'a{r:.1f},{r*0.82:.1f} 0 1,1 0,{r*1.64:.1f} l{-r*0.35:.1f},{r*0.5:.1f} '
            f'q{r*0.05:.1f},{-r*0.4:.1f} {r*0.18:.1f},{-r*0.55:.1f} '
            f'a{r:.1f},{r*0.82:.1f} 0 0,1 {-r*0.18:.1f},{-r*1.09:.1f} z" '
            f'transform="rotate(0 {cx:.1f} {cy:.1f})"/></g>')


def _g_phone(cx, cy, s):
    r = s * 0.26
    return (f'<path transform="rotate(-8 {cx:.1f} {cy:.1f})" fill="#fff" '
            f'd="M{cx-r:.1f},{cy-r:.1f} q{-r*0.15:.1f},{r*0.15:.1f} 0,{r*0.55:.1f} '
            f'q{r*0.6:.1f},{r*1.1:.1f} {r*1.7:.1f},{r*1.4:.1f} '
            f'q{r*0.4:.1f},{r*0.12:.1f} {r*0.55:.1f},{-r*0.05:.1f} '
            f'l{r*0.32:.1f},{-r*0.4:.1f} q{r*0.12:.1f},{-r*0.18:.1f} {-r*0.08:.1f},{-r*0.34:.1f} '
            f'l{-r*0.5:.1f},{-r*0.34:.1f} q{-r*0.16:.1f},{-r*0.1:.1f} {-r*0.3:.1f},{r*0.02:.1f} '
            f'l{-r*0.18:.1f},{r*0.16:.1f} q{-r*0.5:.1f},{-r*0.3:.1f} {-r*0.75:.1f},{-r*0.8:.1f} '
            f'l{r*0.18:.1f},{-r*0.18:.1f} q{r*0.12:.1f},{-r*0.14:.1f} {0.02:.1f},{-r*0.3:.1f} '
            f'l{-r*0.34:.1f},{-r*0.5:.1f} q{-r*0.16:.1f},{-r*0.2:.1f} {-r*0.34:.1f},{-r*0.08:.1f} z"/>')


def _g_compass(cx, cy, s):
    r = s * 0.30
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" stroke="#fff" stroke-width="{s*0.03:.1f}"/>'
            f'<polygon points="{cx:.1f},{cy-r*0.6:.1f} {cx+r*0.22:.1f},{cy:.1f} {cx:.1f},{cy:.1f}" fill="#ff5a5f"/>'
            f'<polygon points="{cx:.1f},{cy+r*0.6:.1f} {cx-r*0.22:.1f},{cy:.1f} {cx:.1f},{cy:.1f}" fill="#fff"/>'
            f'<polygon points="{cx:.1f},{cy-r*0.6:.1f} {cx-r*0.22:.1f},{cy:.1f} {cx:.1f},{cy:.1f}" fill="#ff8a8f"/>'
            f'<polygon points="{cx:.1f},{cy+r*0.6:.1f} {cx+r*0.22:.1f},{cy:.1f} {cx:.1f},{cy:.1f}" fill="#e6e6e6"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{s*0.03:.1f}" fill="#fff"/>')


def _g_camera(cx, cy, s):
    bw, bh = s * 0.56, s * 0.4
    return (f'<rect x="{cx-bw/2:.1f}" y="{cy-bh/2:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="{bh*0.28:.1f}" fill="#fff"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{s*0.15:.1f}" fill="#2b2b2e"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{s*0.10:.1f}" fill="#5b6b82"/>'
            f'<circle cx="{cx+bw*0.28:.1f}" cy="{cy-bh*0.28:.1f}" r="{s*0.03:.1f}" fill="#ffd23f"/>')


def _g_photos(cx, cy, s):
    pets = ""
    cols = ["#f95d6a", "#ff9f0a", "#ffd23f", "#34c759", "#0a84ff", "#5e5ce6", "#bf5af2", "#ff375f"]
    import math
    for i, c in enumerate(cols):
        a = i * math.pi / 4
        px = cx + math.cos(a) * s * 0.17
        py = cy + math.sin(a) * s * 0.17
        pets += f'<ellipse cx="{px:.1f}" cy="{py:.1f}" rx="{s*0.11:.1f}" ry="{s*0.05:.1f}" fill="{c}" transform="rotate({i*45} {px:.1f} {py:.1f})" opacity="0.92"/>'
    return pets


def _g_clock(cx, cy, s):
    r = s * 0.32
    ticks = ""
    import math
    for i in range(12):
        a = i * math.pi / 6
        x1 = cx + math.cos(a) * r * 0.82
        y1 = cy + math.sin(a) * r * 0.82
        x2 = cx + math.cos(a) * r * 0.92
        y2 = cy + math.sin(a) * r * 0.92
        ticks += f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#111" stroke-width="{s*0.02:.1f}"/>'
    return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="#fff"/>{ticks}'
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx:.1f}" y2="{cy-r*0.5:.1f}" stroke="#111" stroke-width="{s*0.035:.1f}" stroke-linecap="round"/>'
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{cx+r*0.62:.1f}" y2="{cy:.1f}" stroke="#111" stroke-width="{s*0.03:.1f}" stroke-linecap="round"/>'
            f'<line x1="{cx:.1f}" y1="{cy+r*0.12:.1f}" x2="{cx-r*0.4:.1f}" y2="{cy-r*0.4:.1f}" stroke="#ff9f0a" stroke-width="{s*0.02:.1f}" stroke-linecap="round"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{s*0.03:.1f}" fill="#ff9f0a"/>')


def _g_weather(cx, cy, s):
    sun = (f'<circle cx="{cx-s*0.12:.1f}" cy="{cy-s*0.1:.1f}" r="{s*0.13:.1f}" fill="#ffd23f"/>')
    cloud = (f'<g fill="#fff"><circle cx="{cx-s*0.02:.1f}" cy="{cy+s*0.08:.1f}" r="{s*0.12:.1f}"/>'
             f'<circle cx="{cx+s*0.14:.1f}" cy="{cy+s*0.06:.1f}" r="{s*0.15:.1f}"/>'
             f'<rect x="{cx-s*0.14:.1f}" y="{cy+s*0.08:.1f}" width="{s*0.32:.1f}" height="{s*0.14:.1f}" rx="{s*0.07:.1f}"/></g>')
    return sun + cloud


def _g_calendar(cx, cy, s):
    d = datetime.date.today()
    week = "周" + "一二三四五六日"[d.weekday()]
    return (f'<rect x="{cx-s*0.3:.1f}" y="{cy-s*0.32:.1f}" width="{s*0.6:.1f}" height="{s*0.64:.1f}" rx="{s*0.08:.1f}" fill="#fff"/>'
            f'<rect x="{cx-s*0.3:.1f}" y="{cy-s*0.32:.1f}" width="{s*0.6:.1f}" height="{s*0.2:.1f}" rx="{s*0.08:.1f}" fill="#ff3b30"/>'
            f'<text x="{cx:.1f}" y="{cy-s*0.18:.1f}" font-size="{s*0.13:.1f}" fill="#fff" text-anchor="middle" font-weight="700">{week}</text>'
            f'<text x="{cx:.1f}" y="{cy+s*0.22:.1f}" font-size="{s*0.34:.1f}" fill="#1d1d1f" text-anchor="middle" font-weight="600">{d.day}</text>')


def _g_settings(cx, cy, s):
    import math
    r = s * 0.28
    teeth = ""
    for i in range(8):
        a = i * math.pi / 4
        x = cx + math.cos(a) * r
        y = cy + math.sin(a) * r
        teeth += f'<rect x="{x-s*0.05:.1f}" y="{y-s*0.05:.1f}" width="{s*0.1:.1f}" height="{s*0.1:.1f}" fill="#c7c9cf" transform="rotate({i*45} {x:.1f} {y:.1f})"/>'
    return (teeth + f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r*0.85:.1f}" fill="#c7c9cf"/>'
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r*0.42:.1f}" fill="#8e9096"/>')


def _g_notes(cx, cy, s):
    lines = "".join(
        f'<line x1="{cx-s*0.2:.1f}" y1="{cy-s*0.12+ i*s*0.12:.1f}" x2="{cx+s*0.2:.1f}" y2="{cy-s*0.12+i*s*0.12:.1f}" stroke="#c9a227" stroke-width="{s*0.025:.1f}"/>'
        for i in range(4))
    return (f'<rect x="{cx-s*0.3:.1f}" y="{cy-s*0.32:.1f}" width="{s*0.6:.1f}" height="{s*0.64:.1f}" rx="{s*0.08:.1f}" fill="#fff"/>'
            f'<rect x="{cx-s*0.3:.1f}" y="{cy-s*0.32:.1f}" width="{s*0.6:.1f}" height="{s*0.16:.1f}" rx="{s*0.08:.1f}" fill="#ffd23f"/>{lines}')


def _g_reminders(cx, cy, s):
    rows = ""
    cols = ["#ff3b30", "#ff9f0a", "#34c759"]
    for i, c in enumerate(cols):
        y = cy - s * 0.16 + i * s * 0.16
        rows += (f'<circle cx="{cx-s*0.18:.1f}" cy="{y:.1f}" r="{s*0.05:.1f}" fill="none" stroke="{c}" stroke-width="{s*0.025:.1f}"/>'
                 f'<line x1="{cx-s*0.06:.1f}" y1="{y:.1f}" x2="{cx+s*0.2:.1f}" y2="{y:.1f}" stroke="#c7c9cf" stroke-width="{s*0.03:.1f}" stroke-linecap="round"/>')
    return rows


def _g_stocks(cx, cy, s):
    return (f'<polyline points="{cx-s*0.28:.1f},{cy+s*0.12:.1f} {cx-s*0.12:.1f},{cy-s*0.05:.1f} '
            f'{cx:.1f},{cy+s*0.02:.1f} {cx+s*0.12:.1f},{cy-s*0.16:.1f} {cx+s*0.28:.1f},{cy-s*0.24:.1f}" '
            f'fill="none" stroke="#34c759" stroke-width="{s*0.04:.1f}" stroke-linejoin="round" stroke-linecap="round"/>'
            f'<line x1="{cx-s*0.3:.1f}" y1="{cy+s*0.24:.1f}" x2="{cx+s*0.3:.1f}" y2="{cy+s*0.24:.1f}" stroke="#3a3a3c" stroke-width="{s*0.02:.1f}"/>')


def _g_music(cx, cy, s):
    return (f'<path d="M{cx-s*0.16:.1f},{cy+s*0.18:.1f} l0,{-s*0.34:.1f} l{s*0.32:.1f},{-s*0.08:.1f} l0,{s*0.34:.1f}" '
            f'fill="none" stroke="#fff" stroke-width="{s*0.05:.1f}" stroke-linejoin="round"/>'
            f'<circle cx="{cx-s*0.16:.1f}" cy="{cy+s*0.18:.1f}" r="{s*0.08:.1f}" fill="#fff"/>'
            f'<circle cx="{cx+s*0.16:.1f}" cy="{cy+s*0.1:.1f}" r="{s*0.08:.1f}" fill="#fff"/>')


def _g_maps(cx, cy, s):
    return (f'<path d="M{cx-s*0.28:.1f},{cy-s*0.2:.1f} L{cx-s*0.05:.1f},{cy-s*0.28:.1f} '
            f'L{cx+s*0.28:.1f},{cy-s*0.16:.1f} L{cx+s*0.05:.1f},{cy+s*0.28:.1f} '
            f'L{cx-s*0.28:.1f},{cy+s*0.2:.1f} Z" fill="#c8e6c9"/>'
            f'<path d="M{cx-s*0.2:.1f},{cy+s*0.22:.1f} Q{cx:.1f},{cy-s*0.1:.1f} {cx+s*0.18:.1f},{cy-s*0.22:.1f}" '
            f'fill="none" stroke="#fff" stroke-width="{s*0.04:.1f}" stroke-dasharray="{s*0.06:.1f} {s*0.04:.1f}"/>'
            f'<path d="M{cx+s*0.12:.1f},{cy-s*0.26:.1f} a{s*0.09:.1f},{s*0.09:.1f} 0 1,1 {s*0.001:.1f},0 '
            f'l{-s*0.09:.1f},{s*0.16:.1f} z" fill="#ff3b30"/>')


def _g_appstore(cx, cy, s):
    return (f'<g stroke="#fff" stroke-width="{s*0.05:.1f}" stroke-linecap="round">'
            f'<line x1="{cx-s*0.2:.1f}" y1="{cy+s*0.16:.1f}" x2="{cx:.1f}" y2="{cy-s*0.2:.1f}"/>'
            f'<line x1="{cx+s*0.2:.1f}" y1="{cy+s*0.16:.1f}" x2="{cx:.1f}" y2="{cy-s*0.2:.1f}"/>'
            f'<line x1="{cx-s*0.12:.1f}" y1="{cy+s*0.02:.1f}" x2="{cx+s*0.12:.1f}" y2="{cy+s*0.02:.1f}"/></g>')


def _g_podcasts(cx, cy, s):
    return (f'<circle cx="{cx:.1f}" cy="{cy-s*0.12:.1f}" r="{s*0.08:.1f}" fill="#fff"/>'
            f'<path d="M{cx-s*0.16:.1f},{cy+s*0.2:.1f} Q{cx:.1f},{cy+s*0.02:.1f} {cx+s*0.16:.1f},{cy+s*0.2:.1f}" '
            f'fill="none" stroke="#fff" stroke-width="{s*0.06:.1f}" stroke-linecap="round"/>'
            f'<path d="M{cx-s*0.26:.1f},{cy+s*0.26:.1f} A{s*0.28:.1f},{s*0.28:.1f} 0 0,1 {cx+s*0.26:.1f},{cy+s*0.26:.1f}" '
            f'fill="none" stroke="#fff" stroke-width="{s*0.045:.1f}" stroke-linecap="round" opacity="0.8"/>')


def _g_wallet(cx, cy, s):
    cards = ""
    cols = ["#ff9f0a", "#ff375f", "#0a84ff"]
    for i, c in enumerate(cols):
        cards += f'<rect x="{cx-s*0.24:.1f}" y="{cy-s*0.22+i*s*0.13:.1f}" width="{s*0.48:.1f}" height="{s*0.22:.1f}" rx="{s*0.04:.1f}" fill="{c}"/>'
    return cards


def _g_files(cx, cy, s):
    return (f'<path d="M{cx-s*0.26:.1f},{cy-s*0.14:.1f} l{s*0.14:.1f},0 l{s*0.06:.1f},{s*0.06:.1f} '
            f'l{s*0.32:.1f},0 l0,{s*0.24:.1f} l{-s*0.52:.1f},0 z" fill="#54c7ec"/>'
            f'<rect x="{cx-s*0.26:.1f}" y="{cy-s*0.06:.1f}" width="{s*0.52:.1f}" height="{s*0.24:.1f}" rx="{s*0.03:.1f}" fill="#7dd3f0"/>')


# 主屏应用：(标签, 底色顶, 底色底, 字形函数)
_APPS = [
    ("信息", "#5ff072", "#0bd44e", _g_message),
    ("日历", "#ffffff", "#f2f2f7", _g_calendar),
    ("照片", "#ffffff", "#f2f2f7", _g_photos),
    ("相机", "#3a3a3c", "#1c1c1e", _g_camera),
    ("时钟", "#2c2c2e", "#000000", _g_clock),
    ("地图", "#e8f5e9", "#c8e6c9", _g_maps),
    ("天气", "#4aa3ff", "#0a6ccf", _g_weather),
    ("备忘录", "#ffffff", "#f2f2f7", _g_notes),
    ("提醒", "#ffffff", "#f2f2f7", _g_reminders),
    ("股市", "#2c2c2e", "#000000", _g_stocks),
    ("钱包", "#3a3a3c", "#1c1c1e", _g_wallet),
    ("设置", "#8e9096", "#5a5c62", _g_settings),
    ("App Store", "#2aa3ff", "#0a84ff", _g_appstore),
    ("音乐", "#ff6a8e", "#fa2f56", _g_music),
    ("播客", "#c86bf0", "#8a2be2", _g_podcasts),
    ("文件", "#7dd3f0", "#2aa3d8", _g_files),
]
_DOCK = [
    ("电话", "#5ff072", "#0bd44e", _g_phone),
    ("Safari", "#4aa3ff", "#0a6ccf", _g_compass),
    ("信息", "#5ff072", "#0bd44e", _g_message),
    ("音乐", "#ff6a8e", "#fa2f56", _g_music),
]


# ============================================================================
# 皮肤主题（一键换肤）—— 全部原创设计，差异体现在壁纸/图标底样式/圆角/口味
# ============================================================================
THEMES = {
    "ios": {
        "label": "iOS 风",
        "palettes": [
            ("#3a1c71", "#6d3bd6", "#d76ea3", "#ffc4d6"),
            ("#0b3d91", "#2a6cf0", "#7bc6ff", "#c9e8ff"),
            ("#1d2b64", "#3a5fcd", "#8a5cf6", "#f7a1c4"),
        ],
        "radius": 0.225, "glass": False,
    },
    "sunset": {
        "label": "暖阳渐变",
        "palettes": [
            ("#7a1f3d", "#e0533d", "#ff9f45", "#ffe0a3"),
            ("#5b1e51", "#c8407a", "#ff7a59", "#ffd6a0"),
            ("#3d1c4e", "#a23e86", "#f06a5b", "#ffcf9e"),
        ],
        "radius": 0.28, "glass": False,
    },
    "glass": {
        "label": "深色毛玻璃",
        "palettes": [
            ("#0b1020", "#141a2e", "#1d2740", "#2a3a63"),
            ("#0a1418", "#10222a", "#173642", "#1f5563"),
            ("#12101c", "#1b1830", "#272247", "#3a2f63"),
        ],
        "radius": 0.30, "glass": True,
    },
}
THEME_LIST = [{"key": k, "label": v["label"]} for k, v in THEMES.items()]


def _theme(key: str) -> dict:
    return THEMES.get(key or "ios", THEMES["ios"])


def _grad_defs() -> str:
    defs = []
    for i, (_, c1, c2, _fn) in enumerate(_APPS + _DOCK):
        defs.append(
            f'<linearGradient id="ig{i}" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>'
        )
    return "".join(defs)


def _icon(x, y, s, idx, app, label=True, theme="ios") -> str:
    _, _c1, _c2, glyph = app
    th = _theme(theme)
    rr = th["radius"]
    cx, cy = x + s / 2, y + s / 2
    if th.get("glass"):
        # 毛玻璃底：半透明白 + 描边，图标玻璃质感
        out = [_squircle(x, y, s, "#ffffff", 'opacity="0.16"', rr),
               _squircle(x, y, s, "none", 'stroke="#ffffff" stroke-opacity="0.22"', rr)]
    else:
        out = [_squircle(x, y, s, f"url(#ig{idx})", "", rr)]
    # 顶部高光
    out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{s:.1f}" height="{s*0.5:.1f}" rx="{s*rr:.1f}" fill="#ffffff" opacity="0.08"/>')
    out.append(glyph(cx, cy, s))
    if label:
        out.append(f'<text x="{cx:.1f}" y="{y+s+13:.1f}" font-size="11.5" fill="#fff" text-anchor="middle" '
                   f'style="paint-order:stroke" opacity="0.96">{_esc(app[0])}</text>')
    return "".join(out)


# ============================================================================
# 状态栏 / 灵动岛 / 壁纸 / Dock
# ============================================================================
def _statusbar(dark: bool = False) -> str:
    c = "#fff" if not dark else "#fff"
    # 信号 4 格
    bars = ""
    for i in range(4):
        bh = 4 + i * 3
        bars += f'<rect x="{356 + i*6:.1f}" y="{30 - bh:.1f}" width="4" height="{bh}" rx="1" fill="{c}"/>'
    # wifi 弧
    wifi = (f'<path d="M382,28 a10,10 0 0,1 16,0" fill="none" stroke="{c}" stroke-width="2.4"/>'
            f'<path d="M386,24 a6,6 0 0,1 8,0" fill="none" stroke="{c}" stroke-width="2.4"/>'
            f'<circle cx="390" cy="20.5" r="1.6" fill="{c}"/>')
    # 电池
    bat = (f'<rect x="404" y="15" width="22" height="11" rx="3" fill="none" stroke="{c}" stroke-opacity="0.5" stroke-width="1.4"/>'
           f'<rect x="406" y="17" width="16" height="7" rx="1.5" fill="{c}"/>'
           f'<rect x="427" y="18.5" width="1.8" height="4" rx="1" fill="{c}" opacity="0.6"/>')
    # 灵动岛
    island = '<rect x="163" y="12" width="114" height="30" rx="15" fill="#000"/>'
    time_t = f'<text x="34" y="30" font-size="17" fill="{c}" font-weight="700" letter-spacing="0.3">9:41</text>'
    # 微调右侧到画布内（wifi/信号/电池分布）
    return f'<g font-family="-apple-system,Helvetica,Arial,sans-serif">{time_t}{island}{bars}{wifi}{bat}</g>'


def _wallpaper(rid: int = 0, theme: str = "ios") -> str:
    """原创渐变壁纸 + 柔光团（按主题取色板）。"""
    palettes = _theme(theme)["palettes"]
    a, b, c, d = palettes[rid % len(palettes)]
    return (f'<defs><linearGradient id="wp" x1="0" y1="0" x2="0.4" y2="1">'
            f'<stop offset="0" stop-color="{a}"/><stop offset="0.55" stop-color="{b}"/>'
            f'<stop offset="1" stop-color="{c}"/></linearGradient>'
            f'<radialGradient id="blob1" cx="0.2" cy="0.15" r="0.5"><stop offset="0" stop-color="{d}" stop-opacity="0.55"/>'
            f'<stop offset="1" stop-color="{d}" stop-opacity="0"/></radialGradient>'
            f'<radialGradient id="blob2" cx="0.9" cy="0.8" r="0.6"><stop offset="0" stop-color="{c}" stop-opacity="0.5"/>'
            f'<stop offset="1" stop-color="{c}" stop-opacity="0"/></radialGradient></defs>'
            f'<rect width="{W}" height="{H}" fill="url(#wp)"/>'
            f'<rect width="{W}" height="{H}" fill="url(#blob1)"/>'
            f'<rect width="{W}" height="{H}" fill="url(#blob2)"/>')


def _home_indicator(dark=False) -> str:
    return '<rect x="150" y="800" width="140" height="5" rx="2.5" fill="#fff" opacity="0.85"/>'


def _weather_widget(fp) -> str:
    net = fp.get("network", {})
    dev = fp.get("device", {})
    city = "云手机·矩阵"
    return (f'<g>'
            f'<rect x="24" y="58" width="392" height="96" rx="22" fill="#ffffff" opacity="0.14"/>'
            f'<rect x="24" y="58" width="392" height="96" rx="22" fill="none" stroke="#ffffff" stroke-opacity="0.18"/>'
            f'<text x="44" y="88" font-size="15" fill="#fff" opacity="0.95">{_esc(city)}</text>'
            f'<text x="44" y="132" font-size="42" fill="#fff" font-weight="300">24°</text>'
            f'<text x="150" y="132" font-size="13" fill="#fff" opacity="0.85">多云</text>'
            + _g_weather(340, 96, 70) +
            f'<text x="396" y="140" font-size="12" fill="#fff" text-anchor="end" opacity="0.85">H:27° L:19°</text>'
            f'<text x="396" y="88" font-size="12" fill="#fff" text-anchor="end" opacity="0.7">{_esc(dev.get("model",""))}</text>'
            f'</g>')


def _svg_home(name: str, fp: dict, theme: str = "ios") -> str:
    net = fp.get("network", {})
    rid = sum(ord(ch) for ch in (fp.get("seed", "") or name)) % 3
    parts = [_wallpaper(rid, theme), _grad_defs(), _statusbar(), _weather_widget(fp)]
    # 4 列图标网格
    cols, size = 4, 62
    xs = [38, 139, 240, 341]
    y0, rowh = 182, 96
    for i, app in enumerate(_APPS):
        col, row = i % cols, i // cols
        parts.append(_icon(xs[col], y0 + row * rowh, size, i, app, theme=theme))
    # 页面圆点：**按实际页数渲染**。
    # 之前固定画 2 个点，但主屏只有 1 页（16 个图标一屏放得下，真机 launcher.db 里
    # 也全是 screen=0），第 2 个点纯属误导 —— 用户会去左右滑却滑不到东西。
    pages = max(1, -(-len(_APPS) // (cols * 4)))  # 每页 4 列 × 4 行
    dot_r, gap = 3, 16
    x_start = 220 - (pages - 1) * gap / 2
    for pi in range(pages):
        op = "" if pi == 0 else ' opacity="0.4"'
        parts.append(f'<circle cx="{x_start + pi * gap:.0f}" cy="672" r="{dot_r}" fill="#fff"{op}/>')
    # 毛玻璃 Dock
    parts.append('<rect x="26" y="694" width="388" height="92" rx="30" fill="#ffffff" opacity="0.16"/>'
                 '<rect x="26" y="694" width="388" height="92" rx="30" fill="none" stroke="#ffffff" stroke-opacity="0.14"/>')
    dxs = [56, 156, 256, 356]
    for j, app in enumerate(_DOCK):
        parts.append(_icon(dxs[j], 706, 66, len(_APPS) + j, app, label=False, theme=theme))
    parts.append(_home_indicator())
    # 设备标识（低调）
    parts.append(f'<text x="220" y="815" font-size="10.5" fill="#fff" text-anchor="middle" opacity="0.55">'
                 f'{_esc(name)} · {_esc(net.get("exit_ip",""))}</text>')
    return "".join(parts)


def _svg_lock(name: str, fp: dict, theme: str = "ios") -> str:
    net = fp.get("network", {})
    rid = sum(ord(ch) for ch in (fp.get("seed", "") or name)) % 3
    d = datetime.date.today()
    week = "星期" + "一二三四五六日"[d.weekday()]
    date_s = f"{week}  {d.month}月{d.day}日"
    parts = [_wallpaper(rid, theme), _grad_defs(), _statusbar()]
    # 锁 + 日期 + 大时钟
    parts.append('<path d="M212,84 h16 v-6 a8,8 0 0,0 -16,0 z M210,84 h20 v14 h-20 z" fill="#fff" opacity="0.9" transform="translate(0,0)"/>')
    parts.append(f'<text x="220" y="150" font-size="17" fill="#fff" text-anchor="middle" opacity="0.9">{_esc(date_s)}</text>')
    parts.append('<text x="220" y="250" font-size="96" fill="#fff" text-anchor="middle" font-weight="300" letter-spacing="1">9:41</text>')
    # 通知卡（毛玻璃）
    parts.append('<rect x="26" y="300" width="388" height="66" rx="18" fill="#ffffff" opacity="0.16"/>')
    parts.append(_icon(40, 314, 38, 0, _APPS[0], label=False, theme=theme))
    parts.append('<text x="92" y="330" font-size="14" fill="#fff" font-weight="600">信息</text>'
                 '<text x="92" y="350" font-size="13" fill="#fff" opacity="0.85">云手机矩阵 · 主流程演示已就绪</text>')
    parts.append('<text x="392" y="330" font-size="12" fill="#fff" text-anchor="end" opacity="0.7">现在</text>')
    # 底部两枚圆形按钮：手电 / 相机
    parts.append('<circle cx="70" cy="770" r="26" fill="#000" opacity="0.35"/>'
                 + _g_flash(70, 770, 30) +
                 '<circle cx="370" cy="770" r="26" fill="#000" opacity="0.35"/>'
                 + _g_camera(370, 770, 34))
    parts.append(_home_indicator())
    parts.append(f'<text x="220" y="815" font-size="10.5" fill="#fff" text-anchor="middle" opacity="0.55">'
                 f'{_esc(name)} · {_esc(net.get("exit_ip",""))}</text>')
    return "".join(parts)


def _g_flash(cx, cy, s):
    return (f'<path d="M{cx+s*0.05:.1f},{cy-s*0.28:.1f} l{-s*0.2:.1f},{s*0.32:.1f} l{s*0.12:.1f},0 '
            f'l{-s*0.05:.1f},{s*0.24:.1f} l{s*0.2:.1f},{-s*0.34:.1f} l{-s*0.12:.1f},0 z" fill="#fff"/>')


def _pill(x, y, w, h, label, on=False, icon="") -> str:
    fill = "#0a84ff" if on else "#ffffff"
    op = "1" if on else "0.18"
    tc = "#fff" if on else "#fff"
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{h/2 if h<w/2 else 18}" fill="{fill}" opacity="{op}"/>'
            + (f'<text x="{x+w/2}" y="{y+h/2+4}" font-size="12" fill="{tc}" text-anchor="middle" opacity="0.95">{_esc(label)}</text>' if label else ""))


def _svg_control(name: str, fp: dict, theme: str = "ios") -> str:
    """控制中心：毛玻璃深色遮罩 + 各模块。"""
    rid = sum(ord(ch) for ch in (fp.get("seed", "") or name)) % 3
    parts = [_wallpaper(rid, theme), _grad_defs()]
    # 深色毛玻璃遮罩
    parts.append(f'<rect width="{W}" height="{H}" fill="#000" opacity="0.32"/>')
    parts.append(_statusbar())
    # 左上：连接模块（2x2 圆钮 在一个圆角面板里）
    parts.append('<rect x="24" y="60" width="180" height="120" rx="26" fill="#ffffff" opacity="0.16"/>')
    conn = [("飞行", "#ff9f0a", False), ("蜂窝", "#34c759", True), ("Wi-Fi", "#0a84ff", True), ("蓝牙", "#0a84ff", True)]
    cxy = [(70, 100), (158, 100), (70, 148), (158, 148)]
    for (lbl, col, on), (cx, cy) in zip(conn, cxy):
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="22" fill="{col if on else "#5a5c62"}" opacity="{1 if on else 0.7}"/>')
        parts.append(f'<text x="{cx}" y="{cy+4}" font-size="10" fill="#fff" text-anchor="middle">{_esc(lbl)}</text>')
    # 右上：音乐面板
    parts.append('<rect x="216" y="60" width="200" height="120" rx="26" fill="#ffffff" opacity="0.16"/>')
    parts.append(_icon(232, 76, 40, len(_APPS) + 3, _DOCK[3], label=False, theme=theme))
    parts.append('<text x="286" y="96" font-size="13" fill="#fff" font-weight="600">正在播放</text>'
                 '<text x="286" y="116" font-size="12" fill="#fff" opacity="0.8">云手机 · 群控演示曲</text>')
    parts.append('<line x1="232" y1="150" x2="400" y2="150" stroke="#fff" stroke-opacity="0.3" stroke-width="3" stroke-linecap="round"/>'
                 '<line x1="232" y1="150" x2="320" y2="150" stroke="#fff" stroke-width="3" stroke-linecap="round"/>')
    # 亮度 / 音量 竖条
    parts.append('<rect x="24" y="192" width="86" height="200" rx="26" fill="#ffffff" opacity="0.16"/>'
                 '<rect x="34" y="272" width="66" height="110" rx="18" fill="#fff" opacity="0.9"/>'
                 '<text x="57" y="372" font-size="16" fill="#8e9096" text-anchor="middle">☀</text>')
    parts.append('<rect x="120" y="192" width="86" height="200" rx="26" fill="#ffffff" opacity="0.16"/>'
                 '<rect x="130" y="300" width="66" height="82" rx="18" fill="#fff" opacity="0.9"/>'
                 '<text x="153" y="372" font-size="15" fill="#8e9096" text-anchor="middle">♪</text>')
    # 右下四宫格快捷：手电/计时/计算/相机
    quick = [("手电", 264, 208), ("计时", 352, 208), ("计算", 264, 296), ("相机", 352, 296)]
    parts.append('<rect x="216" y="192" width="200" height="200" rx="26" fill="none"/>')
    for lbl, cx, cy in quick:
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="30" fill="#ffffff" opacity="0.16"/>'
                     f'<text x="{cx}" y="{cy+4}" font-size="11" fill="#fff" text-anchor="middle">{_esc(lbl)}</text>')
    # 底部一排小按钮
    row = [("屏幕镜像", 90), ("专注", 220), ("屏幕录制", 350)]
    for lbl, cx in row:
        parts.append(f'<circle cx="{cx}" cy="430" r="26" fill="#ffffff" opacity="0.16"/>'
                     f'<text x="{cx}" y="434" font-size="10" fill="#fff" text-anchor="middle">{_esc(lbl)}</text>')
    parts.append(_home_indicator())
    parts.append(f'<text x="220" y="815" font-size="10.5" fill="#fff" text-anchor="middle" opacity="0.55">'
                 f'控制中心 · {_esc(name)}</text>')
    return "".join(parts)


def _svg_browser(name: str, url: str, fp: dict, theme: str = "ios") -> str:
    """iOS Safari 风：顶部地址药丸 + 底部工具栏 + 页面 + 一机一码卡片（网页页面保持浅色）。"""
    b = fp.get("browser", {})
    net = fp.get("network", {})
    dev = fp.get("device", {})
    short = url.replace("https://", "").replace("http://", "").split("/")[0]
    rows = [
        ("出口 IP", net.get("exit_ip", "-")),
        ("机型", dev.get("model", "-")),
        ("时区/语言", f"{b.get('timezone','-')} / {b.get('language','-')}"),
        ("WebGL", b.get("webgl_renderer", "-")),
        ("分辨率", f"{b.get('width','-')}x{b.get('height','-')}@{b.get('dpi','-')}"),
        ("Canvas", b.get("canvas_noise_seed", "-")),
    ]
    info = "".join(
        f'<text x="40" y="{372+i*34}" font-size="13" fill="#8a8f98">{_esc(k)}</text>'
        f'<text x="150" y="{372+i*34}" font-size="13" fill="#1d1d1f">{_esc(v)}</text>'
        for i, (k, v) in enumerate(rows))
    return (f'<rect width="{W}" height="{H}" fill="#f2f2f7"/>'
            # 状态栏（浅底深字）
            f'<rect width="{W}" height="46" fill="#f2f2f7"/>'
            f'<text x="34" y="30" font-size="17" fill="#1d1d1f" font-weight="700">9:41</text>'
            f'<rect x="163" y="12" width="114" height="30" rx="15" fill="#000"/>'
            # 地址药丸
            f'<rect x="16" y="52" width="408" height="40" rx="14" fill="#e3e3e8"/>'
            f'<text x="200" y="77" font-size="14" fill="#3a3a3c" text-anchor="middle">🔒 {_esc(short)}</text>'
            # 页面卡片
            f'<rect x="16" y="104" width="408" height="640" rx="16" fill="#fff"/>'
            f'<text x="40" y="176" font-size="26" fill="#1d1d1f" font-weight="700">Example Domain</text>'
            f'<text x="40" y="212" font-size="14" fill="#6e6e73">This domain is for use in examples.</text>'
            f'<rect x="24" y="300" width="392" height="42" rx="10" fill="#f2f2f7"/>'
            f'<text x="40" y="327" font-size="14" fill="#0a84ff" font-weight="600">一机一码 · 指纹隔离</text>'
            f'{info}'
            # 底部 Safari 工具栏
            f'<rect x="0" y="756" width="{W}" height="64" fill="#f7f7fa"/>'
            f'<text x="44" y="792" font-size="22" fill="#0a84ff">‹</text>'
            f'<text x="104" y="792" font-size="22" fill="#c7c9cf">›</text>'
            f'<rect x="196" y="772" width="20" height="24" rx="3" fill="none" stroke="#0a84ff" stroke-width="2"/>'
            f'<line x1="206" y1="768" x2="206" y2="784" stroke="#0a84ff" stroke-width="2"/>'
            f'<rect x="292" y="770" width="24" height="24" rx="4" fill="none" stroke="#0a84ff" stroke-width="2"/>'
            f'<rect x="372" y="770" width="24" height="24" rx="4" fill="none" stroke="#0a84ff" stroke-width="2"/>'
            f'<rect x="150" y="806" width="140" height="5" rx="2.5" fill="#1d1d1f" opacity="0.3"/>'
            f'<text x="220" y="800" font-size="10" fill="#aeb0b6" text-anchor="middle">{_esc(name)}</text>')


def _g_search(cx, cy, s, color="#fff"):
    r = s * 0.32
    return (f'<circle cx="{cx-r*0.2:.1f}" cy="{cy-r*0.2:.1f}" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="{s*0.11:.1f}"/>'
            f'<line x1="{cx+r*0.32:.1f}" y1="{cy+r*0.32:.1f}" x2="{cx+r*0.72:.1f}" y2="{cy+r*0.72:.1f}" '
            f'stroke="{color}" stroke-width="{s*0.11:.1f}" stroke-linecap="round"/>')


def _rid(name, fp):
    return sum(ord(ch) for ch in (fp.get("seed", "") or name)) % 3


def _folder(x, y, size, idxs, label, theme="ios"):
    """App 资源库文件夹：毛玻璃圆角方块 + 2x2 迷你图标 + 标签。"""
    out = [f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="{size*0.22:.1f}" fill="#ffffff" opacity="0.16"/>']
    mini = size * 0.36
    pad = size * 0.1
    pos = [(x + pad, y + pad), (x + size - pad - mini, y + pad),
           (x + pad, y + size - pad - mini), (x + size - pad - mini, y + size - pad - mini)]
    for (mx, my), idx in zip(pos, idxs):
        out.append(_icon(mx, my, mini, idx, _APPS[idx], label=False, theme=theme))
    out.append(f'<text x="{x+size/2:.1f}" y="{y+size+17:.1f}" font-size="12.5" fill="#fff" text-anchor="middle" opacity="0.92">{_esc(label)}</text>')
    return "".join(out)


def _svg_applibrary(name: str, fp: dict, theme: str = "ios") -> str:
    """App 资源库：分类文件夹网格。"""
    parts = [_wallpaper(_rid(name, fp), theme), _grad_defs(),
             f'<rect width="{W}" height="{H}" fill="#000" opacity="0.18"/>', _statusbar()]
    parts.append('<text x="34" y="88" font-size="27" fill="#fff" font-weight="700">App 资源库</text>')
    parts.append('<rect x="24" y="106" width="392" height="40" rx="20" fill="#ffffff" opacity="0.2"/>')
    parts.append(_g_search(50, 126, 20) + '<text x="76" y="132" font-size="14" fill="#fff" opacity="0.8">搜索</text>')
    cats = [("效率工具", [11, 7, 8, 15]), ("社交与信息", [0, 2, 14, 3]),
            ("媒体娱乐", [13, 4, 9, 10]), ("最近添加", [6, 5, 1, 12])]
    fx, fy, fs = [36, 228], [176, 408], 176
    for i, (lbl, idxs) in enumerate(cats):
        parts.append(_folder(fx[i % 2], fy[i // 2], fs, idxs, lbl, theme=theme))
    parts.append(_home_indicator())
    parts.append(f'<text x="220" y="815" font-size="10.5" fill="#fff" text-anchor="middle" opacity="0.55">{_esc(name)}</text>')
    return "".join(parts)


def _svg_spotlight(name: str, fp: dict, theme: str = "ios") -> str:
    """Spotlight 搜索：搜索框 + Siri 建议 + 建议列表。"""
    parts = [_wallpaper(_rid(name, fp), theme), _grad_defs(),
             f'<rect width="{W}" height="{H}" fill="#000" opacity="0.38"/>', _statusbar()]
    parts.append('<rect x="24" y="70" width="392" height="46" rx="14" fill="#ffffff" opacity="0.22"/>')
    parts.append(_g_search(50, 93, 20) + '<text x="76" y="99" font-size="16" fill="#fff" opacity="0.85">搜索</text>')
    parts.append('<text x="34" y="150" font-size="13" fill="#fff" opacity="0.7">Siri 建议</text>')
    for i, idx in enumerate([0, 15, 4, 11, 13, 7]):
        x = 30 + i * 66
        parts.append(_icon(x, 162, 48, idx, _APPS[idx], label=False, theme=theme))
        parts.append(f'<text x="{x+24}" y="226" font-size="10" fill="#fff" text-anchor="middle" opacity="0.85">{_esc(_APPS[idx][0])}</text>')
    parts.append('<text x="34" y="270" font-size="13" fill="#fff" opacity="0.7">建议</text>')
    sug = [(0, "信息", "打开 云手机矩阵 会话"), (15, "文件", "浏览 /sdcard/Download"),
           (13, "App Store", "搜索 群控相关应用"), (4, "时钟", "创建定时任务")]
    for i, (idx, t, sub) in enumerate(sug):
        y = 286 + i * 60
        parts.append(f'<rect x="24" y="{y}" width="392" height="52" rx="12" fill="#ffffff" opacity="0.12"/>')
        parts.append(_icon(34, y + 8, 36, idx, _APPS[idx], label=False, theme=theme))
        parts.append(f'<text x="82" y="{y+23}" font-size="14" fill="#fff" font-weight="600">{_esc(t)}</text>')
        parts.append(f'<text x="82" y="{y+41}" font-size="12" fill="#fff" opacity="0.75">{_esc(sub)}</text>')
    parts.append(_home_indicator())
    return "".join(parts)


def _svg_today(name: str, fp: dict, theme: str = "ios") -> str:
    """今天视图（负一屏）：搜索 + 小组件栈（天气/设备状态/日历）。"""
    net = fp.get("network", {})
    dev = fp.get("device", {})
    d = datetime.date.today()
    parts = [_wallpaper(_rid(name, fp), theme), _grad_defs(), _statusbar()]
    parts.append('<text x="34" y="90" font-size="30" fill="#fff" font-weight="700">今天</text>')
    parts.append('<rect x="24" y="108" width="392" height="40" rx="20" fill="#ffffff" opacity="0.2"/>')
    parts.append(_g_search(50, 128, 18) + '<text x="76" y="134" font-size="14" fill="#fff" opacity="0.8">搜索</text>')
    # 天气 widget
    parts.append('<rect x="24" y="164" width="392" height="96" rx="22" fill="#ffffff" opacity="0.16"/>')
    parts.append('<text x="44" y="192" font-size="14" fill="#fff" opacity="0.9">云手机·矩阵</text>')
    parts.append('<text x="44" y="234" font-size="40" fill="#fff" font-weight="300">24°</text>')
    parts.append('<text x="140" y="234" font-size="13" fill="#fff" opacity="0.85">多云</text>')
    parts.append(_g_weather(346, 200, 68))
    # 设备状态 widget（与一机一码呼应）
    parts.append('<rect x="24" y="272" width="392" height="120" rx="22" fill="#ffffff" opacity="0.16"/>')
    parts.append('<text x="44" y="300" font-size="15" fill="#fff" font-weight="600">设备状态</text>')
    st = [("机型", dev.get("model", "-")), ("出口 IP", net.get("exit_ip", "-")),
          ("Android", dev.get("android_version", "-"))]
    for i, (k, v) in enumerate(st):
        parts.append(f'<text x="44" y="{330+i*22}" font-size="13" fill="#fff" opacity="0.7">{_esc(k)}</text>'
                     f'<text x="150" y="{330+i*22}" font-size="13" fill="#fff">{_esc(v)}</text>')
    # 日历 widget
    parts.append('<rect x="24" y="404" width="392" height="96" rx="22" fill="#ffffff" opacity="0.16"/>')
    parts.append(f'<text x="44" y="432" font-size="13" fill="#ff9f9f" font-weight="700">{"周一二三四五六日"[0]}{"一二三四五六日"[d.weekday()]}</text>')
    parts.append(f'<text x="44" y="474" font-size="34" fill="#fff" font-weight="600">{d.month}月{d.day}日</text>')
    parts.append('<text x="392" y="440" font-size="13" fill="#fff" text-anchor="end" opacity="0.85">主流程演示彩排</text>')
    parts.append('<text x="392" y="470" font-size="12" fill="#fff" text-anchor="end" opacity="0.7">09:41 全天</text>')
    parts.append(_home_indicator())
    parts.append(f'<text x="220" y="815" font-size="10.5" fill="#fff" text-anchor="middle" opacity="0.55">{_esc(name)} · {_esc(net.get("exit_ip",""))}</text>')
    return "".join(parts)


_ICON_BY_KEY = {a[0]: a for a in _APPS + _DOCK}


def render_icon_svg(key: str, size: int = 180) -> str:
    """把单个应用图标渲染成独立 SVG（供真机图标包栅格化复用，与主屏图标同一设计）。"""
    app = _ICON_BY_KEY.get(key)
    if not app:
        return ""
    _, c1, c2, glyph = app
    cx = cy = size / 2
    defs = (f'<linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>')
    body = (_squircle(0, 0, size, "url(#g)")
            + f'<rect x="0" y="0" width="{size}" height="{size*0.5:.1f}" rx="{size*0.225:.1f}" fill="#fff" opacity="0.08"/>'
            + glyph(cx, cy, size))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
            f'viewBox="0 0 {size} {size}"><defs>{defs}</defs>{body}</svg>')


ICON_KEYS = list(_ICON_BY_KEY.keys())


def _a_icon(x: int, y: int, s: int, bg: str, glyph: str) -> str:
    """安卓风格图标：圆角方形底 + 简笔白色字形（原创矢量，不使用外部美术）。"""
    cx, cy = x + s / 2, y + s / 2
    g = ""
    if glyph == "phone":
        g = (f'<path d="M{cx-10},{cy-12} q4,-6 8,-2 l4,6 q2,3 -2,6 q-8,10 -18,4 q-10,-6 -16,-16 '
             f'q-4,-8 4,-12 z" fill="#fff"/>')
    elif glyph == "chat":
        g = (f'<rect x="{cx-14}" y="{cy-13}" width="28" height="19" rx="7" fill="#fff"/>'
             f'<path d="M{cx-7},{cy+6} l-5,6 l9,-4 z" fill="#fff"/>')
    elif glyph == "browser":
        g = (f'<circle cx="{cx}" cy="{cy}" r="15" fill="none" stroke="#fff" stroke-width="3"/>'
             f'<circle cx="{cx}" cy="{cy}" r="5" fill="#fff"/>')
    elif glyph == "camera":
        g = (f'<rect x="{cx-15}" y="{cy-9}" width="30" height="21" rx="6" fill="#fff"/>'
             f'<circle cx="{cx}" cy="{cy+1}" r="7" fill="#1f2937"/>'
             f'<circle cx="{cx}" cy="{cy+1}" r="3.4" fill="#fff"/>')
    elif glyph == "gallery":
        g = (f'<rect x="{cx-15}" y="{cy-13}" width="30" height="26" rx="5" fill="#fff"/>'
             f'<path d="M{cx-15},{cy+8} l9,-11 l7,8 l5,-5 l9,8 z" fill="#2563eb"/>'
             f'<circle cx="{cx+6}" cy="{cy-6}" r="3.4" fill="#fbbf24"/>')
    elif glyph == "gear":
        g = (f'<circle cx="{cx}" cy="{cy}" r="10" fill="none" stroke="#fff" stroke-width="4"/>'
             f'<circle cx="{cx}" cy="{cy}" r="3.6" fill="#fff"/>')
    elif glyph == "clock":
        g = (f'<circle cx="{cx}" cy="{cy}" r="15" fill="none" stroke="#fff" stroke-width="3"/>'
             f'<path d="M{cx},{cy-9} l0,9 l7,5" stroke="#fff" stroke-width="3" fill="none"/>')
    elif glyph == "calendar":
        g = (f'<rect x="{cx-15}" y="{cy-13}" width="30" height="27" rx="5" fill="#fff"/>'
             f'<rect x="{cx-15}" y="{cy-13}" width="30" height="8" rx="4" fill="#1d4ed8"/>'
             f'<text x="{cx}" y="{cy+7}" font-size="12" font-weight="700" fill="#1d4ed8" text-anchor="middle">4</text>')
    elif glyph == "map":
        g = (f'<path d="M{cx},{cy+15} q-14,-16 0,-29 q14,13 0,29 z" fill="#fff"/>'
             f'<circle cx="{cx}" cy="{cy-2}" r="4.5" fill="#059669"/>')
    elif glyph == "store":
        g = (f'<path d="M{cx-13},{cy-10} l26,0 l-3,24 l-20,0 z" fill="#fff"/>'
             f'<path d="M{cx-6},{cy-2} l12,0 M{cx-6},{cy+6} l12,0" stroke="#1f2937" stroke-width="2.4"/>')
    elif glyph == "mail":
        g = (f'<rect x="{cx-15}" y="{cy-10}" width="30" height="21" rx="4" fill="#fff"/>'
             f'<path d="M{cx-15},{cy-8} l15,12 l15,-12" stroke="#ea4335" stroke-width="3" fill="none"/>')
    elif glyph == "cloud":
        g = (f'<circle cx="{cx-7}" cy="{cy+1}" r="8" fill="#fff"/>'
             f'<circle cx="{cx+5}" cy="{cy+3}" r="6" fill="#fff"/>'
             f'<rect x="{cx-8}" y="{cy-2}" width="16" height="10" rx="5" fill="#fff"/>')
    elif glyph == "folder":
        g = (f'<path d="M{cx-15},{cy-11} l12,0 l4,4 l14,0 l0,20 l-30,0 z" fill="#fff"/>')
    elif glyph == "music":
        g = (f'<path d="M{cx-2},{cy+10} l0,-18 l10,-3 l0,14" stroke="#fff" stroke-width="3" fill="none"/>'
             f'<circle cx="{cx-7}" cy="{cy+11}" r="5" fill="#fff"/>'
             f'<circle cx="{cx+11}" cy="{cy+6}" r="4" fill="#fff"/>')
    elif glyph == "calc":
        g = (f'<rect x="{cx-13}" y="{cy-14}" width="26" height="29" rx="5" fill="#fff"/>'
             f'<rect x="{cx-9}" y="{cy-10}" width="18" height="7" rx="2" fill="#334155"/>'
             + "".join(
                 f'<circle cx="{cx-7+j*7}" cy="{cy+2+i*6}" r="2.2" fill="#334155"/>'
                 for i in range(2) for j in range(3)
             ) + ")")
    elif glyph == "notes":
        g = (f'<rect x="{cx-13}" y="{cy-14}" width="26" height="29" rx="4" fill="#fff"/>'
             f'<path d="M{cx-8},{cy-6} l16,0 M{cx-8},{cy+1} l16,0 M{cx-8},{cy+8} l10,0" '
             f'stroke="#374151" stroke-width="2.2"/>')
    elif glyph == "weather":
        g = (f'<circle cx="{cx-6}" cy="{cy-5}" r="8" fill="#fff"/>'
             f'<circle cx="{cx+6}" cy="{cy+4}" r="6" fill="#fff"/>'
             f'<rect x="{cx-7}" y="{cy-1}" width="14" height="9" rx="4.5" fill="#fff"/>')
    elif glyph == "mic":
        g = (f'<rect x="{cx-5}" y="{cy-15}" width="10" height="18" rx="5" fill="#fff"/>'
             f'<path d="M{cx-10},{cy-1} q10,14 20,0" stroke="#fff" stroke-width="3" fill="none"/>'
             f'<path d="M{cx},{cy+9} l0,6" stroke="#fff" stroke-width="3"/>')
    elif glyph == "video":
        g = (f'<rect x="{cx-15}" y="{cy-11}" width="24" height="22" rx="5" fill="#fff"/>'
             f'<path d="M{cx+9},{cy-3} l8,-6 l0,18 l-8,-6 z" fill="#fff"/>')
    elif glyph == "game":
        g = (f'<rect x="{cx-15}" y="{cy-8}" width="30" height="17" rx="8" fill="#fff"/>'
             f'<path d="M{cx-9},{cy} l7,0 M{cx-5.5},{cy-3.5} l0,7" stroke="#334155" stroke-width="2.4"/>'
             f'<circle cx="{cx+7}" cy="{cy-2}" r="2.2" fill="#334155"/>'
             f'<circle cx="{cx+11}" cy="{cy+2}" r="2.2" fill="#334155"/>')
    return (
        f'<g><rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{s*0.24:.1f}" fill="{bg}"/>'
        f'<g transform="scale(1)">{g}</g></g>'
    )


_A_PHONE = [
    ("电话", "#0f9d58", "phone"),
    ("信息", "#1a73e8", "chat"),
    ("浏览器", "#ffffff", "browser"),
    ("相机", "#374151", "camera"),
    ("图库", "#f8fafc", "gallery"),
    ("设置", "#64748b", "gear"),
    ("时钟", "#0f172a", "clock"),
    ("日历", "#2563eb", "calendar"),
    ("地图", "#16a34a", "map"),
    ("应用商店", "#ffffff", "store"),
    ("邮件", "#f1f5f9", "mail"),
    ("云盘", "#0ea5e9", "cloud"),
    ("文件", "#f59e0b", "folder"),
    ("音乐", "#7c3aed", "music"),
    ("计算器", "#111827", "calc"),
    ("备忘录", "#f8fafc", "notes"),
    ("天气", "#38bdf8", "weather"),
    ("录音", "#ef4444", "mic"),
    ("视频", "#dc2626", "video"),
    ("游戏", "#4f46e5", "game"),
]
_A_DOCK = ["phone", "chat", "browser", "camera"]


def _a_statusbar() -> str:
    now = datetime.datetime.now().strftime("%H:%M")
    bars = "".join(
        f'<rect x="{318+i*4}" y="{18+(3-i)*2}" width="3" height="{6+i*2}" rx="1" fill="#eef4ff"/>'
        for i in range(4)
    )
    return (
        f'<g>'
        f'<text x="18" y="22" font-size="12.5" fill="#eef4ff" font-weight="600">{now}</text>'
        f'{bars}'
        f'<path d="M350,25 l14,-9 l0,9 z" fill="#eef4ff" opacity="0.9"/>'
        f'<rect x="370" y="17" width="21" height="10" rx="3" fill="none" stroke="#eef4ff" stroke-width="1.6"/>'
        f'<rect x="392" y="20" width="2" height="4" rx="1" fill="#eef4ff"/>'
        f'<rect x="372.5" y="19.5" width="14" height="5" rx="1.5" fill="#22c55e"/>'
        f'</g>'
    )


def _svg_android_home(name: str, fp: dict) -> str:
    """安卓桌面（Pixel 风格）：状态栏 + 壁纸 + 日期/天气组件 + 图标网格 + dock + 手势条。

    与 iOS 皮肤刻意区分：直角/圆角矩形、无灵动岛、底部手势条。
    画布内保留「演示模式」角标，避免被误认为真机画面。
    """
    now = datetime.datetime.now()
    week = "一二三四五六日"[now.weekday()]
    date_text = f"{now.month} 月 {now.day} 日 · 周{week}"
    parts = [
        '<defs><linearGradient id="awall" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0%" stop-color="#123a6b"/>'
        '<stop offset="45%" stop-color="#0b2545"/>'
        '<stop offset="100%" stop-color="#061224"/></linearGradient>'
        '<radialGradient id="agl" cx="0.85" cy="0.12" r="0.5">'
        '<stop offset="0%" stop-color="#22d3ee" stop-opacity="0.45"/>'
        '<stop offset="100%" stop-color="#22d3ee" stop-opacity="0"/></radialGradient></defs>',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#awall)"/>',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="url(#agl)"/>',
        '<circle cx="60" cy="690" r="150" fill="#3d7bff" opacity="0.10"/>',
        '<circle cx="400" cy="520" r="110" fill="#22d3ee" opacity="0.08"/>',
        _a_statusbar(),
        # 日期与天气组件
        f'<text x="24" y="70" font-size="26" fill="#f2f7ff" font-weight="600">{date_text}</text>',
        '<text x="24" y="96" font-size="13" fill="#9fb6d9">多云 · 24° · 空气质量 优</text>',
        # 演示角标
        '<g><rect x="330" y="52" width="90" height="22" rx="11" fill="#f5a524" opacity="0.18"/>'
        '<rect x="330" y="52" width="90" height="22" rx="11" fill="none" stroke="#f5a524" stroke-opacity="0.55"/>'
        '<text x="375" y="67" font-size="11" fill="#ffcf7a" text-anchor="middle">演示模式 · SIM</text></g>',
    ]

    # 4 列 × 5 行图标网格
    cols, size = 4, 56
    xs = [30, 130, 230, 330]
    y0, rowh = 130, 92
    for i, (label, bg, glyph) in enumerate(_A_PHONE):
        col, row = i % cols, i // cols
        x, y = xs[col], y0 + row * rowh
        parts.append(_a_icon(x, y, size, bg, glyph))
        parts.append(
            f'<text x="{x + size/2}" y="{y + size + 17}" font-size="11" fill="#dbe7f7" '
            f'text-anchor="middle">{_esc(label)}</text>'
        )

    # Dock
    dock_y = 704
    parts.append(
        f'<rect x="20" y="{dock_y}" width="400" height="76" rx="26" fill="#0b1626" opacity="0.66"/>'
        f'<rect x="20" y="{dock_y}" width="400" height="76" rx="26" fill="none" stroke="#9fb6d9" stroke-opacity="0.18"/>'
    )
    dock_x = [48, 148, 248, 348]
    for x, glyph in zip(dock_x, _A_DOCK):
        parts.append(_a_icon(x, dock_y + 10, 56, "#1f2b45" if glyph != "browser" else "#f8fafc", glyph))
    # 手势条
    parts.append('<rect x="150" y="800" width="140" height="5" rx="2.5" fill="#eef4ff" opacity="0.8"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'font-family="Roboto,Noto Sans CJK SC,-apple-system,Helvetica,Arial,sans-serif">'
        + "".join(parts) + "</svg>"
    )


def render_frame(name: str, current_url: str | None, fingerprint: dict, screen: str = "auto", theme: str = "ios") -> str:
    """返回可直接放进 <img src> 的 data URL。

    screen: auto（有 url→Safari，否则主屏）| home | lock | control | browser | applibrary | spotlight | today
    theme: ios | sunset | glass（一键换肤主题，见 THEMES）
    """
    fp = fingerprint or {}
    if screen == "android":
        svg = _svg_android_home(name, fp)
        b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    if screen == "lock":
        inner = _svg_lock(name, fp, theme)
    elif screen == "control":
        inner = _svg_control(name, fp, theme)
    elif screen == "home":
        inner = _svg_home(name, fp, theme)
    elif screen == "applibrary":
        inner = _svg_applibrary(name, fp, theme)
    elif screen == "spotlight":
        inner = _svg_spotlight(name, fp, theme)
    elif screen == "today":
        inner = _svg_today(name, fp, theme)
    elif screen == "browser":
        inner = _svg_browser(name, current_url or "https://example.com", fp, theme)
    else:
        inner = _svg_browser(name, current_url, fp, theme) if current_url else _svg_home(name, fp, theme)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="-apple-system,BlinkMacSystemFont,Helvetica,Arial,sans-serif">{inner}</svg>'
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"
