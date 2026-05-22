"""后台任务: 跑完一整局. 复用给 start_game (新开局) + lifespan (resume 续跑)."""

from __future__ import annotations

from loguru import logger

from app.core.game_runtime import GameRuntime
from app.core.judge import play_game
from app.crud import game as crud
from app.infra.db import AsyncSessionLocal
from app.infra.event_bus import drop_bus


async def run_game_async(game_id: int, runtime: GameRuntime, max_rounds: int) -> None:
    """跑完一整局并落终态. start_game 跟 resume 都用同一个入口.

    出口:
      - 正常结束: 同步死亡到 game_player + mark_ended
      - 异常: mark_aborted
      - 无论 finally: bus.publish(None) 收尾 SSE + drop_bus 释放订阅
    """
    logger.info(f"[game {game_id}] 开始跑, max_rounds={max_rounds}")
    try:
        result = await play_game(
            runtime.god, runtime.state, max_rounds=max_rounds
        )

        async with AsyncSessionLocal() as db:
            game = await crud.get_game(db, game_id)
            if game is not None:
                for p in runtime.state.players:
                    if not p.alive:
                        await crud.kill_player(
                            db,
                            game_id,
                            p.player_id,
                            round_num=p.died_at_round or 0,
                            cause=p.death_cause or "unknown",
                        )
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
                await crud.mark_aborted(db, game, error=str(e))
    finally:
        runtime.bus.publish(None)
        drop_bus(f"game:{game_id}")
