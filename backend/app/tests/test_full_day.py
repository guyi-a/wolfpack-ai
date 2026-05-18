"""完整 1 天端到端测试 (mock 夜结果, 跑白天 4 phase).

桌面: 2 狼 (1, 4) + 1 女巫 (2) + 1 预言家 (3) + 2 村民 (5, 6).
直接 mock "夜里 5 号被刀" 进入白天, 跑:
  NightAnnouncePhase → LastWordsPhase(5号, killed_at_night)
    → DaySpeechPhase → DayVotePhase → LastWordsPhase(被票者, voted_out)

跑法:
    python app/tests/test_full_day.py

验证:
  1. 5 号能留遗言, 写到 board
  2. 所有活人发言写 board (一段)
  3. 所有活人调 cast_vote (一票)
  4. board 收到 N 条 vote + 1 条 vote_result, loser 不为 None
  5. 出局者再留一段遗言 (voted_out)
  6. GameState.alive 正确减少 (5 号 + 出局者)
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.game_state import GameState, PlayerInfo
from app.core.phase import (
    DaySpeechPhase,
    DayVotePhase,
    LastWordsPhase,
    NightAnnouncePhase,
)


MODEL = "deepseek/deepseek-v4-pro"


def noop(*a, **k):
    pass


def setup():
    players = [
        PlayerInfo("1", "wolf"),
        PlayerInfo("2", "witch"),
        PlayerInfo("3", "seer"),
        PlayerInfo("4", "wolf"),
        PlayerInfo("5", "villager"),
        PlayerInfo("6", "villager"),
    ]
    state = GameState(players=players)
    board = Channel.board([p.player_id for p in players])
    wolf_chat = Channel.wolf_chat(["1", "4"])
    identities = {p.player_id: ("wolf" if p.role == "wolf" else "good") for p in players}
    return state, board, wolf_chat, identities


def build_players(board: Channel, wolf_chat: Channel, identities: dict) -> dict:
    """6 个 Player 实例, 按 id 索引返回."""
    return {
        "1": Wolf("1", MODEL, InMemoryHistoryStore(), teammates=["4"], channels=[wolf_chat, board], on_vote=noop),
        "2": Witch("2", MODEL, InMemoryHistoryStore(), channels=[board], on_potion=noop),
        "3": Seer("3", MODEL, InMemoryHistoryStore(), identities=identities, channels=[board]),
        "4": Wolf("4", MODEL, InMemoryHistoryStore(), teammates=["1"], channels=[wolf_chat, board], on_vote=noop),
        "5": Villager("5", MODEL, InMemoryHistoryStore(), channels=[board]),
        "6": Villager("6", MODEL, InMemoryHistoryStore(), channels=[board]),
    }


def main():
    state, board, wolf_chat, identities = setup()
    players = build_players(board, wolf_chat, identities)

    # ---- mock 第 1 夜: 狼刀 5 号, 女巫没救 → 5 死 ----
    state.start_round()
    state.night_actions.wolf_kill_target = "5"
    state.night_actions.witch_save = False
    state.night_actions.witch_poison_target = None

    print("=" * 76)
    print(f"=== 第 {state.round} 天 (mock: 5号 昨晚被狼刀, 女巫没救) ===")
    print("=" * 76)

    # ---- Phase 1: NightAnnounce ----
    print("\n--- NightAnnouncePhase ---")
    nap = NightAnnouncePhase(state=state, board=board).run()
    print(f"  → 死亡: {nap.payload['deaths']}")
    deaths = nap.payload["deaths"]

    # ---- Phase 2: LastWords (夜间死者) ----
    for dead_pid in deaths:
        print(f"\n--- LastWordsPhase ({dead_pid}号 killed_at_night) ---")
        lw = LastWordsPhase(
            dying=players[dead_pid],
            board=board,
            game_round=state.round,
            reason="killed_at_night",
        ).run()
        print(f"  [{dead_pid}号 遗言] {lw.payload['text']}")

    # ---- Phase 3: DaySpeech (活人轮流发言) ----
    print("\n--- DaySpeechPhase ---")
    alive = state.alive_ids()
    speakers = [players[pid] for pid in alive]
    sp = DaySpeechPhase(speakers=speakers, board=board, game_round=state.round).run()
    for pid, text in sp.payload["speeches"]:
        print(f"  [{pid}号] {text}")

    # ---- Phase 4: DayVote ----
    print("\n--- DayVotePhase ---")
    voters = [players[pid] for pid in alive]
    vp = DayVotePhase(
        voters=voters,
        board=board,
        game_round=state.round,
        alive_ids=alive,
    ).run()
    print(f"  votes: {vp.payload['votes']}")
    print(f"  tally: {vp.payload['tally']}")
    print(f"  loser: {vp.payload['loser']}")

    # 把出局结果落到 state
    state.settle_vote(vp.payload["loser"])

    # ---- Phase 5: LastWords (被票出者) ----
    if vp.payload["loser"]:
        loser = vp.payload["loser"]
        print(f"\n--- LastWordsPhase ({loser}号 voted_out) ---")
        lw2 = LastWordsPhase(
            dying=players[loser],
            board=board,
            game_round=state.round,
            reason="voted_out",
        ).run()
        print(f"  [{loser}号 遗言] {lw2.payload['text']}")

    # ---- 校验 ----
    print("\n" + "=" * 76)
    print("校验")
    print("=" * 76)
    print(f"  当前活人: {state.alive_ids()}")
    print(f"  GameState.phase: {state.phase.value}")
    print(f"  board 事件数: {len(board.all_events())}")
    kinds = {}
    for e in board.all_events():
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    print(f"  board 各 kind: {kinds}")


if __name__ == "__main__":
    main()
