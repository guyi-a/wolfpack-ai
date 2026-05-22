"""断点续跑 — snapshot/restore 测试.

不调真 LLM. 手工创建一局 game, build_runtime 拿到 runtime, 直接操纵 state +
channels 模拟"phase 跑完", 调 runtime.snapshot, 然后 restore_runtime 重建,
断言两者等价.

跑法:
    cd backend && source venv/bin/activate
    python app/tests/test_resume.py

测试用真实 dev DB (wolfpack-data/wolfpack.db), 每个测试自建/自删一个 game,
不污染历史数据.

覆盖:
  1. test_snapshot_roundtrip — 跑 3 个 phase + snapshot, restore 后所有状态一致
  2. test_resume_after_partial_phase — snapshot 后再写脏 event/history,
     restore 时按 last_event_seq / last_history_seqs 清回干净状态
"""

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import delete, select

from app.agent.contexts.history import HistoryEntry
from app.agent.roles.witch import Witch
from app.core.channel import ChannelEvent
from app.core.game_runtime import build_runtime, restore_runtime
from app.core.game_state import Phase
from app.crud import game as crud
from app.infra.db import AsyncSessionLocal
from app.models.game import Game, GameEvent, PlayerPrivateHistory, RuntimeSnapshot
from app.schemas.game import GameConfig, PlayerConfig


MODEL = "deepseek/deepseek-v4-pro"


def _make_config() -> GameConfig:
    """6 人板. 不真跑 LLM, model 名字只是塞进 DB 用."""
    return GameConfig(
        god_model=MODEL,
        players=[
            PlayerConfig(player_id="1", role="wolf", model=MODEL),
            PlayerConfig(player_id="2", role="witch", model=MODEL),
            PlayerConfig(player_id="3", role="seer", model=MODEL),
            PlayerConfig(player_id="4", role="wolf", model=MODEL),
            PlayerConfig(player_id="5", role="villager", model=MODEL),
            PlayerConfig(player_id="6", role="villager", model=MODEL),
        ],
    )


async def _new_game() -> int:
    async with AsyncSessionLocal() as db:
        game = await crud.create_game(db, _make_config())
        await crud.mark_started(db, game)
        return game.id


