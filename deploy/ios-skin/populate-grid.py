#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把已安装应用按「iOS 网格 + Dock」重排进 Lawnchair V1 的 launcher.db。
在能访问该 db 文件、且 python3 自带 sqlite3 的机器上运行（本项目里是 redroid VM）。

用法:
  populate-grid.py <launcher.db 路径> < apps.tsv
其中 apps.tsv 每行:  Title<TAB>package/.Activity   （即 adb 查询到的启动组件）
例如:
  Calendar\tcom.android.calendar/.AllInOneActivity

布局约定（Lawnchair V1 = Launcher3 表结构）:
  favorites.container: -100=主屏工作区, -101=Dock(hotseat)
  主屏 cellY=0 一行被搜索/日期条(QSB)占用，App 从 cellY=1 起排；网格 4 列。
  Dock 用 screen 当槽位(0..3)。
"""
import sqlite3, sys, time

COLS = 4          # 4 列，贴近 iOS
START_ROW = 1     # 主屏第 0 行留给 QSB/日期条
DOCK_SLOTS = 4    # Dock 放 4 个

def intent(comp):
    pkg = comp.split("/")[0]
    return ("#Intent;action=android.intent.action.MAIN;"
            "category=android.intent.category.LAUNCHER;launchFlags=0x10200000;"
            f"package={pkg};component={comp};end")

def main():
    db = sys.argv[1]
    apps = []
    for line in sys.stdin:
        line = line.strip()
        if not line or "\t" not in line:
            continue
        title, comp = line.split("\t", 1)
        apps.append((title.strip(), comp.strip()))
    if not apps:
        print("no apps on stdin", file=sys.stderr); sys.exit(1)

    c = sqlite3.connect(db); cur = c.cursor()
    cur.execute("DELETE FROM favorites")
    now = int(time.time() * 1000); _id = 1

    def ins(title, comp, container, screen, cx, cy):
        nonlocal _id
        cur.execute(
            "INSERT INTO favorites (_id,title,intent,container,screen,cellX,cellY,"
            "spanX,spanY,itemType,appWidgetId,modified,restored,profileId,rank,options) "
            "VALUES (?,?,?,?,?,?,?,1,1,0,-1,?,0,0,0,0)",
            (_id, title, intent(comp), container, screen, cx, cy, now))
        _id += 1

    # 主屏：从 START_ROW 起，4 列铺满
    for i, (title, comp) in enumerate(apps):
        cx = i % COLS
        cy = START_ROW + i // COLS
        ins(title, comp, -100, 0, cx, cy)

    # Dock：取前 DOCK_SLOTS 个应用
    for slot, (title, comp) in enumerate(apps[:DOCK_SLOTS]):
        ins(title, comp, -101, slot, 0, 0)

    # 确保 workspaceScreens 有第 0 屏
    if not cur.execute("SELECT 1 FROM workspaceScreens WHERE _id=0").fetchone():
        cur.execute("INSERT INTO workspaceScreens (_id,screenRank,modified) VALUES (0,0,?)", (now,))

    c.commit()
    rows = cur.execute("SELECT title,container,screen,cellX,cellY FROM favorites").fetchall()
    print(f"favorites rewritten: {len(rows)} 项")
    for r in rows:
        print(" ", r)

if __name__ == "__main__":
    main()
