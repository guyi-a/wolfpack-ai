"""GameRuntime — 一局对局的运行时上下文工厂.

从 SQLite 里拿对局元信息 (game + game_player), 实例化:
  GameState / Channel(board, wolf_chat) / Player (Wolf/Seer/Witch/Villager) / God

然后给 channels 挂两个 sink:
  - sqlite_sink: 异步落库到 game_event 表
  - bus_sink: 推到这局专属的 EventBus (供 SSE 订阅)

这样 phase 跑业务时只 channel.append, 持久化 + 实时广播自动发生.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.agent.base import ActFinishedHook, Player
from app.agent.contexts.history import HistoryEntry
from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.god import God, GodContext
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel, ChannelEvent
from app.core.game_state import GameState, PlayerInfo
from app.crud import game as crud
from app.infra.db import AsyncSessionLocal
from app.infra.event_bus import EventBus, get_bus


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Runtime 容器
# ---------------------------------------------------------------------------


@dataclass
class GameRuntime:
    game_id: int
    state: GameState
    board: Channel
    wolf_chat: Channel
    players: dict[str, Player]
    god: God
    bus: EventBus
    _seq_counter: list[int] = field(default_factory=lambda: [0])

    def next_seq(self) -> int:
        self._seq_counter[0] += 1
        return self._seq_counter[0]


# ---------------------------------------------------------------------------
# 构造 runtime
# ---------------------------------------------------------------------------


def _noop(*args, **kwargs):
    pass


def _build_player(
    pid: str,
    role: str,
    model: str,
    *,
    teammates: Sequence[str],
    identities: dict[str, str],
    board: Channel,
    wolf_chat: Channel,
    bus: Optional[EventBus] = None,
    on_act_finished: Optional[ActFinishedHook] = None,
) -> Player:
    store = InMemoryHistoryStore()
    if role == "wolf":
        return Wolf(
            player_id=pid,
            model_name=model,
            history_store=store,
            teammates=teammates,
            channels=[wolf_chat, board],
            on_vote=_noop,
            bus=bus,
            on_act_finished=on_act_finished,
        )
    if role == "witch":
        return Witch(
            player_id=pid,
            model_name=model,
            history_store=store,
            channels=[board],
            on_potion=_noop,
            bus=bus,
            on_act_finished=on_act_finished,
        )
    if role == "seer":
        return Seer(
            player_id=pid,
            model_name=model,
            history_store=store,
            identities=identities,
            channels=[board],
            bus=bus,
            on_act_finished=on_act_finished,
        )
    if role == "villager":
        return Villager(
            player_id=pid,
            model_name=model,
            history_store=store,
            channels=[board],
            bus=bus,
            on_act_finished=on_act_finished,
        )
    raise ValueError(f"未知 role: {role!r}")


def _make_sqlite_sink(game_id: int, runtime_ref: list["GameRuntime"]):
    """SQLite 落库 sink.

    Channel.append 是同步触发, 用 asyncio.create_task fire-and-forget 异步写入.
    seq 在同步入口计算好传进 task, 保证落库顺序 = 调用顺序.
    """

    def sink(channel: Channel, event: ChannelEvent) -> None:
        runtime = runtime_ref[0]
        seq = runtime.next_seq()

        async def _write() -> None:
            try:
                async with AsyncSessionLocal() as db:
                    # 直接插, 不用 append_event 的"查 max seq" 逻辑 (我们自己算了 seq)
                    from app.models.game import GameEvent
                    db.add(
                        GameEvent(
                            game_id=game_id,
                            seq=seq,
                            channel=channel.name,
                            kind=event.kind,
                            round=event.round,
                            payload=event.payload,
                        )
                    )
                    await db.commit()
            except Exception:
                logger.exception("sqlite sink failed (game=%s seq=%s)", game_id, seq)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_write())
        except RuntimeError:
            # 没在 event loop 里跑 (e.g. asyncio.to_thread 的子线程) — 退化成新 loop
            asyncio.run(_write())

    return sink


def _make_bus_sink(bus: EventBus, runtime_ref: list["GameRuntime"]):
    """EventBus publish sink, 推给 SSE 订阅者."""

    def sink(channel: Channel, event: ChannelEvent) -> None:
        runtime = runtime_ref[0]
        # 注意: seq 跟 sqlite sink 共用一个 counter, 顺序与 SQLite 一致
        # 但 bus 是即时的 (不 await), sqlite 是异步的, 实际落库可能稍晚
        bus.publish(
            {
                "game_id": runtime.game_id,
                "seq": runtime._seq_counter[0],  # 跟最近一次 next_seq 一致
                "channel": channel.name,
                "kind": event.kind,
                "round": event.round,
                "payload": event.payload,
            }
        )

    return sink


def _make_history_sink(game_id: int) -> ActFinishedHook:
    """增量落库 sink: 每次 player.act() 结束后追加 entries 到 player_private_history.

    维护 per-player 的 seq counter, 保证写入顺序 = act 顺序.
    """
    seq_counters: dict[str, int] = defaultdict(int)
    lock = asyncio.Lock()

    async def sink(player_id: str, entries: list[HistoryEntry]) -> None:
        if not entries:
            return
        async with lock:
            start = seq_counters[player_id]
            seq_counters[player_id] = start + len(entries)
        try:
            async with AsyncSessionLocal() as db:
                await crud.append_private_history(db, game_id, player_id, entries, start)
        except Exception:
            logger.exception("history sink failed (game=%s player=%s)", game_id, player_id)

    return sink


async def build_runtime(game_id: int) -> GameRuntime:
    """从 SQLite 拉配置, 构造完整 runtime 并挂好 sinks."""
    async with AsyncSessionLocal() as db:
        game = await crud.get_game(db, game_id)
        if game is None:
            raise ValueError(f"game {game_id} not found")
        players_meta = await crud.get_players(db, game_id)

    # 1. PlayerInfo + GameState
    player_infos = [
        PlayerInfo(player_id=p.player_id, role=p.role) for p in players_meta
    ]
    state = GameState(players=player_infos)

    # 2. Channels
    board = Channel.board([p.player_id for p in player_infos])
    wolf_chat = Channel.wolf_chat([p.player_id for p in player_infos if p.role == "wolf"])

    # 3. identities (给 Seer)
    identities = {p.player_id: ("wolf" if p.role == "wolf" else "good") for p in player_infos}

    # 4. EventBus (按 game_id 隔离)
    bus = get_bus(_bus_key(game_id))

    # 4.5 history sink (act 结束增量落库)
    history_sink = _make_history_sink(game_id)

    # 5. 创建 Player 实例
    wolf_ids = [p.player_id for p in player_infos if p.role == "wolf"]
    players: dict[str, Player] = {}
    for pm in players_meta:
        teammates = [w for w in wolf_ids if w != pm.player_id] if pm.role == "wolf" else []
        players[pm.player_id] = _build_player(
            pm.player_id,
            pm.role,
            pm.model,
            teammates=teammates,
            identities=identities,
            board=board,
            wolf_chat=wolf_chat,
            bus=bus,
            on_act_finished=history_sink,
        )

    # 6. God + GodContext
    god_ctx = GodContext(state=state, board=board, wolf_chat=wolf_chat, players=players)
    god = God(
        player_id="god",
        model_name=game.god_model,
        history_store=InMemoryHistoryStore(),
        ctx=god_ctx,
        bus=bus,
        on_act_finished=history_sink,
    )

    # 7. 装 runtime + 挂 sinks
    runtime = GameRuntime(
        game_id=game_id,
        state=state,
        board=board,
        wolf_chat=wolf_chat,
        players=players,
        god=god,
        bus=bus,
    )
    runtime_ref = [runtime]
    for ch in (board, wolf_chat):
        ch.add_sink(_make_sqlite_sink(game_id, runtime_ref))
        ch.add_sink(_make_bus_sink(bus, runtime_ref))

    return runtime


def _bus_key(game_id: int) -> str:
    return f"game:{game_id}"
