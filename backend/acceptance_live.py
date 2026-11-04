"""真机（redroid）验收核验脚本 —— 对齐 demo 验收清单 8 条。

与 `tests/smoke.py` 的区别：
    smoke.py        针对 simulator，会**批量建 10 台**并留下测试数据，拒绝打真机后端。
    acceptance_live 针对 **redroid 真机**，**非破坏性**：只用现有在跑的设备做核验，
                    不建机、不删机，跑完把设备原来打开的网页还原回去。

用法（后端已启动的前提下）：
    python acceptance_live.py                          # 连本机 8000
    python acceptance_live.py --base http://10.0.0.9:8000/api
    python acceptance_live.py --password 你的密码
    python acceptance_live.py --keep-url               # 不还原设备原网页

判据说明：
    验收 2「建机 10 台」属破坏性操作，本脚本不代跑，只统计当前在跑台数：
    ≥10 台记 PASS，<10 台记 SKIP 并提示用 Web 控制台「批量建机」验证。
"""
from __future__ import annotations

import argparse
import sys
import time

import httpx

GREEN, RED, YELLOW, DIM, RESET = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"

results: list[tuple[str, str, str]] = []  # (验收项, 结论, 说明)


def record(item: str, verdict: str, detail: str) -> None:
    color = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}[verdict]
    mark = {"PASS": "✓", "FAIL": "✗", "SKIP": "○"}[verdict]
    print(f"  {color}{mark} [{verdict}]{RESET} {detail}")
    results.append((item, verdict, detail))


