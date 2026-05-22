#!/bin/bash
# Wolfpack 开发模式一键启动 — 后端 + 前端 + Electron 三进程
# 用法: ./start-dev.sh
# 选项:
#   --no-electron  只起 backend + frontend, 浏览器自己开 http://localhost:5173
#   --no-frontend  只起 backend (调后端接口用)

set -e

cd "$(dirname "$0")"

WITH_FRONTEND=1
WITH_ELECTRON=1
for arg in "$@"; do
  case "$arg" in
    --no-electron) WITH_ELECTRON=0 ;;
    --no-frontend) WITH_FRONTEND=0; WITH_ELECTRON=0 ;;
  esac
done

echo "🐺 启动 Wolfpack 开发环境"
echo ""

PIDS=()

cleanup() {
  echo ""
  echo "⏹  停止所有服务..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  exit
}
trap cleanup INT TERM

# ── 后端 ──────────────────────────────────────────────────────────────
echo "📡 启动后端 (FastAPI, 端口 8080)..."
pushd backend > /dev/null

if [ ! -d "venv" ]; then
  echo "  → 检测到 venv 不存在, 自动创建并安装依赖..."
  python3 -m venv venv
  source venv/bin/activate
  pip install -q --upgrade pip
  pip install -q -r requirements.txt
else
  source venv/bin/activate
fi

# .env 兜底; key 也可以走前端「设置」页填到 SQLite
if [ ! -f ".env" ]; then
  echo "  → .env 不存在, 从 .env.example 复制 (可后续在「设置」页填 key)..."
  cp .env.example .env
fi

WOLFPACK_DEBUG=true python main.py &
PIDS+=($!)
popd > /dev/null

# 等后端 /healthz 就绪
until curl -sf http://127.0.0.1:8080/healthz >/dev/null 2>&1; do
  sleep 0.5
done
echo "  ✓ 后端就绪"

# ── 前端 ──────────────────────────────────────────────────────────────
if [ "$WITH_FRONTEND" = "1" ]; then
  echo "🎨 启动前端 (Vite, 端口 5173)..."
  pushd frontend > /dev/null
  if [ ! -d "node_modules" ]; then
    echo "  → node_modules 不存在, 自动 pnpm install..."
    pnpm install --silent
  fi
  # 前缀打 [frontend] 方便跟 backend 输出区分
  pnpm dev 2>&1 | sed -u 's/^/[frontend] /' &
  PIDS+=($!)
  popd > /dev/null

  # 等前端 5173 ready (Vite 起得快但首次 transform 可能 5-10s)
  echo "  ⏳ 等待 http://127.0.0.1:5173 ..."
  for i in $(seq 1 60); do
    if curl -sf http://127.0.0.1:5173 >/dev/null 2>&1; then
      echo "  ✓ 前端就绪"
      break
    fi
    sleep 0.5
    if [ "$i" = "60" ]; then
      echo "  ⚠ 30s 仍未就绪, 看上面 [frontend] 输出排查"
    fi
  done
fi

# ── Electron ──────────────────────────────────────────────────────────
if [ "$WITH_ELECTRON" = "1" ]; then
  echo "🪟 启动 Electron 窗口 (加载 http://localhost:5173)..."
  pushd electron > /dev/null
  if [ ! -d "node_modules" ]; then
    echo "  → node_modules 不存在, 自动 pnpm install..."
    pnpm install --silent
  fi
  pnpm start 2>&1 | sed -u 's/^/[electron] /' &
  PIDS+=($!)
  popd > /dev/null
fi

echo ""
echo "✅ Wolfpack 已启动"
echo ""
echo "  🔧 后端 API   : http://localhost:8080"
echo "  📖 API 文档   : http://localhost:8080/docs"
if [ "$WITH_FRONTEND" = "1" ]; then
  echo "  🎨 前端       : http://localhost:5173"
fi
if [ "$WITH_ELECTRON" = "1" ]; then
  echo "  🪟 Electron   : 已弹出独立窗口"
fi
echo ""
echo "  首次启动请前往「设置」页填 API key (齿轮按钮)"
echo "  按 Ctrl+C 停止所有服务"
echo ""

wait