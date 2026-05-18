"""SQLAlchemy 2.0 async engine + 会话工厂 + 依赖注入.

桌面 app 单进程, aiosqlite 足够.

schema 演进走 alembic (backend/alembic/), 不在代码里直接 create_all.
开发流程:
  1. 加 model 到 app/models/
  2. cd backend && alembic revision --autogenerate -m "<msg>"
  3. alembic upgrade head

用法:
    from app.infra.db import get_db, Base, engine

    @router.get("/foo")
    async def foo(db: AsyncSession = Depends(get_db)):
        result = await db.execute(...)
        return ...
"""

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.infra.settings import settings


# 启动时确保数据目录存在 (否则 SQLite 创建文件会报 OSError)
settings.ensure_dirs()


# Async engine (单例, 进程级别)
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    connect_args={"check_same_thread": False},  # SQLite 必加
    future=True,
)

# Session 工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """所有 SQLAlchemy 表的基类. models/*.py 里的表都继承它."""
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖注入: 提供一个 AsyncSession, 自动关闭."""
    async with AsyncSessionLocal() as session:
        yield session
