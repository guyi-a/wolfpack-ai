"""Alembic 启动脚本.

跟标准模板比, 我们改了两点:
  1. database URL 从 app.infra.settings 读取 (不在 alembic.ini 里写死)
  2. target_metadata 来自 app.infra.db.Base.metadata
     (这样 alembic revision --autogenerate 能感知到 models/ 下所有表)
"""

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# 让 alembic env.py 能 import app.*
# (alembic CLI 在 backend/ 下跑, prepend_sys_path=. 已经把 backend/ 加进来了, 这里再保险加一次)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.infra.db import Base       # noqa: E402
from app.infra.settings import settings   # noqa: E402

# 导入所有 models 让 Base.metadata 注册它们 (autogenerate 才能比对到)
from app import models   # noqa: E402, F401


config = context.config

# 注入 database URL (替代 ini 里的 sqlalchemy.url)
config.set_main_option("sqlalchemy.url", settings.database_url)

# 启用日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# autogenerate 的对照源
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """offline: 只打印 SQL, 不真连数据库."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """online async: 真连数据库执行 migration."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
