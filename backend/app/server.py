"""Wolfpack FastAPI 入口.

跑法:
    cd backend
    uvicorn app.server:app --reload --port 8080

或者 (开发):
    venv/bin/python -m uvicorn app.server:app --reload --port 8080

后续 Electron Main 在 spawn 时也是同一个命令 (打包后换成 Nuitka binary).
端口 8080 留给后端, 前端 Vite 默认 5173 不冲突.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.infra.settings import settings
from app.routers import game, health, meta, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时做基础初始化, 关闭时清理. schema migration 走 alembic, 不在这里 create_all."""
    settings.ensure_dirs()
    logger.info(f"Wolfpack 启动 — db={settings.db_path}, port={settings.port}")
    yield
    logger.info("Wolfpack 关闭")


app = FastAPI(
    title="Wolfpack",
    description="AI 狼人杀 — 多智能体协作与博弈",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — 桌面 app 只听 loopback, 前端 (Vite dev server / Electron Renderer) 跨域允通
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由注册
app.include_router(health.router, tags=["system"])
app.include_router(meta.router)
app.include_router(game.router)
app.include_router(stream.router)