def main() -> int:
    ap = argparse.ArgumentParser(description="真机验收核验（非破坏性）")
    ap.add_argument("--base", default="http://127.0.0.1:8000/api", help="后端 API 地址")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--password", default="admin123")
    ap.add_argument("--keep-url", action="store_true", help="跑完不还原设备原来的网页")
    args = ap.parse_args()

    # trust_env=False：绕开宿主机的 http_proxy，否则访问 localhost 会被代理拦成 502
    client = httpx.Client(base_url=args.base, trust_env=False, timeout=60)

    print("=" * 68)
    print("  X86 云手机平台 · 真机验收核验（非破坏性）")
    print("=" * 68)

    # ---- 前置：后端可达性与模式 ----
    try:
        health = client.get("/health").json()
    except Exception as exc:
        print(f"{RED}后端不可达：{exc}{RESET}")
        print(f"{DIM}检查：systemctl status cloudphone-backend / 地址是否正确{RESET}")
        return 2
    backend = health.get("backend", "?")
    print(f"后端模式：{backend}    地址：{args.base}")
    if backend != "redroid":
        print(f"{YELLOW}提示：当前是 {backend} 模式，不是真机。真机验收请设 "
              f"CLOUD_DEVICE_BACKEND=redroid{RESET}")
    print()

    # ---- 验收 1：登录 ----
    print("§1 登录")
    t0 = time.time()
    r = client.post("/auth/login", json={"username": args.username, "password": args.password})
    if r.status_code != 200:
        record("1 登录", "FAIL", f"HTTP {r.status_code}：{r.text[:120]}")
        return 1
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    record("1 登录", "PASS", f"账号密码登录成功，JWT 下发，耗时 {(time.time()-t0)*1000:.0f} ms")

    # ---- 取现有设备 ----
    devices = client.get("/devices").json()
    running = [d for d in devices if d.get("status") == "running"]
    print(f"\n{DIM}当前设备：共 {len(devices)} 台，运行中 {len(running)} 台{RESET}")
    if not running:
        print(f"{RED}没有运行中的设备，无法继续。请先在 Web 控制台建机并启动。{RESET}")
        return 1

    original_urls = {d["id"]: d.get("current_url") for d in running}

    # ---- 验收 2：建机（只统计，不代跑）----
    print("\n§2 建机（iOS 皮肤）")
    if len(running) >= 10:
        record("2 建机", "PASS", f"当前 {len(running)} 台运行中（≥10），满足判据")
    else:
        record("2 建机", "SKIP",
               f"当前仅 {len(running)} 台运行中（<10）。本脚本不代建机以免打爆内存，"
               f"请用 Web 控制台「批量建机」建 10 台后复核")
    skins = {d.get("skin") for d in running if d.get("skin")}
    if skins:
        print(f"    {DIM}皮肤分布：{', '.join(sorted(skins))}{RESET}")

    # ---- 验收 4：一机一码（先验，因为不改变状态）----
    print("\n§4 独立身份（一机一码）")
    sample = running[:3]
    if len(sample) < 3:
        record("4 独立身份", "SKIP", f"运行中设备不足 3 台（{len(sample)} 台），无法抽查")
    else:
        try:
            aids = {d["fingerprint"]["device"]["android_id"] for d in sample}
            ips = {d["fingerprint"]["network"]["exit_ip"] for d in sample}
            uas = {d["fingerprint"]["browser"]["user_agent"] for d in sample}
            for d in sample:
                fp = d["fingerprint"]
                print(f"    {DIM}{d['name']}: android_id={fp['device']['android_id']} "
                      f"ip={fp['network']['exit_ip']}{RESET}")
            if len(aids) == 3 and len(ips) == 3 and len(uas) == 3:
                record("4 独立身份", "PASS", "3 台的 android_id / 出口 IP / User-Agent 全部互不相同")
            else:
                dup = []
                if len(aids) < 3:
                    dup.append("android_id")
                if len(ips) < 3:
                    dup.append("出口 IP")
                if len(uas) < 3:
                    dup.append("User-Agent")
                record("4 独立身份", "FAIL", f"以下维度出现重复：{'、'.join(dup)}")
        except (KeyError, TypeError) as exc:
            record("4 独立身份", "FAIL", f"指纹字段缺失：{exc}")

    # ---- 验收 5：投屏预览 ----
    # 注意：redroid 模式下取帧失败会静默回退成平台层渲染的 SVG 皮肤图。
    # 画面看着正常，实际那台设备的 adb 已经断了——必须把 SVG 帧当异常揪出来。
    print("\n§5 投屏预览（多画面数据源）")
    frames_ok, png_cnt, total_ms = 0, 0, 0.0
    svg_devices: list[int] = []
    for d in running:
        t0 = time.time()
        try:
            fr = client.get(f"/devices/{d['id']}/screenshot").json().get("frame", "")
        except Exception:
            fr = ""
        ms = (time.time() - t0) * 1000
        if fr.startswith("data:image/"):
            frames_ok += 1
            total_ms += ms
            if fr.startswith("data:image/png"):
                png_cnt += 1
            elif backend == "redroid":
                svg_devices.append(d["id"])
    avg = total_ms / max(frames_ok, 1)
    if frames_ok != len(running):
        record("5 投屏预览", "FAIL", f"仅 {frames_ok}/{len(running)} 台取帧成功")
    elif svg_devices:
        record("5 投屏预览", "FAIL",
               f"{frames_ok}/{len(running)} 台有画面，但设备 {svg_devices} 返回的是平台层皮肤图"
               f"而非真机实拍帧 —— 这些设备的 adb 已断连，画面是回退渲染的假象")
        print(f"    {YELLOW}修复：adb connect localhost:{'/'.join(str(5555 + i) for i in svg_devices)}"
              f"（端口 = 5555 + 设备ID），再重启后端服务{RESET}")
    else:
        record("5 投屏预览", "PASS",
               f"{frames_ok}/{len(running)} 台成功取帧且全部为真机 PNG 实拍帧，平均 {avg:.0f} ms/帧")

    # ---- 验收 3 + 6：开网页 + 单台操控 ----
    print("\n§3+§6 开网页 与 单台操控")
    d0 = running[0]
    did = d0["id"]
    probe_url = "https://example.com"
    t0 = time.time()
    r1 = client.post(f"/devices/{did}/control/open_url", json={"url": probe_url})
    open_ms = (time.time() - t0) * 1000
    t0 = time.time()
    r2 = client.post(f"/devices/{did}/control/tap", json={"x": 200, "y": 400})
    tap_ms = (time.time() - t0) * 1000
    r3 = client.post(f"/devices/{did}/control/key", json={"key": "home"})

    if r1.status_code == 200:
        cur = client.get(f"/devices/{did}").json().get("current_url")
        if cur == probe_url:
            record("3 开网页", "PASS",
                   f"设备 {did} 打开 {probe_url} 成功（下发耗时 {open_ms:.0f} ms）")
        else:
            record("3 开网页", "FAIL", f"下发成功但 current_url={cur}，期望 {probe_url}")
    else:
        record("3 开网页", "FAIL", f"HTTP {r1.status_code}：{r1.text[:120]}")

    if r2.status_code == 200 and r3.status_code == 200:
        record("6 单台操控", "PASS",
               f"tap 往返 {tap_ms:.0f} ms、key(home) 成功，操控通道正常")
    else:
        record("6 单台操控", "FAIL",
               f"tap HTTP {r2.status_code} / key HTTP {r3.status_code}")

    # ---- 验收 7：批量同步 ----
    print("\n§7 批量同步（1 控 N）")
    ids = [d["id"] for d in running]
    batch_url = "https://example.org"
    t0 = time.time()
    rb = client.post("/batch/open_url", json={"device_ids": ids, "url": batch_url})
    batch_s = time.time() - t0
    if rb.status_code == 200:
        okn = rb.json().get("ok", 0)
        rt = client.post("/batch/tap", json={"device_ids": ids, "x": 540, "y": 960})
        tapn = rt.json().get("ok", 0) if rt.status_code == 200 else 0
        if okn == len(ids) and tapn == len(ids):
            record("7 批量同步", "PASS",
                   f"批量开网页 {okn}/{len(ids)} 成功，耗时 {batch_s:.1f}s；同步 tap {tapn}/{len(ids)} 成功")
        else:
            record("7 批量同步", "FAIL", f"开网页 {okn}/{len(ids)}、tap {tapn}/{len(ids)}")
    else:
        record("7 批量同步", "FAIL", f"HTTP {rb.status_code}：{rb.text[:120]}")

    # ---- 验收 8：脚本跨设备回放 ----
    print("\n§8 脚本录制 → 跨设备回放")
    try:
        script = client.post("/scripts", json={
            "name": f"验收核验脚本-{int(time.time())}",
            "steps": [
                {"action": "open_url", "params": {"url": "https://example.com"}},
                {"action": "wait", "params": {"seconds": 0.5}},
                {"action": "swipe", "params": {"x1": 540, "y1": 1600, "x2": 540, "y2": 600}},
                {"action": "tap", "params": {"x": 300, "y": 500}},
            ],
        }).json()
        t0 = time.time()
        run = client.post(f"/scripts/{script['id']}/run", json={"device_ids": ids}).json()
        run_s = time.time() - t0
        succ = sum(1 for x in run.get("results", []) if x.get("status") == "success")
        if run.get("status") == "success" and succ == len(ids):
            record("8 脚本回放", "PASS",
                   f"脚本跨 {len(ids)} 台真机回放 {succ}/{len(ids)} 成功，耗时 {run_s:.1f}s")
        else:
            record("8 脚本回放", "FAIL",
                   f"回放 {succ}/{len(ids)} 成功，整体 status={run.get('status')}")
        client.delete(f"/scripts/{script['id']}")  # 清理临时脚本
    except Exception as exc:
        record("8 脚本回放", "FAIL", f"异常：{exc}")

    # ---- 真机佐证（非验收项，用于证明确实是真安卓而非模拟器）----
    print(f"\n{DIM}§附 真机佐证{RESET}")
    try:
        apps = client.get(f"/devices/{did}/apps").json()
        print(f"  {DIM}已装应用数：{apps.get('count', '?')}{RESET}")
    except Exception:
        pass
    try:
        logs = client.get(f"/devices/{did}/logcat", params={"lines": 10}).json()
        n = len(logs.get("lines", logs.get("logs", []))) if isinstance(logs, dict) else 0
        print(f"  {DIM}logcat 取到 {n} 行真实日志{RESET}")
    except Exception:
        pass

    # ---- 还原现场 ----
    if not args.keep_url:
        print(f"\n{DIM}还原设备原网页…{RESET}")
        restored = 0
        for dev_id, url in original_urls.items():
            if url:
                try:
                    if client.post(f"/devices/{dev_id}/control/open_url",
                                   json={"url": url}).status_code == 200:
                        restored += 1
                except Exception:
                    pass
        print(f"  {DIM}已还原 {restored} 台{RESET}")

    # ---- 汇总 ----
    print("\n" + "=" * 68)
    passed = sum(1 for _, v, _ in results if v == "PASS")
    failed = sum(1 for _, v, _ in results if v == "FAIL")
    skipped = sum(1 for _, v, _ in results if v == "SKIP")
    print(f"  验收汇总：{GREEN}{passed} 通过{RESET}  {RED}{failed} 失败{RESET}  {YELLOW}{skipped} 跳过{RESET}"
          f"  （共 {len(results)} 项）")
    for item, verdict, _ in results:
        color = {"PASS": GREEN, "FAIL": RED, "SKIP": YELLOW}[verdict]
        print(f"    {color}{verdict:<4}{RESET}  {item}")
    print("=" * 68)

    if failed:
        print(f"{RED}存在未通过项，请对照 docs/部署搭建手册_x86服务器_中国大陆.md 第 11 章排查。{RESET}")
        return 1
    if skipped:
        print(f"{YELLOW}无失败项，但有跳过项（通常是设备台数不足），补足后复跑即可。{RESET}")
        return 0
    print(f"{GREEN}全部验收项通过 ✅{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
