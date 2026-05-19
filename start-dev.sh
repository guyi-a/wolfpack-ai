#!/bin/bash
# Wolfpack 开发模式一键启动
# 用法: ./start-dev.sh

set -e

cd "$(dirname "$0")"

echo "🐺 启动 Wolfpack 开发环境"
echo ""

# ── 后端 ──────────────────────────────────────────────────────────────
echo "📡 启动后端 (FastAPI, 端口 8080)..."
cd backend

# venv 没建就自动建
if [ ! -d "venv" ]; then
  echo "  → 检测到 venv 不存在, 自动创建并安装依赖..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
else
  source venv/bin/activate
fi

# .env 没建就拷
if [ ! -f ".env" ]; then
  echo "  → .env 不存在, 从 .env.example 复制 (记得填 API key)..."
  cp .env.example .env
fi

# 起后端 (热重载)
WOLFPACK_DEBUG=true python main.py &
BACKEND_PID=$!
cd ..

sleep 2

# ── 前端 (将来补) ─────────────────────────────────────────────────────
# echo "🎨 启动前端 (Vite, 端口 5173)..."
# cd frontend
# npm run dev &
# FRONTEND_PID=$!
# cd ..

echo ""
echo "✅ Wolfpack 已启动"
echo ""
echo "  🔧 后端 API   : http://localhost:8080"
echo "  📖 API 文档   : http://localhost:8080/docs"
echo "  💚 健康检查   : http://localhost:8080/healthz"
echo "  🎨 视觉 demo  : http://localhost:8080/demo/game.html"
echo ""
echo "  按 Ctrl+C 停止所有服务"

trap "echo ''; echo '⏹  停止服务...'; kill $BACKEND_PID 2>/dev/null || true; exit" INT TERM
wait
