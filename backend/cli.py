"""Wolfpack 命令行入口.

跑法:
    python -m backend.cli
    python -m backend.cli --model pa/claude-opus-4-7
    python -m backend.cli --max-rounds 10

或者直接:
    python backend/cli.py
"""

import argparse
import sys
import time
from pathlib import Path

# 兼容 `python backend/cli.py` 和 `python -m backend.cli` 两种跑法
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.god import God, GodContext
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.game_state import GameState, PlayerInfo
from app.core.judge import play_game


# 6 人板默认配置
DEFAULT_LAYOUT = [
    ("1", "wolf"),
    ("2", "witch"),
    ("3", "seer"),
    ("4", "wolf"),
    ("5", "villager"),
    ("6", "villager"),
]


def noop(*args, **kwargs):
    pass


def setup_game(model: str):
    players_info = [PlayerInfo(pid, role) for pid, role in DEFAULT_LAYOUT]
    state = GameState(players=players_info)
    board = Channel.board([p.player_id for p in players_info])
    wolf_chat = Channel.wolf_chat([p.player_id for p in players_info if p.role == "wolf"])
    identities = {p.player_id: ("wolf" if p.role == "wolf" else "good") for p in players_info}

    players = {}
    for pid, role in DEFAULT_LAYOUT:
        if role == "wolf":
            teammates = [other for other, r in DEFAULT_LAYOUT if r == "wolf" and other != pid]
            players[pid] = Wolf(
                pid, model, InMemoryHistoryStore(),
                teammates=teammates, channels=[wolf_chat, board], on_vote=noop,
            )
        elif role == "witch":
            players[pid] = Witch(
                pid, model, InMemoryHistoryStore(), channels=[board], on_potion=noop,
            )
        elif role == "seer":
            players[pid] = Seer(
                pid, model, InMemoryHistoryStore(), identities=identities, channels=[board],
            )
        else:
            players[pid] = Villager(pid, model, InMemoryHistoryStore(), channels=[board])

    ctx = GodContext(state=state, board=board, wolf_chat=wolf_chat, players=players)
    god = God("god", model, InMemoryHistoryStore(), ctx=ctx)
    return god, state, board, wolf_chat, players


def render_board(board: Channel) -> None:
    """按时间顺序打印 board 全部事件 (人类可读格式)."""
    print()
    print("=" * 76)
    print("                          对 局 回 放 (board)")
    print("=" * 76)
    last_round = -1
    for e in board.all_events():
        if e.round != last_round:
            print(f"\n────────── 第 {e.round} 轮 ──────────")
            last_round = e.round
        p = e.payload
        if e.kind == "night_result":
            deaths = p["deaths"]
            if deaths:
                who = "、".join(f"{d}号" for d in deaths)
                print(f"  🌑 夜公告: {who} 死亡")
            else:
                print(f"  🌑 夜公告: 平安夜, 无人死亡")
        elif e.kind == "last_words":
            reason = "🌒 夜死" if p["reason"] == "killed_at_night" else "⚰️ 票出"
            print(f"  {reason} 遗言 [{p['speaker']}号]: {p['text']}")
        elif e.kind == "speech":
            print(f"  💬 [{p['speaker']}号]: {p['text']}")
        elif e.kind == "vote":
            print(f"     🗳️  {p['voter']}号 → {p['target']}号")
        elif e.kind == "vote_result":
            ab = p.get("abstentions") or []
            ab_str = f", 弃权 {ab}" if ab else ""
            if p["loser"]:
                print(f"  📊 投票结果: {p['loser']}号 出局  票数 {p['tally']}{ab_str}")
            else:
                print(f"  📊 投票结果: 平票, 无人出局  票数 {p['tally']}{ab_str}")
        elif e.kind == "game_end":
            print(f"\n  🏁 对局结束: {p['winner']} 方胜利!\n")


def render_wolf_chat(wolf_chat: Channel) -> None:
    """单独打印狼频道, 复盘狼套路."""
    events = [e for e in wolf_chat.all_events() if e.kind == "speech"]
    if not events:
        return
    print()
    print("=" * 76)
    print("                       狼频道私聊 (wolf_chat)")
    print("=" * 76)
    last_round = -1
    for e in events:
        if e.round != last_round:
            print(f"\n────────── 第 {e.round} 夜 ──────────")
            last_round = e.round
        print(f"  🐺 [{e.payload['speaker']}号]: {e.payload['text']}")


def main():
    parser = argparse.ArgumentParser(
        description="Wolfpack — 跑一局狼人杀 (6 人板默认)",
    )
    parser.add_argument(
        "--model",
        default="deepseek/deepseek-v4-pro",
        help="所有玩家共用的 LLM (默认: deepseek-v4-pro)",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=8,
        help="最大轮数兜底, 防 LLM 卡死 (默认 8)",
    )
    parser.add_argument(
        "--hide-wolf-chat",
        action="store_true",
        help="不在最后打印狼频道 (默认会打印, 方便复盘)",
    )
    args = parser.parse_args()

    print("=" * 76)
    print("              W O L F P A C K   ·   AI 狼人杀")
    print("=" * 76)
    print(f"  模型     : {args.model}")
    print(f"  最大轮数 : {args.max_rounds}")
    print(f"  桌面     : {DEFAULT_LAYOUT}")
    print("=" * 76)
    print("\n开始跑 . . . (一局大约 30~60 次 LLM 调用, 请耐心等待)\n")

    god, state, board, wolf_chat, _players = setup_game(args.model)

    t0 = time.time()
    result = play_game(god, state, max_rounds=args.max_rounds)
    elapsed = time.time() - t0

    render_board(board)
    if not args.hide_wolf_chat:
        render_wolf_chat(wolf_chat)

    print()
    print("=" * 76)
    print(f"  结束: winner={result['winner']}, "
          f"轮数={result['rounds_played']}, "
          f"耗时={elapsed:.1f}s")
    print("=" * 76)


if __name__ == "__main__":
    main()
