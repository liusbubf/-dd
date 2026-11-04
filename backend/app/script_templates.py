"""内置脚本模板库（GM-205 / 7.4.4 模板库）。

每个模板：``{name, description, steps}``。步骤复用现有动作
（open_url / tap / swipe / text / key / wait）并支持逻辑控制 ``loop``：
``{"action": "loop", "params": {"count": N, "steps": [...]}}``。

模板是「只读种子」，通过 ``POST /scripts/from-template`` 复制成一个真实脚本。
"""
from __future__ import annotations

TEMPLATES: list[dict] = [
    {
        "name": "打开网页并滑动浏览",
        "description": "打开指定网页，等待加载后上下滑动浏览页面内容。",
        "steps": [
            {"action": "open_url", "params": {"url": "https://whoer.net"}},
            {"action": "wait", "params": {"seconds": 1}},
            {"action": "swipe", "params": {"x1": 540, "y1": 1600, "x2": 540, "y2": 600, "duration_ms": 300}},
            {"action": "wait", "params": {"seconds": 0.5}},
            {"action": "swipe", "params": {"x1": 540, "y1": 600, "x2": 540, "y2": 1600, "duration_ms": 300}},
        ],
    },
    {
        "name": "登录流程(开页→点击→输入→提交)",
        "description": "打开登录页，点击账号框输入用户名，点击密码框输入密码，回车提交。",
        "steps": [
            {"action": "open_url", "params": {"url": "https://example.com/login"}},
            {"action": "wait", "params": {"seconds": 1}},
            {"action": "tap", "params": {"x": 540, "y": 700}},
            {"action": "text", "params": {"text": "demo_user"}},
            {"action": "tap", "params": {"x": 540, "y": 900}},
            {"action": "text", "params": {"text": "demo_pass"}},
            {"action": "tap", "params": {"x": 540, "y": 1100}},
            {"action": "key", "params": {"key": "enter"}},
        ],
    },
    {
        "name": "循环刷新 5 次",
        "description": "打开网页后循环 5 次：下拉刷新并等待，模拟定时刷新。",
        "steps": [
            {"action": "open_url", "params": {"url": "https://whoer.net"}},
            {
                "action": "loop",
                "params": {
                    "count": 5,
                    "steps": [
                        {"action": "swipe", "params": {"x1": 540, "y1": 500, "x2": 540, "y2": 1400, "duration_ms": 300}},
                        {"action": "wait", "params": {"seconds": 1}},
                    ],
                },
            },
        ],
    },
    {
        "name": "循环点赞(循环点击)",
        "description": "打开信息流后循环 10 次：点击点赞位置、短暂等待、上滑到下一条。",
        "steps": [
            {"action": "open_url", "params": {"url": "https://example.com/feed"}},
            {"action": "wait", "params": {"seconds": 1}},
            {
                "action": "loop",
                "params": {
                    "count": 10,
                    "steps": [
                        {"action": "tap", "params": {"x": 900, "y": 1500}},
                        {"action": "wait", "params": {"seconds": 0.5}},
                        {"action": "swipe", "params": {"x1": 540, "y1": 1400, "x2": 540, "y2": 700, "duration_ms": 300}},
                    ],
                },
            },
        ],
    },
]
