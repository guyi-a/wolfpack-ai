#!/usr/bin/env bash
#
# 用 Nuitka 把 backend 打包成单文件 binary `wolfpack-server`.
#
# 跑法 (必须先 activate venv):
#   source backend/venv/bin/activate
#   bash backend/scripts/build_binary.sh
#
# 产物: backend/build-dist/wolfpack-server (Mac arm64/x86_64 视当前机)
#
# 第一次跑要 5-10 分钟 + 数 GB 内存. Nuitka 会下载一个 C 编译器 cache 之类.
# 后续可装 ccache (brew install ccache) 加速.

set -euo pipefail

cd "$(dirname "$0")/.."   # cd backend/

# 输出目录
OUT_DIR="build-dist"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

# 关键说明:
# --onefile               单 binary, 启动时自解压到 tmp/wolfpack-server.XXX
# --standalone            包含所有依赖 (onefile 隐含 standalone)
# --follow-imports        静态跟踪 import (默认就开, 显式写一遍)
# --output-filename       产物名
# --output-dir            产物目录
# --assume-yes-for-downloads  Nuitka 首次跑可能下 C 编译器/cache, 同意
# --include-package       打进去整个包 (用于 lazy import 抓不到的)
# --include-package-data  打包的 data files (templates / *.json / *.yaml)
# --nofollow-import-to    显式排除不需要的, 减小体积
#
# 必须 include 的重型框架 (lazy import 多):
#   langchain / langchain_core / langchain_anthropic / langgraph
#   sqlalchemy / alembic (data: versions/)
#   pydantic / pydantic_settings
#   uvicorn / fastapi
#   loguru / dotenv
#
# app 本身用 --include-package=app 一次性打进去 (动态 import 路由等)

python -m nuitka \
  --onefile \
  --standalone \
  --static-libpython=no \
  --assume-yes-for-downloads \
  --output-filename=wolfpack-server \
  --output-dir="$OUT_DIR" \
  --include-package=app \
  --include-package-data=app \
  --include-package=langchain \
  --include-package=langchain_core \
  --include-package=langchain_anthropic \
  --include-package=langgraph \
  --include-package=sqlalchemy \
  --include-package=aiosqlite \
  --include-package=alembic \
  --include-package-data=alembic \
  --include-package=uvicorn \
  --include-package=fastapi \
  --include-package=pydantic \
  --include-package=pydantic_settings \
  --include-package=loguru \
  --include-package=dotenv \
  --include-package=anthropic \
  --include-package=httpx \
  --include-package=sse_starlette \
  main.py

echo ""
echo "✅ build done: $OUT_DIR/wolfpack-server"
ls -lh "$OUT_DIR/wolfpack-server"
