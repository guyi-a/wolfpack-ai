@echo off
chcp 65001 >nul

echo [Wolfpack] Starting dev environment...
echo.

start "Wolfpack Backend (port 8080)" cmd /k "cd /d %~dp0backend && (if not exist venv (python -m venv venv && call venv\Scripts\activate.bat && pip install -q --upgrade pip && pip install -q -r requirements.txt) else (call venv\Scripts\activate.bat)) && (if not exist .env (copy .env.example .env)) && set WOLFPACK_DEBUG=true && python main.py"

timeout /t 2 >nul

REM 前端启动 (将来补)
REM start "Wolfpack Frontend (port 5173)" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo   Backend  : http://localhost:8080
echo   API Docs : http://localhost:8080/docs
echo   Health   : http://localhost:8080/healthz
echo   Demo     : http://localhost:8080/demo/game.html
echo.
echo Close the opened window(s) to stop services.
