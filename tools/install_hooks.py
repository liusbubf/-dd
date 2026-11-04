#!/usr/bin/env python3
"""安装本地 git 钩子（改代码口令门禁）。

说明：当前仓库是纯源码快照，**没有 .git**。本脚本会先检查是否存在 git 仓库：
  - 不存在：只打印提示并退出（不会 `git init`，也不创建仓库）；
  - 存在：设置 core.hooksPath 指向 .githooks，并给钩子加可执行权限。

将来执行 `git init` 之后，运行一次 `python tools/install_hooks.py` 即可生效。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = ROOT / ".githooks"
HOOK_FILE = HOOKS_DIR / "pre-commit"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def main() -> int:
    if not HOOK_FILE.is_file():
        print(f"[install_hooks] 缺少钩子文件：{HOOK_FILE}", file=sys.stderr)
        return 1

    probe = _git("rev-parse", "--is-inside-work-tree")
    if probe.returncode != 0:
        print(
            "[install_hooks] 当前目录不是 git 仓库（本仓库为源码快照，无 .git）。\n"
            "  钩子已就绪，但不会立即生效。\n"
            "  将来执行 `git init` 后，再做一次 `python tools/install_hooks.py` 即可启用。\n"
            "  在此之前，请手动遵守改代码口令流程（python tools/code_auth.py）。"
        )
        return 0

    result = _git("config", "core.hooksPath", ".githooks")
    if result.returncode != 0:
        print(f"[install_hooks] 设置 core.hooksPath 失败：{result.stderr.strip()}", file=sys.stderr)
        return 1

    if os.name != "nt":
        try:
            HOOK_FILE.chmod(0o755)
        except OSError as exc:
            print(f"[install_hooks] 设置可执行权限失败：{exc}", file=sys.stderr)
            return 1
    else:
        print(
            "[install_hooks] Windows 环境：`.githooks/pre-commit` 需由 Git for Windows 自带的\n"
            "  bash 执行（git 默认会调用 sh）。若无法执行，请在 Git Bash 中手动 chmod +x。"
        )

    print("[install_hooks] 已启用 .githooks/pre-commit（core.hooksPath=.githooks）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
