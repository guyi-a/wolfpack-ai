"""GameRuntime — 一局对局的运行时上下文工厂.

从 SQLite 里拿对局元信息 (game + game_player), 实例化:
  GameState / Channel(board, wolf_chat) / Player (Wolf/Seer/Witch/Villager) / God

然后给 channels 挂两个 sink:
  - sqlite_sink: 异步落库到 game_event 表
  - bus_sink: 推到这局专属的 EventBus (供 SSE 订阅)

这样 phase 跑业务时只 channel.append, 持久化 + 实时广播自动发生.

另外: GameRuntime 持有 `snapshot(last_phase)` 用于断点续跑. God 每跑完一个
phase 调一次. snapshot 前会 flush 所有 in-flight 的 sqlite 写, 保证落库严格
≤ snapshot 的 last_event_seq.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.agent.base import ActFinishedHook, Player
from app.agent.contexts.history import HistoryEntry
from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.god import God, GodContext
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.agent.roles.witch import PotionState, Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel, ChannelEvent
from app.core.game_state import GameState, NightActions, Phase, PlayerInfo
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
    # in-flight sqlite_sink 写任务, snapshot 前要 await 干净
    _pending_writes: list[asyncio.Task] = field(default_factory=list)
    # per-player history seq 高水位 (= 已落库的行数). 跟 history_sink 共享这同一份 dict.
    _history_seq_counters: dict[str, int] = field(default_factory=dict)

    def next_seq(self) -> int:
        self._seq_counter[0] += 1
        return self._seq_counter[0]

    async def flush_writes(self) -> None:
        """等待所有 in-flight sqlite_sink 写任务完成. snapshot 前必调."""
        if not self._pending_writes:
            return
        pending = [t for t in self._pending_writes if not t.done()]
        self._pending_writes.clear()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def snapshot(self, *, last_phase: str) -> None:
        """Phase 完成后写一次 runtime_snapshot.

        步骤: flush 写队列 → 同步死亡到 game_player → 收集 potion_states → upsert.

        死亡同步到 game_player 是 restore 时恢复 alive 状态的唯一可靠来源 (snapshot
        本身不存 alive). kill_player 幂等, 重复 snapshot 不会出错.
        """
        await self.flush_writes()

        try:
            async with AsyncSessionLocal() as db:
                for p in self.state.players:
                    if not p.alive:
                        await crud.kill_player(
                            db,
                            self.game_id,
                            p.player_id,
                            round_num=p.died_at_round or 0,
                            cause=p.death_cause or "unknown",
                        )
        except Exception:
            logger.exception("snapshot: sync deaths failed (game=%s)", self.game_id)

        potion_states: dict[str, dict] = {}
        for pid, player in self.players.items():
            if isinstance(player, Witch):
                ps = player.potion_state
                potion_states[pid] = {
                    "save_available": ps.save_available,
                    "poison_available": ps.poison_available,
                }
        night_actions = {
            "wolf_kill_target": self.state.night_actions.wolf_kill_target,
            "witch_save": self.state.night_actions.witch_save,
            "witch_poison_target": self.state.night_actions.witch_poison_target,
        }
        try:
            async with AsyncSessionLocal() as db:
                await crud.upsert_snapshot(
                    db,
                    self.game_id,
                    round=self.state.round,
                    phase=self.state.phase.value,
                    night_actions=night_actions,
                    eliminated_today=self.state.eliminated_today,
                    deaths_announced_today=list(self.state.deaths_announced_today),
                    potion_states=potion_states,
                    last_event_seq=self._seq_counter[0],
                    last_history_seqs=dict(self._history_seq_counters),
                    last_phase_name=last_phase,
                )
        except Exception:
            logger.exception("snapshot failed (game=%s phase=%s)", self.game_id, last_phase)


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

    task 会追加到 runtime._pending_writes, snapshot 前 flush 用.
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
            task = loop.create_task(_write())
            runtime._pending_writes.append(task)
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


def _make_history_sink(
    game_id: int, seq_counters: dict[str, int]
) -> ActFinishedHook:
    """增量落库 sink: 每次 player.act() 结束后追加 entries 到 player_private_history.

    seq_counters 是外部传入的共享 dict (放在 runtime._history_seq_counters 上),
    snapshot 时直接读. 保证写入顺序 = act 顺序.
    """
    lock = asyncio.Lock()

    async def sink(player_id: str, entries: list[HistoryEntry]) -> None:
        if not entries:
            return
        async with lock:
            start = seq_counters.get(player_id, 0)
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

    # 4.5 history sink (act 结束增量落库) — counter dict 之后塞给 runtime 共享
    history_seq_counters: dict[str, int] = {}
    history_sink = _make_history_sink(game_id, history_seq_counters)

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

    # 6. God + GodContext (on_phase_done 占位, 等 runtime 建好再注入)
    god_ctx = GodContext(
        state=state, board=board, wolf_chat=wolf_chat, players=players
    )
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
        _history_seq_counters=history_seq_counters,
    )
    runtime_ref = [runtime]
    for ch in (board, wolf_chat):
        ch.add_sink(_make_sqlite_sink(game_id, runtime_ref))
        ch.add_sink(_make_bus_sink(bus, runtime_ref))

    # 8. 注入 phase 完成钩子 (循环引用问题: ctx 持有 runtime.snapshot, runtime 持有 god, god 持有 ctx)
    async def _on_phase_done(phase_name: str) -> None:
        await runtime.snapshot(last_phase=phase_name)

    god_ctx.on_phase_done = _on_phase_done

    return runtime


def _bus_key(game_id: int) -> str:
    return f"game:{game_id}"


# ---------------------------------------------------------------------------
# 断点续跑: 从 SQLite 重建运行时
# ---------------------------------------------------------------------------


async def restore_runtime(game_id: int) -> GameRuntime:
    """从 SQLite 重建一个已跑到一半的 game 的运行时.

    前提: runtime_snapshot 表里有 game_id 对应的快照行.
    流程: build_runtime → 按 snapshot 高水位清理脏行 → 重放事件/history → 恢复
    GameState/PotionState/seq counters → 返回 runtime, 调用方再交给 play_game.
    """
    # 1. 拿 snapshot (没有就报错, 调用方自己处理)
    async with AsyncSessionLocal() as db:
        snap = await crud.load_snapshot(db, game_id)
    if snap is None:
        raise ValueError(f"game {game_id} 没有 runtime_snapshot, 无法 restore")

    # 2. 建一份全新 runtime (空 channel events / 空 history / state.round=0)
    runtime = await build_runtime(game_id)

    # 3. 清理脏数据 — 把高水位之后的行删了 (snapshot 之后到 server 崩之前的部分写)
    #    history 要遍历所有可能的 player_id (含 god): snapshot 里没记录的 pid
    #    意味着 snapshot 时 count=0, 它在 snapshot 之后写的 history 全是脏的, 也要清.
    all_player_ids = list(runtime.players.keys()) + ["god"]
    async with AsyncSessionLocal() as db:
        await crud.delete_events_after_seq(db, game_id, snap.last_event_seq)
        for pid in all_player_ids:
            count = int(snap.last_history_seqs.get(pid, 0) or 0)
            await crud.delete_history_after_seq(db, game_id, pid, count)

    # 4. 重放 game_event 到 channel.events (临时摘掉 sinks, 不要触发二次落库 / 二次 publish)
    async with AsyncSessionLocal() as db:
        events = await crud.list_events(db, game_id)
    channels_by_name = {runtime.board.name: runtime.board, runtime.wolf_chat.name: runtime.wolf_chat}
    for ch in channels_by_name.values():
        saved_sinks = ch.sinks
        ch.sinks = []
        try:
            for ev in events:
                if ev.channel != ch.name:
                    continue
                ch.append(ChannelEvent(kind=ev.kind, round=ev.round, payload=dict(ev.payload)))
        finally:
            ch.sinks = saved_sinks

    # 5. 重放 player_private_history 到 InMemoryHistoryStore
    async with AsyncSessionLocal() as db:
        histories = await crud.list_all_private_histories(db, game_id)
    for pid, rows in histories.items():
        player = runtime.players.get(pid) if pid != "god" else runtime.god
        if player is None:
            logger.warning("restore: 未知 player_id=%s, 跳过 history 重放", pid)
            continue
        for r in rows:
            entry = HistoryEntry(
                role=r.role,
                text=r.text,
                thinking=r.thinking,
                tool_calls=list(r.tool_calls or []),
                tool_call_id=r.tool_call_id or "",
                name=r.name or "",
                round=r.round,
            )
            player.history_store.append(pid, entry)

    # 6. 从 snapshot 重建 GameState 的可变部分
    state = runtime.state
    state.round = snap.round
    state.phase = Phase(snap.phase)
    na = snap.night_actions or {}
    state.night_actions = NightActions(
        wolf_kill_target=na.get("wolf_kill_target"),
        witch_save=bool(na.get("witch_save", False)),
        witch_poison_target=na.get("witch_poison_target"),
    )
    state.eliminated_today = snap.eliminated_today
    state.deaths_announced_today = list(snap.deaths_announced_today or [])

    # 7. 从 game_player 表恢复死亡 (源头是这张表, 跑中 phase 没同步, 但 mark_ended 同步过.
    #    更可靠的还是从 channel events / state.kill 推, 但快照只覆盖快照时点的状态.
    #    保险: 用 game_player 行, 如果 alive=False 则在 state 里也 kill.)
    async with AsyncSessionLocal() as db:
        players_meta = await crud.get_players(db, game_id)
    for pm in players_meta:
        if not pm.alive:
            pi = state.get(pm.player_id)
            pi.alive = False
            pi.died_at_round = pm.died_at_round
            pi.death_cause = pm.death_cause

    # 8. 恢复女巫 PotionState
    for pid, ps_dict in (snap.potion_states or {}).items():
        player = runtime.players.get(pid)
        if isinstance(player, Witch):
            player.potion_state = PotionState(
                save_available=bool(ps_dict.get("save_available", True)),
                poison_available=bool(ps_dict.get("poison_available", True)),
            )

    # 9. 恢复 seq counters
    runtime._seq_counter[0] = snap.last_event_seq
    for pid, count in (snap.last_history_seqs or {}).items():
        runtime._history_seq_counters[pid] = int(count)

    logger.info(
        "restored game=%s round=%s phase=%s last_phase=%s events=%s",
        game_id, state.round, state.phase.value, snap.last_phase_name, snap.last_event_seq,
    )
    return runtime
