"""SSE 实时事件流.

GET /games/{game_id}/stream
  - 第一步: 从 SQLite 回放该局当前已有的所有 events (按 seq 顺序)
  - 第二步: 订阅这局的 EventBus 拿后续实时事件 (publish 进来的)
  - 对局结束 → bus 关闭 → 自动 yield stream_end

前端只要 EventSource('/games/42/stream') 就能拿到从开局到结束的完整事件流.
"""

import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import game as crud
from app.infra.db import get_db
from app.infra.event_bus import get_bus


router = APIRouter(prefix="/games", tags=["stream"])


SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",   # 关掉中间反代缓冲
}


def _sse(data: dict) -> str:
    """把 dict 包成 SSE 帧."""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get(
    "/{game_id}/stream",
    summary="对局事件流 (SSE): 先回放历史 + 接续实时",
)
async def stream_game(
    game_id: int,
    channel: Optional[str] = Query(
        None,
        description="只推该 channel 的事件 (board / wolf_chat / lovers)",
    ),
    db: AsyncSession = Depends(get_db),
):
    game = await crud.get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")

    channels_filter = [channel] if channel else None
    initial_events = await crud.list_events(db, game_id, channels=channels_filter)

    # 取一次状态: 已结束的局只回放历史不订阅 bus
    is_terminal = game.status in ("ended", "aborted")
    bus = None if is_terminal else get_bus(f"game:{game_id}")

    async def generate() -> AsyncIterator[str]:
        # 1. 回放历史
        for ev in initial_events:
            yield _sse({
                "seq": ev.seq,
                "channel": ev.channel,
                "kind": ev.kind,
                "round": ev.round,
                "payload": ev.payload,
            })

        if is_terminal:
            yield _sse({"kind": "stream_end", "reason": "already_ended"})
            return

        # 2. 订阅 bus 拿后续
        assert bus is not None
        queue = bus.subscribe()
        try:
            while True:
                event = await queue.get()
                if event is None:
                    yield _sse({"kind": "stream_end", "reason": "game_over"})
                    break
                # 客户端指定 channel 过滤
                if channel and event.get("channel") != channel:
                    continue
                yield _sse(event)
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
