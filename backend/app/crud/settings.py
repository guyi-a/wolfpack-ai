"""AppSettings 的 CRUD. singleton 表 (id=1).

第一次 get_settings 时若不存在则自动建一行默认值.
"""

import datetime as dt
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import AppSettings


_DEFAULT_BASE_URL = "https://api.novita.ai/anthropic"


async def get_settings(db: AsyncSession) -> AppSettings:
    """拿 settings 行. 不存在就建一个默认行 (空 key + novita 默认 base_url)."""
    row = await db.get(AppSettings, 1)
    if row is None:
        # 第一次启动: .env 里有就用 .env 的值兜底, 没有就完全空 / 默认 url
        row = AppSettings(
            id=1,
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            anthropic_base_url=os.environ.get(
                "ANTHROPIC_BASE_URL", _DEFAULT_BASE_URL
            ),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def update_settings(
    db: AsyncSession,
    anthropic_api_key: str | None = None,
    anthropic_base_url: str | None = None,
) -> AppSettings:
    """覆盖式更新 (None 表示不动)."""
    row = await get_settings(db)
    if anthropic_api_key is not None:
        row.anthropic_api_key = anthropic_api_key.strip()
    if anthropic_base_url is not None:
        row.anthropic_base_url = anthropic_base_url.strip() or _DEFAULT_BASE_URL
    row.updated_at = dt.datetime.now(dt.timezone.utc)
    await db.commit()
    await db.refresh(row)
    return row
