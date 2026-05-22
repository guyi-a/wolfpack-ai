"""Wolfpack FastAPI 入口.

跑法:
    cd backend
    uvicorn app.server:app --reload --port 8080

或者 (开发):
    venv/bin/python -m uvicorn app.server:app --reload --port 8080

后续 Electron Main 在 spawn 时也是同一个命令 (打包后换成 Nuitka binary).
端口 8080 留给后端, 前端 Vite 默认 5173 不冲突.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from loguru import logger
from sqlalchemy import select

from app.core.game_runner import run_game_async
from app.core.game_runtime import restore_runtime
from app.crud import game as crud
from app.crud import settings as settings_crud
from app.infra.db import AsyncSessionLocal, Base, engine
from app.infra.settings import settings
from app.models.game import Game
from app.routers import game, health, meta, settings as settings_router, stream


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时做基础初始化, 关闭时清理.

    建表策略: dev 流程是 alembic, 但 Nuitka onefile binary 跑不了 alembic (versions/
    散文件抓不全). 所以 lifespan 直接 create_all 兜底 — 表存在 no-op, 不存在就建.
    dev 跑 alembic upgrade head 之后再起 server 也是 no-op, 互不打架.

    sweep_or_resume: 对所有上次进程死掉留下的 status='running' 的局, 有 snapshot
    就 restore_runtime + 后台接着跑, 没有就标 aborted (太早崩, 无法续).
    """
    settings.ensure_dirs()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 加载持久化的 Anthropic 凭据到 os.environ.
    # 优先级: DB > .env (DB 不空时覆盖 .env, 让设置页修改立刻生效).
    async with AsyncSessionLocal() as db:
        app_settings = await settings_crud.get_settings(db)
    if app_settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = app_settings.anthropic_api_key
    if app_settings.anthropic_base_url:
        os.environ["ANTHROPIC_BASE_URL"] = app_settings.anthropic_base_url
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning("ANTHROPIC_API_KEY 未配置 — 用户首次启动需前往「设置」页填写")

    async with AsyncSessionLocal() as db:
        stale = await db.execute(select(Game).where(Game.status == "running"))
        stale_games = list(stale.scalars().all())

    resumed = 0
    aborted = 0
    for g in stale_games:
        async with AsyncSessionLocal() as db:
            snap = await crud.load_snapshot(db, g.id)
        if snap is None:
            async with AsyncSessionLocal() as db:
                game_row = await crud.get_game(db, g.id)
                if game_row is not None:
                    await crud.mark_aborted(db, game_row, error="server_restart")
            aborted += 1
            continue
        try:
            runtime = await restore_runtime(g.id)
            max_rounds = 8
            if isinstance(g.config_json, dict):
                max_rounds = int(g.config_json.get("max_rounds", 8))
            asyncio.create_task(run_game_async(g.id, runtime, max_rounds))
            resumed += 1
        except Exception:
            logger.exception(f"[game {g.id}] restore failed, mark aborted")
            async with AsyncSessionLocal() as db:
                game_row = await crud.get_game(db, g.id)
                if game_row is not None:
                    await crud.mark_aborted(db, game_row, error="restore_failed")
            aborted += 1

    if resumed or aborted:
        logger.warning(f"启动 sweep: resumed={resumed}, aborted={aborted}")

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
app.include_router(settings_router.router)
app.include_router(game.router)
app.include_router(stream.router)

# 静态 demo (开发期视觉调性预览, 不参与 production 路径)
_DEMO_DIR = Path(__file__).resolve().parent.parent.parent / "examples" / "frontend-demo"
if _DEMO_DIR.exists():
    app.mount("/demo", StaticFiles(directory=str(_DEMO_DIR), html=True), name="demo")
