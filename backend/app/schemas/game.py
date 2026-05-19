"""Pydantic schemas — API 边界数据契约.

跟 SQLAlchemy models 区分:
  - models/ = ORM 表结构, 跟数据库直接耦合
  - schemas/ = HTTP 入参出参, 跟前端直接耦合
两者解耦, 表结构改了不一定影响 API, 反之亦然.
"""

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ============================================================================
# 开局配置 (POST /games 入参)
# ============================================================================

Role = Literal["wolf", "seer", "witch", "villager"]


class PlayerConfig(BaseModel):
    """单个 player 的配置."""

    player_id: str = Field(..., description="座位号, e.g. '1' '2'")
    role: Role = Field(..., description="角色")
    model: str = Field(..., description="使用的 LLM 模型 ID")


class GameConfig(BaseModel):
    """开一局所需的全部配置 (POST /games 的 body)."""

    god_model: str = Field(..., description="God 用什么模型")
    players: list[PlayerConfig] = Field(
        ..., min_length=4, description="所有玩家配置, 至少 4 人"
    )

    # 预留扩展字段
    rules: dict[str, Any] = Field(
        default_factory=dict,
        description="可选规则开关 (守卫 / 猎人 / etc), 第一版可空",
    )


# ============================================================================
# 出参 (GET /games / GET /games/{id})
# ============================================================================


class PlayerOut(BaseModel):
    """玩家配置 + 终态返回."""

    player_id: str
    role: Role
    model: str
    alive: bool
    died_at_round: Optional[int]
    death_cause: Optional[str]

    class Config:
        from_attributes = True   # 支持从 ORM 对象构造


class GameSummary(BaseModel):
    """列表用的对局摘要."""

    id: int
    status: str
    winner: Optional[str]
    rounds_played: int
    god_model: str
    created_at: dt.datetime
    started_at: Optional[dt.datetime]
    ended_at: Optional[dt.datetime]

    class Config:
        from_attributes = True


class GameDetail(GameSummary):
    """详情包含 player 列表 + config_json."""

    config_json: dict[str, Any]
    error_message: Optional[str]
    players: list[PlayerOut]

    class Config:
        from_attributes = True


# ============================================================================
# 事件
# ============================================================================


class GameEventOut(BaseModel):
    """对局公开事件 (复盘 / SSE 推前端都用这个 shape)."""

    seq: int
    channel: str
    kind: str
    round: int
    payload: dict[str, Any]
    created_at: dt.datetime

    class Config:
        from_attributes = True


class PrivateHistoryEntryOut(BaseModel):
    """player 私有 history 一条 (复盘"内心戏"展示用)."""

    seq: int
    role: str
    text: str
    thinking: str
    tool_calls: list[Any]
    tool_call_id: str
    name: str
    round: int

    class Config:
        from_attributes = True


class PrivateHistoryOut(BaseModel):
    """某 player 的完整私有 history."""

    player_id: str
    entries: list[PrivateHistoryEntryOut]
