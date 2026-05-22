"""设置接口的入参出参 schemas.

GET /settings 直接回明文 api_key (前端 input 默认 type=password 隐藏);
PUT /settings 覆盖式更新两个字段.
"""

import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field


class AppSettingsOut(BaseModel):
    """GET /settings 返回. api_key 明文 — 前端用 password 输入框遮蔽."""

    anthropic_api_key: str
    anthropic_base_url: str
    updated_at: Optional[dt.datetime] = None

    class Config:
        from_attributes = True


class AppSettingsUpdate(BaseModel):
    """PUT /settings 入参. 两个字段都可选, 仅传的字段会覆盖."""

    anthropic_api_key: Optional[str] = Field(
        default=None, description="留空表示不改"
    )
    anthropic_base_url: Optional[str] = Field(
        default=None, description="留空表示不改"
    )
