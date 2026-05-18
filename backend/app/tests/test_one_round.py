"""6 人板 1 轮端到端测试 (Channel 抽象).

桌面: 2 狼 + 1 预言家 + 1 女巫 + 2 村民.
本测试只跑 "夜间狼刀 + 预言家查验 → 白天公告 + 每人 1 句发言" 这半轮.

跑法:
    python app/tests/test_one_round.py

验证目标:
  1. board channel 公开事件完整, 顺序正确
  2. 每个 player 私有 history 只含自己的 thinking
  3. 预言家私有 history 含 check_player 工具调用, 别人看不到
  4. 别的 player 能在自己 messages 里看到对手的公开发言
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.core.channel import Channel
from app.core.game_state import GameState, PlayerInfo


MODEL = "deepseek/deepseek-v4-pro"


def setup_game() -> tuple[GameState, Channel]:
    """6 人桌面: 1=wolf, 2=witch, 3=seer, 4=wolf, 5=villager, 6=villager."""
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
    return state, board


def main():
    state, board = setup_game()
    print("=" * 72)
    print(f"6 人板初始: {[(p.player_id, p.role) for p in state.players]}")
    print("=" * 72)

    # ---------- 第 1 夜 ----------
    state.start_round()
    print(f"\n--- 第 {state.round} 夜 ---")

    state.night_actions.wolf_kill_target = "5"

    identities = {p.player_id: ("wolf" if p.role == "wolf" else "good") for p in state.players}
    seer = Seer(
        player_id="3",
        model_name=MODEL,
        history_store=InMemoryHistoryStore(),
        identities=identities,
        channels=[board],
    )
    seer_action = seer.act("现在是第 1 夜, 你是预言家 3 号. 请查验 1 号玩家.")
    print(f"  [Seer 私有] {seer_action[:120]}")

    deaths = state.settle_night()
    board.append_night_result(state.round, deaths)
    print(f"  [夜间结算] 死亡: {deaths}, 当前 phase: {state.phase.value}")

    # ---------- 第 1 天 发言 ----------
    print(f"\n--- 第 {state.round} 天 发言 ---")
    print(f"  (5 号是否已死: {'5' not in state.alive_ids()})")

    villagers: dict[str, Villager] = {}
    for pid in state.alive_ids():
        if pid == "3":
            continue
        villagers[pid] = Villager(
            player_id=pid,
            model_name=MODEL,
            history_store=InMemoryHistoryStore(),
            channels=[board],
        )

    for pid in state.alive_ids():
        speaker = seer if pid == "3" else villagers[pid]
        task = (
            f"现在是第 {state.round} 天白天, 你是 {pid} 号. "
            f"昨晚死亡情况已经在公开记录里. "
            f"请用一句话发言, 不超过 30 字."
        )
        speech = speaker.act(task)
        board.append_speech(state.round, pid, speech)
        print(f"  [{pid}号] {speech}")

    # ---------- 校验 ----------
    print("\n" + "=" * 72)
    print("校验")
    print("=" * 72)

    expected_speech_count = len(state.alive_ids())
    speech_events = [e for e in board.all_events() if e.kind == "speech"]
    print(f"  [√] board 公开发言数 = {len(speech_events)} (预期 {expected_speech_count})")

    seer_h = seer.history()
    seer_tool_calls = [e for e in seer_h if e.tool_calls]
    print(f"  [√] Seer 私有 tool_call 数 = {len(seer_tool_calls)} (应 ≥ 1)")

    for pid, p in villagers.items():
        h = p.history()
        has_tool = any(e.tool_calls or e.role == "tool" for e in h)
        print(f"  [{pid}号 私有] 是否含工具调用: {has_tool} (应=False)")

    sample = next(iter(villagers.values()))
    sample_id = sample.player_id
    msgs = sample._build_messages("(检测用任务)")
    public_in_msgs = [m for m in msgs if hasattr(m, "content")
                      and isinstance(m.content, str)
                      and m.content.startswith("[第")]
    print(f"\n  [{sample_id}号] 拼接后 messages 含公开事件 {len(public_in_msgs)} 条:")
    for m in public_in_msgs:
        print(f"     · {m.content[:60]}{'…' if len(m.content) > 60 else ''}")

    def has_thinking_block(msgs) -> bool:
        for m in msgs:
            c = getattr(m, "content", None)
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        return True
        return False
    print(f"  [{sample_id}号] messages 是否含 thinking block: "
          f"{has_thinking_block(msgs)} (默认应=False)")


if __name__ == "__main__":
    main()
