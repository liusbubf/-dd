#!/usr/bin/env python
"""RBAC 初始账号初始化（幂等，可重复执行）。

作用：按四个角色创建/补齐初始账号，不覆盖已有账号的口令（除非显式 --reset-password）。

口令来源（优先级）：
1. 环境变量 CLOUD_SEED_PWD_SUPERADMIN / _ADMIN / _OPERATOR / _VIEWER
2. 未提供时用 secrets 生成强口令，打印到终端并写入本地未跟踪文件 .seed_passwords.json

用法（在项目根目录执行）：
    python tools/seed_rbac.py --dry-run        # 只看会做什么，不写账号/口令文件
    python tools/seed_rbac.py                  # 实际执行
    python tools/seed_rbac.py --reset-password # 重置口令（危险，仅显式指定时执行）
    python tools/seed_rbac.py --role operator --username op1   # 只初始化一个自定义账号

默认账号：shuntian(superadmin) / admin(admin) / operator(operator) / viewer(viewer)
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
PASSWORD_FILE = ROOT / ".seed_passwords.json"

ENV_VARS = {
    "superadmin": "CLOUD_SEED_PWD_SUPERADMIN",
    "admin": "CLOUD_SEED_PWD_ADMIN",
    "operator": "CLOUD_SEED_PWD_OPERATOR",
    "viewer": "CLOUD_SEED_PWD_VIEWER",
}

DEFAULT_ACCOUNTS = {
    "superadmin": "shuntian",
    "admin": "admin",
    "operator": "operator",
    "viewer": "viewer",
}

# 生成口令用的字符集：去掉易混淆字符（0/O、1/l/I）
_ALPHABET = "".join(
    c for c in (string.ascii_letters + string.digits) if c not in "0O1lI"
)


def generate_password(length: int = 20) -> str:
    """生成满足后端复杂度校验（>=6 位、含字母、含数字）的强口令。"""
    while True:
        pwd = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if any(c.isalpha() for c in pwd) and any(c.isdigit() for c in pwd):
            return pwd


def _bootstrap_env() -> None:
    """先加载 .env，再确定数据库地址，最后才能 import app 模块。

    backend 默认以 backend/ 为工作目录运行，SQLite 落在 backend/cloud_platform.db；
    本脚本从项目根运行，若未显式配置，必须指到同一个库，否则会往空库里播种。
    """
    for envfile in (ROOT / ".env", BACKEND / ".env"):
        if envfile.exists():
            load_dotenv(envfile, override=False)
    if not os.getenv("CLOUD_DATABASE_URL"):
        db_file = BACKEND / "cloud_platform.db"
        os.environ["CLOUD_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    sys.path.insert(0, str(BACKEND))


def _load_password_file() -> dict:
    if not PASSWORD_FILE.exists():
        return {}
    try:
        data = json.loads(PASSWORD_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_password_file(data: dict) -> None:
    PASSWORD_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:  # POSIX 下收紧为仅本人可读写；Windows 上 chmod 只影响只读位，尽量而为
        os.chmod(PASSWORD_FILE, 0o600)
    except OSError:
        pass


def _parse_targets(args: argparse.Namespace) -> list[tuple[str, str]]:
    """返回 [(role, username)] 目标列表。

    --username 支持两种写法：
      role=name（如 superadmin=boss）——覆盖该角色的默认账号名
      纯名字（需配合 --role）——只初始化这一个账号
    """
    targets: dict[str, str] = {}

    if not args.username:
        if args.role:
            if args.role not in DEFAULT_ACCOUNTS:
                raise SystemExit(f"未知角色：{args.role}")
            targets[args.role] = DEFAULT_ACCOUNTS[args.role]
        else:
            targets.update(DEFAULT_ACCOUNTS)
        return list(targets.items())

    for raw in args.username:
        if "=" in raw:
            role, name = (s.strip() for s in raw.split("=", 1))
            if role not in DEFAULT_ACCOUNTS:
                raise SystemExit(f"未知角色：{role}")
            if not name:
                raise SystemExit(f"账号名为空：{raw}")
            targets[role] = name
        else:
            if not args.role:
                raise SystemExit("纯账号名必须配合 --role 使用，或写成 role=name")
            if args.role not in DEFAULT_ACCOUNTS:
                raise SystemExit(f"未知角色：{args.role}")
            targets[args.role] = raw.strip()

    return list(targets.items())


async def run(args: argparse.Namespace) -> int:
    targets = _parse_targets(args)
    _bootstrap_env()

    from sqlalchemy import select

    from app.auth import hash_password
    from app.database import SessionLocal, init_db
    from app.models import User

    await init_db()  # 表不存在时先建表；已存在时无副作用

    rows: list[dict] = []
    generated: dict[str, str] = {}
    pwd_file = _load_password_file()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async with SessionLocal() as db:
        for role, username in targets:
            env_var = ENV_VARS[role]
            env_pwd = os.getenv(env_var, "").strip()
            source = f"env:{env_var}" if env_pwd else "generated"

            user = (
                await db.execute(select(User).where(User.username == username))
            ).scalar_one_or_none()

            action = "跳过（口令未变）"
            if user is None:
                pwd = env_pwd or generate_password()
                if not env_pwd:
                    generated[username] = pwd
                if not args.dry_run:
                    db.add(
                        User(
                            username=username,
                            password_hash=hash_password(pwd),
                            role=role,
                        )
                    )
                    await db.commit()
                action = "新建"
            else:
                changes = []
                if user.role != role:
                    if not args.dry_run:
                        user.role = role
                    changes.append(f"角色 {user.role} → {role}")
                if args.reset_password:
                    pwd = env_pwd or generate_password()
                    if not env_pwd:
                        generated[username] = pwd
                    if not args.dry_run:
                        user.password_hash = hash_password(pwd)
                    changes.append("重置口令")
                if changes:
                    if not args.dry_run:
                        await db.commit()
                    action = "更新：" + "、".join(changes)
                if changes and source == "generated" and "重置口令" in changes:
                    pwd_file[username] = {
                        "role": role,
                        "password": generated[username],
                        "source": source,
                        "updated_at": now,
                    }

            rows.append(
                {
                    "username": username,
                    "role": role,
                    "created": "是" if action == "新建" else "否",
                    "action": action,
                    "source": source if action != "跳过（口令未变）" else "-",
                }
            )

    if generated and not args.dry_run:
        role_of = {name: role for role, name in targets}
        for username, pwd in generated.items():
            entry = pwd_file.get(username, {})
            entry.update(
                {
                    "role": role_of.get(username, entry.get("role", "")),
                    "password": pwd,
                    "source": "generated",
                    "updated_at": now,
                }
            )
            pwd_file[username] = entry
        _save_password_file(pwd_file)

    _print_table(rows, dry_run=args.dry_run)
    if generated:
        if args.dry_run:
            print("\n[dry-run] 本次将会生成的口令（未写入任何文件）：")
        else:
            print("\n本次生成的口令（仅显示一次，已写入 .seed_passwords.json，请勿提交）：")
        for username, pwd in generated.items():
            print(f"  {username} / {pwd}")
    elif not args.dry_run:
        print("\n本次未生成新口令（使用环境变量或未重置已有账号）。")
    if args.dry_run:
        print("\n[dry-run] 未写入账号数据，也未写 .seed_passwords.json（仅确保表结构存在以便查询）。")
    return 0


def _print_table(rows: list[dict], dry_run: bool) -> None:
    headers = ["账号", "角色", "是否新建", "动作", "口令来源"]
    keys = ["username", "role", "created", "action", "source"]
    widths = [
        max([len(h)] + [len(str(r[k])) for r in rows]) for h, k in zip(headers, keys)
    ]

    def line(cells: list[str]) -> str:
        return " | ".join(c.ljust(w) for c, w in zip(cells, widths))

    print(("[dry-run] " if dry_run else "") + "RBAC 初始账号：")
    print(line(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(line([r[k] for k in keys]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="初始化 RBAC 四角色账号（幂等，可重复执行）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写库/不写口令文件")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="重置已存在账号的口令（默认不覆盖原口令）",
    )
    parser.add_argument(
        "--username",
        action="append",
        metavar="[ROLE=]NAME",
        help="覆盖账号名：role=name，或纯名字配合 --role",
    )
    parser.add_argument(
        "--role",
        choices=sorted(DEFAULT_ACCOUNTS),
        help="只处理该角色（配合纯 --username 使用时指定角色）",
    )
    args = parser.parse_args()

    import asyncio

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
