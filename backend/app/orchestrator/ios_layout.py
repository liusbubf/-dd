"""设计稿桌面布局表：把 preview.py 的 iOS 风主屏（_APPS 16 + _DOCK 4）落到真机。

对应换肤引擎 D 步骤（redroid._populate_grid 的设计稿路径）：
- 每个条目 = 设计稿图标（app/skins/icons/{theme}/{NN}.png，BLOB 写进 launcher.db）
  + 中文标题 + 点击行为（app：拉起真机组件；web：打开占位移动站）。
- index/标题与 app/skins/icons/manifest.json 严格一致：00-15 主屏（4 列铺 4 行，
  cellY 从 1 起、顶行留白更贴设计稿），16-19 Dock（container=-101，screen=0..3）。
- app 条目的候选组件已在真机验证；不在已装清单里则降级为该条目 url（web），
  两者皆无则跳过（保留设计稿位置，不重排）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# web 条目占位 URL（集中定义，随时可换成自家 H5；选大众移动站，真机 WebView 可打开）
_WEB_URLS = {
    "messages": "https://m.weibo.cn/",           # 信息：无短信应用，用微博移动站占位
    "maps": "https://m.amap.com/",               # 地图：高德移动站
    "weather": "https://m.weather.com.cn/",      # 天气：中国天气网移动站
    "notes": "https://note.youdao.com/",         # 备忘录：有道云笔记
    "reminders": "https://dida365.com/",         # 提醒：滴答清单
    "stocks": "https://finance.sina.cn/",        # 股市：新浪财经移动站
    "wallet": "https://m.alipay.com/",           # 钱包：支付宝移动站
    "appstore": "https://f-droid.org/",          # App Store：F-Droid 开源市场
    "music": "https://music.163.com/",           # 音乐：网易云音乐
    "podcasts": "https://m.ximalaya.com/",       # 播客：喜马拉雅移动站
}

_MAIN_COLS = 4       # 主屏 4 列（与设计稿/pref_numCols 一致）
_MAIN_START_ROW = 1  # 主屏从 cellY=1 起铺（第 0 行留白，更贴设计稿顶部空间）


@dataclass(frozen=True)
class Entry:
    """设计稿一个图标位：index=图标资产编号（{NN}.png），title 与 manifest 一致。"""

    index: int
    title: str
    kind: str                    # "app"（拉起真机组件）| "web"（打开占位站）
    component: str | None = None  # app：候选组件（pkg/类名，可用 . 缩写）
    url: str | None = None        # web 的 URL；也作 app 组件缺失时的降级 URL


# 设计稿 20 条目（00-15 主屏、16-19 Dock），顺序 = preview._APPS + _DOCK
LAYOUT: list[Entry] = [
    Entry(0, "信息", "web", url=_WEB_URLS["messages"]),
    Entry(1, "日历", "app", component="com.android.calendar/.AllInOneActivity"),
    Entry(2, "照片", "app", component="com.android.gallery3d/.app.GalleryActivity"),
    # 真机无相机应用，与照片共用相册组件
    Entry(3, "相机", "app", component="com.android.gallery3d/.app.GalleryActivity"),
    Entry(4, "时钟", "app", component="com.android.deskclock/.DeskClock"),
    Entry(5, "地图", "web", url=_WEB_URLS["maps"]),
    Entry(6, "天气", "web", url=_WEB_URLS["weather"]),
    Entry(7, "备忘录", "web", url=_WEB_URLS["notes"]),
    Entry(8, "提醒", "web", url=_WEB_URLS["reminders"]),
    Entry(9, "股市", "web", url=_WEB_URLS["stocks"]),
    Entry(10, "钱包", "web", url=_WEB_URLS["wallet"]),
    Entry(11, "设置", "app", component="com.android.settings/.Settings"),
    Entry(12, "App Store", "web", url=_WEB_URLS["appstore"]),
    Entry(13, "音乐", "web", url=_WEB_URLS["music"]),
    Entry(14, "播客", "web", url=_WEB_URLS["podcasts"]),
    Entry(15, "文件", "app", component="com.android.documentsui/.LauncherActivity"),
    # ---- Dock（container=-101，screen=槽位 0..3，无标签）----
    Entry(16, "电话", "app", component="com.android.contacts/.activities.PeopleActivity"),
    Entry(17, "Safari", "app", component="org.chromium.webview_shell/.WebViewBrowserActivity"),
    Entry(18, "信息", "web", url=_WEB_URLS["messages"]),
    Entry(19, "音乐", "web", url=_WEB_URLS["music"]),
]


def _full_component(comp: str) -> str:
    """组件名归一成全名：com.foo/.Bar -> com.foo/com.foo.Bar（便于与已装清单比对）。"""
    pkg, cls = comp.split("/", 1)
    return f"{pkg}/{pkg}{cls}" if cls.startswith(".") else comp


def _app_intent(comp: str) -> str:
    """app 条目 intent：与旧真实应用网格一致的 MAIN/LAUNCHER component 形式。"""
    pkg = comp.split("/")[0]
    return (
        "#Intent;action=android.intent.action.MAIN;"
        "category=android.intent.category.LAUNCHER;launchFlags=0x10200000;"
        f"package={pkg};component={comp};end"
    )


def _web_intent(url: str) -> str:
    """web 条目 intent：URL + VIEW（真机探针验证过点击可打开浏览器）。"""
    return f"{url}#Intent;action=android.intent.action.VIEW;end"


def build_favorites(installed_components: set[str], icons_dir: str, theme: str) -> list[dict]:
    """按设计稿布局生成 favorites 行数据（全部 itemType=1 快捷方式 + 图标 BLOB）。

    installed_components: 真机已装 LAUNCHER 组件集合（pkg/类名，缩写全名均可）；
    icons_dir: app/skins/icons 根目录；theme: ios | sunset | glass。
    返回 [{title,intent,container,screen,cellX,cellY,icon}]；
    图标文件缺失抛 FileNotFoundError（调用方以此回退旧网格逻辑）。
    """
    installed = {_full_component(c) for c in installed_components}
    rows: list[dict] = []
    for e in LAYOUT:
        intent = None
        if e.kind == "app" and e.component:
            comp = _full_component(e.component)
            if comp in installed:
                intent = _app_intent(comp)
        if intent is None and e.url:
            intent = _web_intent(e.url)  # web 条目 / app 组件缺失时的降级
        if intent is None:
            continue  # 组件缺失且无降级 URL：跳过（该格留空，不重排其余位置）
        with open(os.path.join(icons_dir, theme, f"{e.index:02d}.png"), "rb") as f:
            icon = f.read()
        if e.index < 16:  # 主屏：4 列铺 4 行，cellY 从 1 起
            pos = {
                "container": -100,
                "screen": 0,
                "cellX": e.index % _MAIN_COLS,
                "cellY": _MAIN_START_ROW + e.index // _MAIN_COLS,
            }
        else:  # Dock：screen 即槽位
            pos = {"container": -101, "screen": e.index - 16, "cellX": 0, "cellY": 0}
        rows.append({"title": e.title, "intent": intent, "icon": icon, **pos})
    return rows
