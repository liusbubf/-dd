"""端到端主流程冒烟测试（对齐 demo 验收清单 8 条）。

用法：backend 已启动后，运行
    python -m tests.smoke

⚠️ 只允许打 simulator 后端：脚本会批量建 10 台/删设备，误打真机后端（redroid）
会真的起 10 个容器把 VM 内存打爆（真发生过）。redroid 后端需显式 --i-know-redroid。
"""
from __future__ import annotations

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import httpx

BASE = "http://127.0.0.1:8000/api"
client = httpx.Client(base_url=BASE, trust_env=False, timeout=30)


def _guard_backend() -> None:
    """冒烟前置检查：拒绝在 redroid（真机）后端上跑，除非显式带 --i-know-redroid。"""
    r = client.get("/health")
    backend = r.json().get("backend", "?")
    if backend != "simulator" and "--i-know-redroid" not in sys.argv:
        fail(
            f"当前后端是 {backend}（真机），冒烟会批量建 10 台真容器打爆 VM；"
            "请连 simulator 后端再跑，或显式加 --i-know-redroid"
        )


def ok(msg: str) -> None:
    print(f"  [OK] {msg}")


def fail(msg: str) -> None:
    print(f"  [FAIL] {msg}")
    sys.exit(1)


def _cleanup_demo_state() -> None:
    """清理历史残留的 demo 资源，保证一次冒烟测试始终从干净状态开始。"""
    existing = client.get("/devices").json()
    stale_device_ids = [d["id"] for d in existing if d.get("name", "").startswith("演示机")]
    if stale_device_ids:
        client.post("/devices/batch-delete", json={"device_ids": stale_device_ids})

    groups = client.get("/groups").json()
    for group in groups:
        if group.get("name") == "矩阵A组":
            client.delete(f"/groups/{group['id']}")


def main() -> None:
    _guard_backend()
    # 1. 登录
    print("§1 登录")
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    ok(f"账号密码登录成功，token={token[:16]}…")

    _cleanup_demo_state()

    # 2. 批量建机
    print("§2 批量建 10 台云手机（iOS 皮肤 + 开网页）")
    r = client.post(
        "/devices/batch",
        json={"count": 10, "name_prefix": "演示机", "target_url": "https://browserleaks.com", "auto_start": True},
    )
    assert r.status_code == 200, r.text
    devices = r.json()
    running = [d for d in devices if d["status"] == "running"]
    assert len(running) == 10, [d["status"] for d in devices]
    ok(f"创建并启动 {len(running)}/10 台，状态均为 running")

    # 3. 独立身份（一机一码）
    print("§3 抽查 3 台：设备标识 / 出口 IP / 浏览器指纹各不相同")
    sample = devices[:3]
    models = {d["fingerprint"]["device"]["android_id"] for d in sample}
    ips = {d["fingerprint"]["network"]["exit_ip"] for d in sample}
    uas = {d["fingerprint"]["browser"]["user_agent"] for d in sample}
    assert len(models) == 3 and len(ips) == 3 and len(uas) == 3, "指纹出现重复"
    for d in sample:
        fp = d["fingerprint"]
        print(
            f"    {d['name']}: model={fp['device']['model']:<16} "
            f"ip={fp['network']['exit_ip']:<15} tz={fp['browser']['timezone']:<16} "
            f"chrome={fp['browser']['chrome_version']}"
        )
    ok("3 台的 android_id / 出口 IP / UA 全部互不相同")

    # 4. 预览帧（多画面预览基础）
    print("§4 预览帧渲染（Web/PC 多画面预览的数据源）")
    d0 = devices[0]
    r = client.get(f"/devices/{d0['id']}/screenshot")
    assert r.status_code == 200 and r.json()["frame"].startswith("data:image/"), r.text
    ok(f"设备 {d0['id']} 预览帧生成成功（{len(r.json()['frame'])} 字节 data URL）")

    # 5. 单机操控
    print("§5 单台操控：打开网页 + tap + 输入")
    did = d0["id"]
    assert client.post(f"/devices/{did}/control/open_url", json={"url": "https://ip.sb"}).status_code == 200
    assert client.post(f"/devices/{did}/control/tap", json={"x": 200, "y": 400}).status_code == 200
    assert client.post(f"/devices/{did}/control/text", json={"text": "hello"}).status_code == 200
    cur = client.get(f"/devices/{did}").json()["current_url"]
    assert cur == "https://ip.sb", cur
    ok("单机 open_url / tap / text 成功，当前页已切到 https://ip.sb")

    # 6. 批量同步：一键全部开同一网页
    print("§6 批量同步：一键让全部设备打开同一网页 + 同步 tap")
    ids = [d["id"] for d in devices]
    r = client.post("/batch/open_url", json={"device_ids": ids, "url": "https://example.com"})
    assert r.status_code == 200 and r.json()["ok"] == 10, r.text
    r = client.post("/batch/tap", json={"device_ids": ids, "x": 540, "y": 960})
    assert r.status_code == 200 and r.json()["ok"] == 10, r.text
    changed = [d for d in client.get("/devices").json() if d["current_url"] == "https://example.com"]
    assert len(changed) == 10, len(changed)
    ok("10 台全部切到 https://example.com，批量 tap 10/10 成功")

    # 7. 分组
    print("§7 分组管理")
    gid = client.post("/groups", json={"name": "矩阵A组"}).json()["id"]
    client.patch(f"/devices/{ids[0]}", json={"group_id": gid})
    cnt = next(g for g in client.get("/groups").json() if g["id"] == gid)["device_count"]
    assert cnt == 1, cnt
    ok(f"新建分组『矩阵A组』并归入 1 台设备（device_count={cnt}）")

    # 8. 脚本录制 → 跨设备回放
    print("§8 脚本录制 → 跨设备回放")
    script = client.post(
        "/scripts",
        json={
            "name": "开网页并操作",
            "steps": [
                {"action": "open_url", "params": {"url": "https://whoer.net"}},
                {"action": "wait", "params": {"seconds": 0.1}},
                {"action": "swipe", "params": {"x1": 540, "y1": 1600, "x2": 540, "y2": 600}},
                {"action": "tap", "params": {"x": 300, "y": 500}},
            ],
        },
    ).json()
    run = client.post(f"/scripts/{script['id']}/run", json={"device_ids": ids[:3]}).json()
    assert run["status"] == "success", run
    assert all(r["status"] == "success" for r in run["results"]), run
    ok(f"脚本『{script['name']}』在 3 台设备回放成功（run_id={run['id']}）")

    print("\n全部 8 项主流程验收通过")


if __name__ == "__main__":
    main()
