@echo off
setlocal
cd /d "%~dp0"
set PATH=C:\Program Files\nodejs;%PATH%

start "CloudPhone Backend" cmd /k "cd /d ""%~dp0backend"" && .venv-local\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
start "CloudPhone Frontend" cmd /k "cd /d ""%~dp0frontend"" && pnpm install && pnpm run dev -- --host 0.0.0.0 --port 5173"
if exist "%~dp0pc-client\package.json" (
    start "CloudPhone PC Client" cmd /k "cd /d ""%~dp0pc-client"" && npm install && npm run dev"
)

echo =====================
echo Backend: http://localhost:8000/docs
echo Frontend: http://localhost:5173
echo PC Client: launched if dependencies are present
echo =====================
