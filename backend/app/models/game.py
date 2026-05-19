"""SQLAlchemy 表定义 — 对局相关.

四张表:
  - game                    : 对局元信息 (config snapshot, 状态, 胜负, 时间)
  - game_player             : 每个 player 的配置 + 终态 (model, role, 存亡)
  - game_event              : 所有公开事件 (board/wolf_chat 全部 ChannelEvent 落盘, 用于复盘 + 评测)
  - player_private_history  : 对局结束时归档每个 player (含 god) 的私有 history (thinking + 工具调用), 复盘内心戏用
"""

import datetime as dt
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Game(Base):
    """一局对局的元信息."""

    __tablename__ = "game"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 生命周期状态: pending(已建未开) / running / ended / aborted
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    winner: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    rounds_played: Mapped[int] = mapped_column(Integer, default=0)

    # 关键模型抽出来方便聚合查询 (其他细节都在 config_json)
    god_model: Mapped[str] = mapped_column(String(64))

    # 完整配置 snapshot, 一次写定不再改
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 时间戳
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.current_timestamp()
    )
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ended_at: Mapped[Optional[dt.datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 异常退出时写, 正常结束为 null
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 关联
    players: Mapped[list["GamePlayer"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        order_by="GamePlayer.player_id",
    )
    events: Mapped[list["GameEvent"]] = relationship(
        back_populates="game",
        cascade="all, delete-orphan",
        order_by="GameEvent.seq",
    )


class GamePlayer(Base):
    """每个 player 的配置 + 终态. 一局 6 个 player → 6 行."""

    __tablename__ = "game_player"
    __table_args__ = (
        UniqueConstraint("game_id", "player_id", name="uq_game_player_pid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), index=True
    )

    player_id: Mapped[str] = mapped_column(String(8))      # "1" / "2" / ...
    role: Mapped[str] = mapped_column(String(16))          # wolf / seer / witch / villager
    model: Mapped[str] = mapped_column(String(64))         # 这个 player 用的模型

    # 终态 (开局时 alive=True / 其余 None)
    alive: Mapped[bool] = mapped_column(default=True)
    died_at_round: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    death_cause: Mapped[Optional[str]] = mapped_column(
        String(32), nullable=True
    )  # killed_at_night / voted_out / poisoned

    game: Mapped["Game"] = relationship(back_populates="players")


class GameEvent(Base):
    """对局事件流. 一条事件一行, 按 seq 排序就是完整回放."""

    __tablename__ = "game_event"
    __table_args__ = (
        Index("ix_game_event_game_seq", "game_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), index=True
    )

    seq: Mapped[int] = mapped_column(Integer)              # 该局内的事件序号 (从 1 开始)
    channel: Mapped[str] = mapped_column(String(16))       # board / wolf_chat / lovers
    kind: Mapped[str] = mapped_column(String(24))          # speech / vote / vote_result / ...
    round: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.current_timestamp()
    )

    game: Mapped["Game"] = relationship(back_populates="events")


class PlayerPrivateHistory(Base):
    """对局结束时归档的"player 私有 LLM messages 流".

    一行 = 内存里一条 HistoryEntry 的 SQLite 副本.
    包括 thinking + tool_calls + tool_result + text.
    player_id 同时承担 player 和 god ("1"/"2".../"god").

    MVP: 仅在对局正常结束时 (mark_ended) 一次性 batch insert.
    """

    __tablename__ = "player_private_history"
    __table_args__ = (
        Index("ix_pph_game_player_seq", "game_id", "player_id", "seq"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    game_id: Mapped[int] = mapped_column(
        ForeignKey("game.id", ondelete="CASCADE"), index=True
    )

    player_id: Mapped[str] = mapped_column(String(16))         # "1"/"2".../"god"
    seq: Mapped[int] = mapped_column(Integer)                  # 该 player 内的顺序 (从 0 开始)
    role: Mapped[str] = mapped_column(String(16))              # system/user/assistant/tool
    text: Mapped[str] = mapped_column(Text, default="")
    thinking: Mapped[str] = mapped_column(Text, default="")
    tool_calls: Mapped[list[Any]] = mapped_column(JSON, default=list)
    tool_call_id: Mapped[str] = mapped_column(String(64), default="")
    name: Mapped[str] = mapped_column(String(32), default="")  # role=tool 时的工具名
    round: Mapped[int] = mapped_column(Integer, default=0)
