"""Pydantic schemas — API 边界数据契约."""

from app.schemas.game import (
    GameConfig,
    GameDetail,
    GameEventOut,
    GameSummary,
    PlayerConfig,
    PlayerOut,
    PrivateHistoryEntryOut,
    PrivateHistoryOut,
    Role,
)

__all__ = [
    "GameConfig",
    "GameDetail",
    "GameEventOut",
    "GameSummary",
    "PlayerConfig",
    "PlayerOut",
    "PrivateHistoryEntryOut",
    "PrivateHistoryOut",
    "Role",
]
