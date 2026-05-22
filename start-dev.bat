@echo off
chcp 65001 >nul

echo [Wolfpack] Starting dev environment...
echo.

REM ── Backend ──────────────────────────────────────────────────────────
start "Wolfpack Backend (port 8080)" cmd /k "cd /d %~dp0backend && (if not exist venv (python -m venv venv && call venv\Scripts\activate.bat && pip install -q --upgrade pip && pip install -q -r requirements.txt) else (call venv\Scripts\activate.bat)) && (if not exist .env (copy .env.example .env)) && set WOLFPACK_DEBUG=true && python main.py"

REM 等 backend 起来 (约 5s)
timeout /t 5 >nul

REM ── Frontend (Vite) ──────────────────────────────────────────────────
start "Wolfpack Frontend (port 5173)" cmd /k "cd /d %~dp0frontend && (if not exist node_modules (pnpm install)) && pnpm dev"

REM 等 Vite 起 (3s 通常够)
timeout /t 3 >nul

REM ── Electron 窗口 ────────────────────────────────────────────────────
start "Wolfpack Electron" cmd /k "cd /d %~dp0electron && (if not exist node_modules (pnpm install)) && pnpm start"

echo.
echo   Backend  : http://localhost:8080
echo   Frontend : http://localhost:5173
echo   Electron : 弹出独立窗口
echo.
echo 首次启动请前往「设置」页填 API key (齿轮按钮)
echo Close the opened window(s) to stop services.
