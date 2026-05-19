"""Game / GamePlayer / GameEvent 的 CRUD 操作.

routers 层只调用这里, 不直接写 SQLAlchemy. 便于:
  - 业务规则集中 (e.g. create_game 必同时建好所有 game_player 行)
  - 测试时 mock
"""

import datetime as dt
from typing import Optional, Sequence

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import Game, GameEvent, GamePlayer, PlayerPrivateHistory
from app.schemas.game import GameConfig


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# ============================================================================
# Game
# ============================================================================


async def create_game(db: AsyncSession, config: GameConfig) -> Game:
    """新建一局 game + 同时建好所有 game_player. status='pending'."""
    game = Game(
        status="pending",
        god_model=config.god_model,
        config_json=config.model_dump(),
        rounds_played=0,
    )
    db.add(game)
    await db.flush()   # 拿 game.id

    for p in config.players:
        db.add(
            GamePlayer(
                game_id=game.id,
                player_id=p.player_id,
                role=p.role,
                model=p.model,
                alive=True,
            )
        )

    await db.commit()
    await db.refresh(game)
    return game


async def get_game(db: AsyncSession, game_id: int) -> Optional[Game]:
    result = await db.execute(select(Game).where(Game.id == game_id))
    return result.scalar_one_or_none()


async def list_games(
    db: AsyncSession,
    limit: int = 50,
    status: Optional[str] = None,
) -> Sequence[Game]:
    stmt = select(Game).order_by(desc(Game.created_at)).limit(limit)
    if status:
        stmt = stmt.where(Game.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


async def mark_started(db: AsyncSession, game: Game) -> None:
    game.status = "running"
    game.started_at = _utcnow()
    await db.commit()


async def mark_ended(
    db: AsyncSession,
    game: Game,
    *,
    winner: Optional[str],
    rounds_played: int,
) -> None:
    game.status = "ended"
    game.winner = winner
    game.rounds_played = rounds_played
    game.ended_at = _utcnow()
    await db.commit()


async def mark_aborted(
    db: AsyncSession,
    game: Game,
    *,
    error: str,
) -> None:
    game.status = "aborted"
    game.error_message = error
    game.ended_at = _utcnow()
    await db.commit()


# ============================================================================
# GamePlayer
# ============================================================================


async def get_players(db: AsyncSession, game_id: int) -> Sequence[GamePlayer]:
    stmt = (
        select(GamePlayer)
        .where(GamePlayer.game_id == game_id)
        .order_by(GamePlayer.player_id)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def kill_player(
    db: AsyncSession,
    game_id: int,
    player_id: str,
    *,
    round_num: int,
    cause: str,
) -> None:
    """标记 player 死亡. cause ∈ {killed_at_night, voted_out, poisoned}."""
    stmt = select(GamePlayer).where(
        GamePlayer.game_id == game_id,
        GamePlayer.player_id == player_id,
    )
    result = await db.execute(stmt)
    player = result.scalar_one_or_none()
    if player is None:
        return
    player.alive = False
    player.died_at_round = round_num
    player.death_cause = cause
    await db.commit()


# ============================================================================
# GameEvent
# ============================================================================


async def append_event(
    db: AsyncSession,
    game_id: int,
    *,
    channel: str,
    kind: str,
    round_num: int,
    payload: dict,
) -> GameEvent:
    """追加一条公开事件. seq 自动 = 当前 max(seq)+1 (按局).

    注意: 一局内并发追加事件会有 seq 竞争, 但我们目前是单线程跑一局, 不会冲突.
    """
    seq_result = await db.execute(
        select(func.coalesce(func.max(GameEvent.seq), 0))
        .where(GameEvent.game_id == game_id)
    )
    next_seq = seq_result.scalar_one() + 1

    event = GameEvent(
        game_id=game_id,
        seq=next_seq,
        channel=channel,
        kind=kind,
        round=round_num,
        payload=payload,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def list_events(
    db: AsyncSession,
    game_id: int,
    *,
    channels: Optional[Sequence[str]] = None,
) -> Sequence[GameEvent]:
    stmt = (
        select(GameEvent)
        .where(GameEvent.game_id == game_id)
        .order_by(GameEvent.seq)
    )
    if channels:
        stmt = stmt.where(GameEvent.channel.in_(channels))
    result = await db.execute(stmt)
    return result.scalars().all()


# ============================================================================
# PlayerPrivateHistory — 私有 LLM messages 归档
# ============================================================================


async def archive_private_histories(
    db: AsyncSession,
    game_id: int,
    histories: dict[str, list],
) -> int:
    """对局结束时, 把所有 player (含 god) 的私有 history dump 到 SQLite.

    Args:
        game_id: 对局 ID
        histories: {player_id: list[HistoryEntry]} (HistoryEntry 见 app/agent/contexts/history.py)

    Returns:
        归档的行数.
    """
    rows: list[PlayerPrivateHistory] = []
    for player_id, entries in histories.items():
        for seq, entry in enumerate(entries):
            rows.append(
                PlayerPrivateHistory(
                    game_id=game_id,
                    player_id=player_id,
                    seq=seq,
                    role=entry.role,
                    text=entry.text,
                    thinking=entry.thinking,
                    tool_calls=entry.tool_calls,
                    tool_call_id=entry.tool_call_id,
                    name=entry.name,
                    round=entry.round,
                )
            )
    if rows:
        db.add_all(rows)
        await db.commit()
    return len(rows)


async def list_private_history(
    db: AsyncSession,
    game_id: int,
    player_id: str,
) -> Sequence[PlayerPrivateHistory]:
    """读出某 player 的归档 history. 按 seq 升序."""
    stmt = (
        select(PlayerPrivateHistory)
        .where(
            PlayerPrivateHistory.game_id == game_id,
            PlayerPrivateHistory.player_id == player_id,
        )
        .order_by(PlayerPrivateHistory.seq)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


async def list_all_private_histories(
    db: AsyncSession,
    game_id: int,
) -> dict[str, list[PlayerPrivateHistory]]:
    """读出该局所有 player 的归档. 返回 {player_id: [...]}."""
    stmt = (
        select(PlayerPrivateHistory)
        .where(PlayerPrivateHistory.game_id == game_id)
        .order_by(PlayerPrivateHistory.player_id, PlayerPrivateHistory.seq)
    )
    result = await db.execute(stmt)
    out: dict[str, list[PlayerPrivateHistory]] = {}
    for row in result.scalars().all():
        out.setdefault(row.player_id, []).append(row)
    return out
