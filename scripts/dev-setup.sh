#!/usr/bin/env bash
# 一次性准备好本地开发环境：Python 虚拟环境 + 后端依赖 + backend/.env + 前端依赖。
# 用法：bash scripts/dev-setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV="$ROOT/backend/.venv"

echo "==> 检查 Python 版本（需要 3.11+）"
"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 11):
    sys.exit(f"需要 Python 3.11+，当前 {sys.version.split()[0]}")
print(f"   Python {sys.version.split()[0]} OK")
PY

echo "==> 创建后端虚拟环境 backend/.venv"
if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON_BIN" -m venv "$VENV"
fi

echo "==> 安装后端依赖（含 pytest / ruff）"
"$VENV/bin/python" -m pip install -q --upgrade pip
"$VENV/bin/python" -m pip install -q -r "$ROOT/backend/requirements-dev.txt"

echo "==> 准备 backend/.env"
if [ ! -f "$ROOT/backend/.env" ]; then
  cp "$ROOT/backend/.env.example" "$ROOT/backend/.env"
  echo "   已从 .env.example 生成（默认 simulator + SQLite），需要真机/云机时再改"
fi

echo "==> 安装前端依赖（Node ≥ 22.13，包管理器 pnpm）"
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  if ! command -v pnpm >/dev/null 2>&1 && command -v corepack >/dev/null 2>&1; then
    corepack enable
  fi
  if ! command -v pnpm >/dev/null 2>&1; then
    echo "未找到 pnpm：请先执行 npm i -g pnpm" >&2
    exit 1
  fi
  (cd "$ROOT/frontend" && pnpm install --frozen-lockfile)
fi

echo ""
echo "环境就绪。下一步："
echo "  启动整套：bash start-all.sh        （后端 :8000 + 前端 :5173）"
echo "  跑测试：  cd backend && .venv/bin/python -m pytest tests -q"
