"""Game CRUD HTTP 接口.

MVP endpoints:
  POST   /games                     — 开一局, 入参 GameConfig, 返 GameDetail
  POST   /games/{id}/start          — 启动这局 (后台跑 LLM, 立即返回)
  GET    /games                     — 列出最近的对局 (摘要)
  GET    /games/{game_id}           — 单局详情, 含 players
  GET    /games/{game_id}/events    — 按 seq 拿事件流 (复盘用)

SSE 实时流单独在 app/routers/stream.py.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.game_runtime import build_runtime
from app.core.judge import play_game
from app.crud import game as crud
from app.infra.db import AsyncSessionLocal, get_db
from app.infra.event_bus import drop_bus
from app.schemas.game import (
    GameConfig,
    GameDetail,
    GameEventOut,
    GameSummary,
    PlayerOut,
    PrivateHistoryEntryOut,
    PrivateHistoryOut,
)


router = APIRouter(prefix="/games", tags=["games"])


def _detail_from_orm(game) -> GameDetail:
    """ORM Game (含 .players 关联) → GameDetail. 显式重组, 避免懒加载."""
    return GameDetail(
        id=game.id,
        status=game.status,
        winner=game.winner,
        rounds_played=game.rounds_played,
        god_model=game.god_model,
        created_at=game.created_at,
        started_at=game.started_at,
        ended_at=game.ended_at,
        config_json=game.config_json,
        error_message=game.error_message,
        players=[PlayerOut.model_validate(p) for p in game.players],
    )


@router.post(
    "",
    response_model=GameDetail,
    status_code=status.HTTP_201_CREATED,
    summary="开一局新对局 (status=pending, 还没真正跑)",
)
async def create_game(
    config: GameConfig,
    db: AsyncSession = Depends(get_db),
) -> GameDetail:
    game = await crud.create_game(db, config)
    await db.refresh(game, attribute_names=["players"])
    return _detail_from_orm(game)


@router.post(
    "/{game_id}/start",
    status_code=status.HTTP_202_ACCEPTED,
    summary="启动这局 (后台异步跑 LLM, 立即返回)",
)
async def start_game(
    game_id: int,
    background_tasks: BackgroundTasks,
    max_rounds: int = Query(8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> dict:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    if game.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"game {game_id} status={game.status!r}, 不能 start",
        )

    # 构造 runtime (会从 SQLite 拉配置, 实例化 player/god, 挂 sinks)
    runtime = await build_runtime(game_id)
    await crud.mark_started(db, game)

    background_tasks.add_task(_run_game_async, game_id, runtime, max_rounds)
    return {"status": "running", "game_id": game_id}


async def _run_game_async(game_id: int, runtime, max_rounds: int) -> None:
    """后台任务: 跑完整局, 跑完后 mark_ended / mark_aborted."""
    logger.info(f"[game {game_id}] 开始跑, max_rounds={max_rounds}")
    try:
        result = await play_game(
            runtime.god, runtime.state, max_rounds=max_rounds
        )

        async with AsyncSessionLocal() as db:
            game = await crud.get_game(db, game_id)
            if game is not None:
                # 1. 同步死亡到 game_player
                for p in runtime.state.players:
                    if not p.alive:
                        await crud.kill_player(
                            db,
                            game_id,
                            p.player_id,
                            round_num=p.died_at_round or 0,
                            cause=p.death_cause or "unknown",
                        )
                # 2. 归档每个 player + god 的私有 history
                histories = _collect_histories(runtime)
                rows = await crud.archive_private_histories(db, game_id, histories)
                logger.info(f"[game {game_id}] 归档 private history {rows} 行")
                # 3. mark_ended
                await crud.mark_ended(
                    db, game,
                    winner=result["winner"],
                    rounds_played=result["rounds_played"],
                )
        logger.info(f"[game {game_id}] 结束: winner={result['winner']}")
    except Exception as e:
        logger.exception(f"[game {game_id}] 异常退出")
        async with AsyncSessionLocal() as db:
            game = await crud.get_game(db, game_id)
            if game is not None:
                # 异常退出也归档已有的 history (复盘异常局)
                try:
                    histories = _collect_histories(runtime)
                    await crud.archive_private_histories(db, game_id, histories)
                except Exception:
                    logger.exception(f"[game {game_id}] 归档失败 (异常退出路径)")
                await crud.mark_aborted(db, game, error=str(e))
    finally:
        runtime.bus.publish(None)
        drop_bus(f"game:{game_id}")


def _collect_histories(runtime) -> dict:
    """从 runtime 收集 player + god 的私有 history. 输出 {player_id: list[HistoryEntry]}."""
    out: dict[str, list] = {}
    for pid, player in runtime.players.items():
        out[pid] = player.history()
    out["god"] = runtime.god.history()
    return out


@router.get(
    "",
    response_model=list[GameSummary],
    summary="列出最近的对局摘要",
)
async def list_games(
    limit: int = Query(50, ge=1, le=200),
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="按状态过滤: pending / running / ended / aborted",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[GameSummary]:
    games = await crud.list_games(db, limit=limit, status=status_filter)
    return [GameSummary.model_validate(g) for g in games]


@router.get(
    "/{game_id}",
    response_model=GameDetail,
    summary="单局详情, 含玩家清单",
)
async def get_game(
    game_id: int,
    db: AsyncSession = Depends(get_db),
) -> GameDetail:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    await db.refresh(game, attribute_names=["players"])
    return _detail_from_orm(game)


@router.get(
    "/{game_id}/events",
    response_model=list[GameEventOut],
    summary="拿对局事件流 (用于复盘)",
)
async def list_events(
    game_id: int,
    channel: Optional[str] = Query(
        None,
        description="可选过滤: board / wolf_chat / lovers",
    ),
    db: AsyncSession = Depends(get_db),
) -> list[GameEventOut]:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    channels = [channel] if channel else None
    events = await crud.list_events(db, game_id, channels=channels)
    return [GameEventOut.model_validate(e) for e in events]


@router.get(
    "/{game_id}/players/{player_id}/history",
    response_model=PrivateHistoryOut,
    summary="拿某 player 的私有 history (内心戏复盘)",
)
async def get_player_history(
    game_id: int,
    player_id: str,
    db: AsyncSession = Depends(get_db),
) -> PrivateHistoryOut:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    entries = await crud.list_private_history(db, game_id, player_id)
    return PrivateHistoryOut(
        player_id=player_id,
        entries=[PrivateHistoryEntryOut.model_validate(e) for e in entries],
    )


@router.get(
    "/{game_id}/histories",
    response_model=list[PrivateHistoryOut],
    summary="拿该局所有 player 的私有 history (上帝复盘)",
)
async def get_all_histories(
    game_id: int,
    db: AsyncSession = Depends(get_db),
) -> list[PrivateHistoryOut]:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    histories = await crud.list_all_private_histories(db, game_id)
    return [
        PrivateHistoryOut(
            player_id=pid,
            entries=[PrivateHistoryEntryOut.model_validate(e) for e in entries],
        )
        for pid, entries in histories.items()
    ]
