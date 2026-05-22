"""设置接口 — Anthropic 协议接入凭据.

  GET  /settings       拿当前 api_key / base_url (api_key 明文回, 前端 password 输入框遮蔽)
  PUT  /settings       覆盖更新, 写入同时把 os.environ 也更新, 让正在跑的 llm_factory 立刻拿到新值
"""

import os

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import settings as crud
from app.infra.db import get_db
from app.schemas.settings import AppSettingsOut, AppSettingsUpdate


router = APIRouter(prefix="/settings", tags=["settings"])


def _sync_env(api_key: str, base_url: str) -> None:
    """同步到 os.environ — llm_factory 每次 get_chat_model 时读 env.

    空字符串显式 pop 掉 (而不是 set 空), 否则 get_chat_model 拿到 "" 还以为是没配.
    """
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key
    else:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    if base_url:
        os.environ["ANTHROPIC_BASE_URL"] = base_url
    else:
        os.environ.pop("ANTHROPIC_BASE_URL", None)


@router.get("", response_model=AppSettingsOut, summary="读取当前应用设置")
async def get_app_settings(db: AsyncSession = Depends(get_db)) -> AppSettingsOut:
    row = await crud.get_settings(db)
    return AppSettingsOut.model_validate(row)


@router.put("", response_model=AppSettingsOut, summary="更新应用设置")
async def update_app_settings(
    body: AppSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> AppSettingsOut:
    row = await crud.update_settings(
        db,
        anthropic_api_key=body.anthropic_api_key,
        anthropic_base_url=body.anthropic_base_url,
    )
    _sync_env(row.anthropic_api_key, row.anthropic_base_url)
    return AppSettingsOut.model_validate(row)
