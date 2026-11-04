# 一次性准备好本地开发环境（Windows）：Python 虚拟环境 + 后端依赖 + backend\.env + 前端依赖。
# 用法：powershell -ExecutionPolicy Bypass -File scripts\dev-setup.ps1
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root "backend\.venv"
$Py = Join-Path $Venv "Scripts\python.exe"

Write-Host "==> 检查 Python 版本（需要 3.11+）"
python -c "import sys; sys.exit('需要 Python 3.11+，当前 ' + sys.version.split()[0]) if sys.version_info < (3, 11) else print('   Python ' + sys.version.split()[0] + ' OK')"

Write-Host "==> 创建后端虚拟环境 backend\.venv"
if (-not (Test-Path $Py)) {
    python -m venv $Venv
}

Write-Host "==> 安装后端依赖（含 pytest / ruff）"
& $Py -m pip install -q --upgrade pip
& $Py -m pip install -q -r (Join-Path $Root "backend\requirements-dev.txt")

Write-Host "==> 准备 backend\.env"
$EnvFile = Join-Path $Root "backend\.env"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $Root "backend\.env.example") $EnvFile
    Write-Host "   已从 .env.example 生成（默认 simulator + SQLite），需要真机/云机时再改"
}

Write-Host "==> 安装前端依赖（Node >= 22.13，包管理器 pnpm）"
if (-not (Test-Path (Join-Path $Root "frontend\node_modules"))) {
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue) -and (Get-Command corepack -ErrorAction SilentlyContinue)) {
        corepack enable
    }
    if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
        throw "未找到 pnpm：请先执行 npm i -g pnpm"
    }
    Push-Location (Join-Path $Root "frontend")
    pnpm install --frozen-lockfile
    Pop-Location
}

Write-Host ""
Write-Host "环境就绪。下一步："
Write-Host "  启动整套：start-all.bat            （后端 :8000 + 前端 :5173）"
Write-Host "  跑测试：  backend\.venv\Scripts\python.exe -m pytest backend\tests -q"
