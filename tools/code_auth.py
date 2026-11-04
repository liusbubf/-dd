#!/usr/bin/env python3
"""本地改代码口令门禁。

用途：在提交前确认「操作者知道改代码口令」，避免误改 / 未授权改动进入仓库。

口令来源优先级（三者取其一，均为本地未跟踪文件）：
  1. 环境变量 CODE_AUTH_PASSWORD
  2. 项目根 .env 或 backend/.env 中的 CODE_AUTH_PASSWORD
  3. 项目根 auth.local.json 中的 code_auth_password

通过校验后会在项目根写入 .code-auth（含签发时间、过期时间与 HMAC 签名），有效期 30 分钟。
.git/hooks 或 .githooks/pre-commit 通过 `python tools/code_auth.py --check` 调用本脚本。

安全说明：本文件**不包含任何口令明文**，口令只存在 .env / auth.local.json（已被 .gitignore 忽略）。
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUTH_FILE = ROOT / ".code-auth"
ENV_FILES = (ROOT / ".env", ROOT / "backend" / ".env")
LOCAL_JSON = ROOT / "auth.local.json"
VALID_MINUTES = 30


def _read_env_value(path: Path, key: str) -> str | None:
    """从极简 KEY=VALUE 格式的 .env 中取值（不引入 python-dotenv 依赖）。"""
    if not path.is_file():
        return None
    try:
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def get_password() -> str | None:
    """按优先级读取本地口令；都没有则返回 None（视为未配置）。"""
    value = os.environ.get("CODE_AUTH_PASSWORD")
    if value and value.strip():
        return value.strip()

    for path in ENV_FILES:
        value = _read_env_value(path, "CODE_AUTH_PASSWORD")
        if value:
            return value

    if LOCAL_JSON.is_file():
        try:
            data = json.loads(LOCAL_JSON.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for key in ("code_auth_password", "CODE_AUTH_PASSWORD"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return None


def _signature(password: str, payload: str) -> str:
    return hmac.new(
        password.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def issue(password: str) -> dict:
    """签发新令牌并落盘。"""
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=VALID_MINUTES)
    payload = f"{now.isoformat()}|{expires.isoformat()}"
    record = {
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "valid_minutes": VALID_MINUTES,
        "sig": _signature(password, payload),
    }
    AUTH_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return record


def check(password: str | None = None) -> tuple[bool, str]:
    """校验令牌；未通过时返回原因。"""
    password = password or get_password()
    if not password:
        return False, "未配置 CODE_AUTH_PASSWORD（请在 .env 或 auth.local.json 中设置）"

    if not AUTH_FILE.is_file():
        return False, "未找到 .code-auth，请先运行 python tools/code_auth.py"

    try:
        record = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        issued_at = record["issued_at"]
        expires_at = record["expires_at"]
        sig = record["sig"]
    except (OSError, json.JSONDecodeError, KeyError):
        return False, ".code-auth 内容损坏，请重新运行 python tools/code_auth.py"

    expect = _signature(password, f"{issued_at}|{expires_at}")
    if not hmac.compare_digest(str(sig), expect):
        return False, ".code-auth 签名不匹配（口令已变更或文件被篡改），请重新授权"

    try:
        expires = datetime.fromisoformat(expires_at)
    except ValueError:
        return False, ".code-auth 过期时间格式非法，请重新授权"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if datetime.now(timezone.utc) > expires:
        return False, f"授权已过期（有效期 {VALID_MINUTES} 分钟），请重新运行 python tools/code_auth.py"

    return True, f"授权有效，至 {expires.astimezone().strftime('%Y-%m-%d %H:%M:%S')}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地改代码口令门禁")
    parser.add_argument("--check", action="store_true", help="仅校验令牌（供 git 钩子调用）")
    parser.add_argument("--status", action="store_true", help="查看当前授权状态")
    parser.add_argument("--revoke", action="store_true", help="删除 .code-auth")
    parser.add_argument("--password", help="非交互传入口令（会留在命令历史，不推荐）")
    args = parser.parse_args(argv)

    if args.check:
        ok, message = check()
        if not ok:
            print(f"[code_auth] 拒绝：{message}", file=sys.stderr)
            return 1
        return 0

    if args.status:
        ok, message = check()
        print(("[code_auth] " + ("✔ " if ok else "✘ ") + message))
        return 0 if ok else 1

    if args.revoke:
        AUTH_FILE.unlink(missing_ok=True)
        print("[code_auth] 已删除 .code-auth")
        return 0

    stored = get_password()
    if not stored:
        print(
            "[code_auth] 未配置 CODE_AUTH_PASSWORD。\n"
            "  请复制 .env.example 为 .env 并填写 CODE_AUTH_PASSWORD，\n"
            "  或在 auth.local.json 中设置 {\"code_auth_password\": \"<你的口令>\"}。",
            file=sys.stderr,
        )
        return 2

    supplied = args.password or getpass.getpass("请输入改代码口令: ")
    if not hmac.compare_digest(supplied.strip(), stored):
        print("[code_auth] 口令错误。", file=sys.stderr)
        return 1

    record = issue(stored)
    print(
        f"[code_auth] 授权成功，有效期 {VALID_MINUTES} 分钟，"
        f"至 {record['expires_at']}（本地文件 .code-auth，已被 .gitignore 忽略）"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
