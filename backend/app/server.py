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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select

from app.infra.db import AsyncSessionLocal
from app.infra.settings import settings
from app.models.game import Game
from app.routers import game, health, meta, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时做基础初始化, 关闭时清理. schema migration 走 alembic, 不在这里 create_all."""
    settings.ensure_dirs()

    # 兜底: 上次进程死掉留下的 status='running' 是僵尸局, 全部标 aborted.
    # 真正的"断点续跑"是大工程 (见 CLAUDE.md "故障恢复"), MVP 先用这个清理.
    async with AsyncSessionLocal() as db:
        stale = await db.execute(select(Game).where(Game.status == "running"))
        sweeped = 0
        for g in stale.scalars().all():
            g.status = "aborted"
            g.error_message = "server_restart"
            g.ended_at = datetime.now(timezone.utc)
            sweeped += 1
        if sweeped:
            await db.commit()
            logger.warning(f"启动 sweep: {sweeped} 个僵尸 game 已标 aborted")

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

# 静态 demo (开发期视觉调性预览, 不参与 production 路径)
_DEMO_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "frontend-demo"
if _DEMO_DIR.exists():
    app.mount("/demo", StaticFiles(directory=str(_DEMO_DIR), html=True), name="demo")
