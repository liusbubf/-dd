#!/usr/bin/env bash
# 一条命令起后端 + 前端（macOS / Linux）。首次运行会自动准备环境。
# 用法：bash start-all.sh    后端 http://localhost:8000/docs   前端 http://localhost:5173
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/backend/.venv"

if [ ! -x "$VENV/bin/python" ] || [ ! -f "$ROOT/backend/.env" ]; then
  echo "==> 首次运行，先准备环境"
  bash "$ROOT/scripts/dev-setup.sh"
fi

echo "==> 启动后端 http://localhost:8000/docs"
(cd "$ROOT/backend" && "$VENV/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port 8000) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

echo "==> 启动前端 http://localhost:5173（Ctrl+C 同时结束后端）"
cd "$ROOT/frontend"
pnpm run dev -- --host 0.0.0.0 --port 5173
