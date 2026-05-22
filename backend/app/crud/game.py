"""Game / GamePlayer / GameEvent 的 CRUD 操作.

routers 层只调用这里, 不直接写 SQLAlchemy. 便于:
  - 业务规则集中 (e.g. create_game 必同时建好所有 game_player 行)
  - 测试时 mock
"""

import datetime as dt
from typing import Optional, Sequence

from sqlalchemy import delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.game import (
    Game,
    GameEvent,
    GamePlayer,
    PlayerPrivateHistory,
    RuntimeSnapshot,
)
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
    await db.execute(
        delete(RuntimeSnapshot).where(RuntimeSnapshot.game_id == game.id)
    )
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
    await db.execute(
        delete(RuntimeSnapshot).where(RuntimeSnapshot.game_id == game.id)
    )
    await db.commit()


async def delete_game(db: AsyncSession, game_id: int) -> int:
    """硬删一局: game 行 + 级联 game_player / game_event / player_private_history / runtime_snapshot
    (FK ondelete='CASCADE' 兜底). 返回删除的 game 行数 (0 或 1)."""
    result = await db.execute(delete(Game).where(Game.id == game_id))
    await db.commit()
    return result.rowcount or 0


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


async def append_private_history(
    db: AsyncSession,
    game_id: int,
    player_id: str,
    entries: list,
    start_seq: int,
) -> int:
    """单个 player 增量追加 history (act 结束后调用).

    Args:
        start_seq: 此次追加的第一条 seq (调用方维护 per-player 计数)
    Returns:
        追加的行数.
    """
    if not entries:
        return 0
    rows = [
        PlayerPrivateHistory(
            game_id=game_id,
            player_id=player_id,
            seq=start_seq + i,
            role=e.role,
            text=e.text,
            thinking=e.thinking,
            tool_calls=e.tool_calls,
            tool_call_id=e.tool_call_id,
            name=e.name,
            round=e.round,
        )
        for i, e in enumerate(entries)
    ]
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


# ============================================================================
# 统计聚合
# ============================================================================


async def fetch_stats_rows(
    db: AsyncSession,
) -> tuple[list[Game], list[tuple[int, str, str]]]:
    """拉取统计所需原始数据.

    Returns:
        (all_games, player_rows)
          all_games: 所有 Game 行 (含 pending/running)
          player_rows: 所有 game_player 的 (game_id, role, model) 元组
    """
    games_result = await db.execute(select(Game))
    games = list(games_result.scalars().all())

    p_stmt = select(GamePlayer.game_id, GamePlayer.role, GamePlayer.model)
    p_result = await db.execute(p_stmt)
    player_rows = [(int(gid), str(role), str(model)) for gid, role, model in p_result.all()]
    return games, player_rows


# ============================================================================
# RuntimeSnapshot — 断点续跑
# ============================================================================


async def upsert_snapshot(
    db: AsyncSession,
    game_id: int,
    *,
    round: int,
    phase: str,
    night_actions: dict,
    eliminated_today: Optional[str],
    deaths_announced_today: list[str],
    potion_states: dict,
    last_event_seq: int,
    last_history_seqs: dict[str, int],
    last_phase_name: str,
) -> None:
    """覆盖式写入 (每局只有一行, game_id 是 PK).

    用 ORM 先 select 再 update / insert, SQLite 没有 ON CONFLICT 的便捷 SQLA 高层 API.
    """
    existing = await db.get(RuntimeSnapshot, game_id)
    if existing is None:
        existing = RuntimeSnapshot(game_id=game_id)
        db.add(existing)
    existing.round = round
    existing.phase = phase
    existing.night_actions = night_actions
    existing.eliminated_today = eliminated_today
    existing.deaths_announced_today = list(deaths_announced_today)
    existing.potion_states = dict(potion_states)
    existing.last_event_seq = last_event_seq
    existing.last_history_seqs = dict(last_history_seqs)
    existing.last_phase_name = last_phase_name
    existing.updated_at = _utcnow()
    await db.commit()


async def load_snapshot(
    db: AsyncSession, game_id: int
) -> Optional[RuntimeSnapshot]:
    return await db.get(RuntimeSnapshot, game_id)


async def delete_snapshot(db: AsyncSession, game_id: int) -> None:
    await db.execute(delete(RuntimeSnapshot).where(RuntimeSnapshot.game_id == game_id))
    await db.commit()


# ============================================================================
# Restore 用: 删除超过 snapshot 高水位的脏行
# ============================================================================


async def delete_events_after_seq(
    db: AsyncSession, game_id: int, last_seq: int
) -> int:
    """删除 game_event 里 seq > last_seq 的行 (restore 时清理脏数据)."""
    result = await db.execute(
        delete(GameEvent).where(
            GameEvent.game_id == game_id, GameEvent.seq > last_seq
        )
    )
    await db.commit()
    return result.rowcount or 0


async def delete_history_after_seq(
    db: AsyncSession,
    game_id: int,
    player_id: str,
    last_seq_count: int,
) -> int:
    """删除某 player 的 private_history 里 seq >= last_seq_count 的行.

    Note: 我们的 history seq 从 0 开始计数, last_seq_count 是"已保留的行数",
    所以是 seq >= count (而非 > count).
    """
    result = await db.execute(
        delete(PlayerPrivateHistory).where(
            PlayerPrivateHistory.game_id == game_id,
            PlayerPrivateHistory.player_id == player_id,
            PlayerPrivateHistory.seq >= last_seq_count,
        )
    )
    await db.commit()
    return result.rowcount or 0
