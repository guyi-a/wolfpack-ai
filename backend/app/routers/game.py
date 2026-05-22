"""Game CRUD HTTP 接口.

MVP endpoints:
  POST   /games                     — 开一局, 入参 GameConfig, 返 GameDetail
  POST   /games/{id}/start          — 启动这局 (后台跑 LLM, 立即返回)
  GET    /games                     — 列出最近的对局 (摘要)
  GET    /games/{game_id}           — 单局详情, 含 players
  GET    /games/{game_id}/events    — 按 seq 拿事件流 (复盘用)
  GET    /games/{game_id}/export    — 一键导出整局 (JSON / Markdown), 用于分享 + 离线复盘

SSE 实时流单独在 app/routers/stream.py.
"""

import json
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import Response
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.game_runner import run_game_async
from app.core.game_runtime import build_runtime
from app.agent.infra.llm_factory import CredentialsMissingError
from app.crud import game as crud
from app.infra.db import get_db
from app.schemas.game import (
    GameConfig,
    GameDetail,
    GameEventOut,
    GameStatsOut,
    GameSummary,
    PlayerOut,
    PrivateHistoryEntryOut,
    PrivateHistoryOut,
    StatsByModel,
    StatsByModelRole,
    StatsByRole,
)
from app.utils.markdown_export import render_markdown


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

    # 把 max_rounds 落到 config_json, 给 resume 用 (后续 server 重启接着跑时要拿).
    game.config_json = {**(game.config_json or {}), "max_rounds": max_rounds}

    # 构造 runtime (会从 SQLite 拉配置, 实例化 player/god, 挂 sinks)
    try:
        runtime = await build_runtime(game_id)
    except CredentialsMissingError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await crud.mark_started(db, game)

    background_tasks.add_task(run_game_async, game_id, runtime, max_rounds)
    return {"status": "running", "game_id": game_id}


@router.delete(
    "/{game_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="硬删一局 (含 events / players / 私有 history / snapshot). running 状态拒绝. "
            "胜率统计 (/stats) 是实时算的, 删完下次拉自动反映, 后端不用额外清理.",
)
async def delete_game(
    game_id: int,
    db: AsyncSession = Depends(get_db),
) -> Response:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    if game.status == "running":
        raise HTTPException(
            status_code=400,
            detail=f"game {game_id} 正在运行, 请先停止再删除",
        )
    await crud.delete_game(db, game_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    "/stats",
    response_model=GameStatsOut,
    summary="对局聚合统计 (Home 用): 胜率/角色/模型矩阵",
)
async def get_stats(db: AsyncSession = Depends(get_db)) -> GameStatsOut:
    games, player_rows = await crud.fetch_stats_rows(db)

    total = len(games)
    ended = [g for g in games if g.status == "ended" and g.winner is not None]
    aborted = sum(1 for g in games if g.status == "aborted")
    good_wins = sum(1 for g in ended if g.winner == "good")
    wolf_wins = sum(1 for g in ended if g.winner == "wolf")
    avg_rounds = (
        sum(g.rounds_played for g in ended) / len(ended) if ended else 0.0
    )

    winner_by_game: dict[int, str] = {g.id: g.winner for g in ended}  # type: ignore[misc]

    # 只聚合已结束有胜负的局
    role_acc: dict[str, dict[str, int]] = {}            # role -> {wins,total}
    model_acc: dict[str, dict[str, int]] = {}           # model -> {wins,total}
    mr_acc: dict[tuple[str, str], dict[str, int]] = {}  # (model,role) -> {wins,total}

    for game_id, role, model in player_rows:
        winner = winner_by_game.get(game_id)
        if winner is None:
            continue
        is_wolf = role == "wolf"
        won = (winner == "wolf" and is_wolf) or (winner == "good" and not is_wolf)

        for acc, key in (
            (role_acc, role),
            (model_acc, model),
            (mr_acc, (model, role)),
        ):
            bucket = acc.setdefault(key, {"wins": 0, "total": 0})  # type: ignore[arg-type]
            bucket["total"] += 1
            if won:
                bucket["wins"] += 1

    return GameStatsOut(
        total_games=total,
        ended_games=len(ended),
        good_wins=good_wins,
        wolf_wins=wolf_wins,
        aborted=aborted,
        avg_rounds=round(avg_rounds, 2),
        by_role=[
            StatsByRole(role=r, total=v["total"], wins=v["wins"])  # type: ignore[arg-type]
            for r, v in sorted(role_acc.items())
        ],
        by_model=[
            StatsByModel(model=m, total=v["total"], wins=v["wins"])
            for m, v in sorted(model_acc.items(), key=lambda kv: -kv[1]["total"])
        ],
        by_model_role=[
            StatsByModelRole(model=m, role=r, total=v["total"], wins=v["wins"])  # type: ignore[arg-type]
            for (m, r), v in sorted(mr_acc.items())
        ],
    )


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


@router.get(
    "/{game_id}/export",
    summary="导出一局完整对局 (json 全量 / markdown 人读). 走附件下载.",
)
async def export_game(
    game_id: int,
    format: Literal["json", "markdown"] = Query("json"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    await db.refresh(game, attribute_names=["players"])
    events = await crud.list_events(db, game_id)
    histories_orm = await crud.list_all_private_histories(db, game_id)

    filename_base = f"wolfpack-game-{game_id}"

    if format == "markdown":
        body = render_markdown(game, game.players, events, histories_orm)
        return Response(
            content=body,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.md"',
            },
        )

    # JSON 全量 (含 events + histories), 适合做交换格式
    payload = {
        "game": GameDetail(
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
        ).model_dump(mode="json"),
        "events": [
            GameEventOut.model_validate(e).model_dump(mode="json")
            for e in events
        ],
        "histories": [
            PrivateHistoryOut(
                player_id=pid,
                entries=[PrivateHistoryEntryOut.model_validate(e) for e in entries],
            ).model_dump(mode="json")
            for pid, entries in histories_orm.items()
        ],
    }
    body_json = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        content=body_json,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.json"',
        },
    )
