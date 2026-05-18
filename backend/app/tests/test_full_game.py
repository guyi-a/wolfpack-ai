"""完整对局端到端测试 — God 主持 1 局狼人杀直到胜负.

桌面: 2 狼 (1, 4) + 1 女巫 (2) + 1 预言家 (3) + 2 村民 (5, 6).
God 通过 run_phase 工具按 prompt 调度顺序跑完所有 phase.

跑法:
    python app/tests/test_full_game.py
注意: 这个会调几十次 LLM, 跑几分钟.

验证:
  1. play_game 正常返回 (winner 不为 None)
  2. board 收到完整事件流: night_result + last_words + speech + vote + vote_result + game_end
  3. 各 player 私有 history 仍互不交叉
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.god import God, GodContext
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.game_state import GameState, PlayerInfo
from app.core.judge import play_game


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


def build_players(board, wolf_chat, identities) -> dict:
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

    ctx = GodContext(state=state, board=board, wolf_chat=wolf_chat, players=players)
    god = God(
        player_id="god",
        model_name=MODEL,
        history_store=InMemoryHistoryStore(),
        ctx=ctx,
    )

    print("=" * 76)
    print("Wolfpack 完整对局 — God 主持")
    print(f"配置: {[(p.player_id, p.role) for p in state.players]}")
    print("=" * 76)

    result = play_game(god, state, max_rounds=8)

    print("\n" + "=" * 76)
    print(f"对局结束: winner={result['winner']}, rounds={result['rounds_played']}, "
          f"normal={result['ended_normally']}, iters={result['iterations']}")
    print("=" * 76)

    # ----- board 摘要 -----
    print(f"\n--- board 事件 (共 {len(board.all_events())} 条) ---")
    for e in board.all_events():
        p = e.payload
        if e.kind == "speech":
            print(f"  [r{e.round}] 发言 {p['speaker']}号: {p['text'][:60]}")
        elif e.kind == "last_words":
            reason = "夜死" if p["reason"] == "killed_at_night" else "票出"
            print(f"  [r{e.round}] 遗言({reason}) {p['speaker']}号: {p['text'][:60]}")
        elif e.kind == "vote":
            print(f"  [r{e.round}] 投票 {p['voter']}->{p['target']}")
        elif e.kind == "vote_result":
            ab = p.get("abstentions") or []
            print(f"  [r{e.round}] 票果: loser={p['loser']}, tally={p['tally']}, abstain={ab}")
        elif e.kind == "night_result":
            print(f"  [r{e.round}] 夜公告: deaths={p['deaths']}")
        elif e.kind == "game_end":
            print(f"  [r{e.round}] 🏁 winner={p['winner']}")

    # ----- 私有 history 大小校验 -----
    print(f"\n--- 私有 history 行数 ---")
    print(f"  god       : {len(god.history())}")
    for pid, p in players.items():
        print(f"  {pid}号({state.role_of(pid):8s}): {len(p.history())}")


if __name__ == "__main__":
    main()