async def _drop_game(game_id: int) -> None:
    """测试 cleanup. CASCADE FK 会连带删 game_player / game_event /
    runtime_snapshot / player_private_history."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Game).where(Game.id == game_id))
        await db.commit()


# ---------------------------------------------------------------------------
# 模拟 act 增量落库 (不调 LLM, 手工塞 history)
# ---------------------------------------------------------------------------


async def _append_history_via_sink(
    runtime, player_id: str, entries: list[HistoryEntry]
) -> None:
    """直接调 runtime 持有的 history_sink (跟真 act 走同样路径)."""
    # build_runtime 给每个 player 注入了 on_act_finished hook
    # 但这里我们要触发"已经写好的 sink"; runtime 没暴露 sink 引用,
    # 所以走 player.on_act_finished 也行 (它就是 history_sink)
    player = runtime.players.get(player_id) if player_id != "god" else runtime.god
    assert player is not None and player.on_act_finished is not None
    # 同步到 InMemoryHistoryStore (act 也是这么做的)
    for e in entries:
        player.history_store.append(player_id, e)
    await player.on_act_finished(player_id, entries)


# ---------------------------------------------------------------------------
# test 1: snapshot_roundtrip
# ---------------------------------------------------------------------------


async def test_snapshot_roundtrip() -> None:
    print("=" * 76)
    print("test_snapshot_roundtrip")
    print("=" * 76)

    game_id = await _new_game()
    print(f"  game_id = {game_id}")

    runtime = await build_runtime(game_id)

    # --- 模拟 round 1: wolf_night ---
    runtime.state.start_round()            # round=1, phase=NIGHT
    runtime.board.append_phase_change(1, "night_start")
    runtime.board.append_phase_change(1, "wolf_night")
    runtime.wolf_chat.append_speech(1, "1", "刀 5 号.")
    runtime.wolf_chat.append_speech(1, "4", "同意.")
    runtime.state.night_actions.wolf_kill_target = "5"
    await _append_history_via_sink(
        runtime, "1",
        [HistoryEntry(role="user", text="第1夜狼商量", round=1),
         HistoryEntry(role="assistant", text="刀 5 号", thinking="位置中等", round=1)]
    )
    await runtime.snapshot(last_phase="wolf_night")

    # --- 模拟 witch_night ---
    runtime.board.append_phase_change(1, "witch_night")
    # 女巫不救
    runtime.state.night_actions.witch_save = False
    # 消耗一瓶毒药 (改 potion_state)
    witch = runtime.players["2"]
    assert isinstance(witch, Witch)
    witch.potion_state.poison_available = False
    runtime.state.night_actions.witch_poison_target = "6"
    await _append_history_via_sink(
        runtime, "2",
        [HistoryEntry(role="user", text="第1夜女巫决策", round=1),
         HistoryEntry(role="assistant", text="毒 6 号", round=1)]
    )
    await runtime.snapshot(last_phase="witch_night")

    # --- 模拟 night_announce: settle_night 改 state + 写 board ---
    deaths = runtime.state.settle_night()  # kill 5 + 6, phase=DAY_SPEECH
    runtime.board.append_phase_change(1, "day_start")
    runtime.board.append_phase_change(1, "night_announce")
    runtime.board.append_night_result(1, deaths)
    await runtime.snapshot(last_phase="night_announce")

    # ---- 拿原始 runtime 的 "snapshot 快照" 做对比基准 ----
    src_round = runtime.state.round
    src_phase = runtime.state.phase
    src_alive = sorted(runtime.state.alive_ids())
    src_na = (
        runtime.state.night_actions.wolf_kill_target,
        runtime.state.night_actions.witch_save,
        runtime.state.night_actions.witch_poison_target,
    )
    src_deaths_today = list(runtime.state.deaths_announced_today)
    src_board_events = len(runtime.board.events)
    src_wolf_events = len(runtime.wolf_chat.events)
    src_seq = runtime._seq_counter[0]
    src_history_seqs = dict(runtime._history_seq_counters)
    src_potion = {
        pid: (p.potion_state.save_available, p.potion_state.poison_available)
        for pid, p in runtime.players.items() if isinstance(p, Witch)
    }

    print(f"  原 runtime: round={src_round} phase={src_phase.value} "
          f"alive={src_alive} seq={src_seq} board_events={src_board_events}")

    # ---- restore ----
    restored = await restore_runtime(game_id)

    assert restored.state.round == src_round, "round 不一致"
    assert restored.state.phase == src_phase, f"phase 不一致: {restored.state.phase}"
    assert sorted(restored.state.alive_ids()) == src_alive, \
        f"alive 不一致: {sorted(restored.state.alive_ids())} vs {src_alive}"
    na = restored.state.night_actions
    assert (na.wolf_kill_target, na.witch_save, na.witch_poison_target) == src_na, \
        "night_actions 不一致"
    assert list(restored.state.deaths_announced_today) == src_deaths_today, \
        "deaths_announced_today 不一致"
    assert len(restored.board.events) == src_board_events, "board events 数不一致"
    assert len(restored.wolf_chat.events) == src_wolf_events, "wolf_chat events 数不一致"
    assert restored._seq_counter[0] == src_seq, "seq counter 不一致"
    assert dict(restored._history_seq_counters) == src_history_seqs, \
        "history seq counters 不一致"
    restored_potion = {
        pid: (p.potion_state.save_available, p.potion_state.poison_available)
        for pid, p in restored.players.items() if isinstance(p, Witch)
    }
    assert restored_potion == src_potion, f"potion 不一致: {restored_potion} vs {src_potion}"

    # 私有 history 也要还原
    assert len(restored.players["1"].history()) == len(runtime.players["1"].history())
    assert len(restored.players["2"].history()) == len(runtime.players["2"].history())

    print(f"  ✓ restore 后所有字段一致")

    await _drop_game(game_id)


# ---------------------------------------------------------------------------
# test 2: resume_after_partial_phase
# ---------------------------------------------------------------------------


async def test_resume_after_partial_phase() -> None:
    print("=" * 76)
    print("test_resume_after_partial_phase")
    print("=" * 76)

    game_id = await _new_game()
    print(f"  game_id = {game_id}")

    runtime = await build_runtime(game_id)

    # ---- 跑到 wolf_night 完成 + snapshot ----
    runtime.state.start_round()
    runtime.board.append_phase_change(1, "night_start")
    runtime.board.append_phase_change(1, "wolf_night")
    runtime.wolf_chat.append_speech(1, "1", "刀 5 号.")
    runtime.state.night_actions.wolf_kill_target = "5"
    await _append_history_via_sink(
        runtime, "1",
        [HistoryEntry(role="user", text="task", round=1),
         HistoryEntry(role="assistant", text="刀 5 号", round=1)]
    )
    await runtime.snapshot(last_phase="wolf_night")

    clean_seq = runtime._seq_counter[0]
    clean_history_seqs = dict(runtime._history_seq_counters)
    clean_board_events = len(runtime.board.events)
    clean_wolf_events = len(runtime.wolf_chat.events)
    clean_p1_history = len(runtime.players["1"].history())
    print(f"  snapshot 完: seq={clean_seq} board={clean_board_events} "
          f"wolf_chat={clean_wolf_events} p1_history={clean_p1_history}")

    # ---- 模拟 phase B 中途崩: 手动追加几条脏事件 + 脏 history ----
    # (这些事件本来 sqlite_sink 也会写进 DB, 我们模拟 sink 写完但 snapshot 还没更新)
    runtime.board.append_phase_change(1, "seer_night")
    runtime.board.append_speech(1, "god", "脏数据 1")     # 直接 SQL 也得追加
    # 同时追加一条脏 history
    await _append_history_via_sink(
        runtime, "3",
        [HistoryEntry(role="user", text="查谁", round=1),
         HistoryEntry(role="assistant", text="脏 — 还没完成", round=1)]
    )

    # 确认脏数据进了 DB (channel sink 是 fire-and-forget, 先 flush 等异步写完成)
    await runtime.flush_writes()
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(GameEvent).where(GameEvent.game_id == game_id)
        )
        dirty_events = len(list(res.scalars().all()))
        res2 = await db.execute(
            select(PlayerPrivateHistory).where(
                PlayerPrivateHistory.game_id == game_id,
                PlayerPrivateHistory.player_id == "3",
            )
        )
        dirty_p3_hist = len(list(res2.scalars().all()))
    print(f"  脏数据已落库: events={dirty_events}, p3_history={dirty_p3_hist}")
    assert dirty_events > clean_board_events + clean_wolf_events, "脏 events 没落"
    assert dirty_p3_hist > 0, "脏 history 没落"

    # ---- restore — 应当按 snapshot 高水位切回干净 ----
    restored = await restore_runtime(game_id)

    # board 上脏的 phase_change + speech 应该被清掉
    assert len(restored.board.events) == clean_board_events, \
        f"board 没清干净: {len(restored.board.events)} vs {clean_board_events}"
    assert len(restored.wolf_chat.events) == clean_wolf_events, \
        f"wolf_chat 没清干净: {len(restored.wolf_chat.events)} vs {clean_wolf_events}"
    assert restored._seq_counter[0] == clean_seq, "seq 没重置"
    # p3 (seer) 脏 history 应该被清掉, 回到 0
    assert len(restored.players["3"].history()) == 0, "p3 history 没清干净"
    # p1 (wolf) 干净 history 应该保留
    assert len(restored.players["1"].history()) == clean_p1_history, "p1 history 丢了"
    # phase 还是 wolf_night 完成后的状态
    assert restored.state.night_actions.wolf_kill_target == "5", "night_actions 丢了"

    print(f"  ✓ 脏数据被清干净, 干净数据保留")

    await _drop_game(game_id)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def main():
    await test_snapshot_roundtrip()
    print()
    await test_resume_after_partial_phase()
    print("\n✅ 所有测试通过")


if __name__ == "__main__":
    asyncio.run(main())
