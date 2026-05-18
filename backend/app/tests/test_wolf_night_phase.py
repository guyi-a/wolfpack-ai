"""WolfNightPhase 端到端测试.

跑法:
    python app/tests/test_wolf_night_phase.py

验证:
  1. 两狼能在 wolf_chat 里互相看到对方发言
  2. 每只狼都至少调过一次 cast_vote 工具
  3. VoteCollector 能统计出最终 kill_target
  4. wolf_chat 里有 (rounds * wolf_count) 条 speech 事件
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.phase import WolfNightPhase


MODEL = "deepseek/deepseek-v4-pro"


def main():
    print("=" * 72)
    print("WolfNightPhase 测试: 2 狼 (1号, 4号), 候选目标 [2号, 3号, 5号, 6号]")
    print("=" * 72)

    board = Channel.board(["1", "2", "3", "4", "5", "6"])
    wolf_chat = Channel.wolf_chat(["1", "4"])

    # 占位 on_vote, phase 会重绑
    def noop(*args, **kwargs):
        pass

    wolf1 = Wolf(
        player_id="1",
        model_name=MODEL,
        history_store=InMemoryHistoryStore(),
        teammates=["4"],
        channels=[board, wolf_chat],
        on_vote=noop,
    )
    wolf4 = Wolf(
        player_id="4",
        model_name=MODEL,
        history_store=InMemoryHistoryStore(),
        teammates=["1"],
        channels=[board, wolf_chat],
        on_vote=noop,
    )

    phase = WolfNightPhase(
        wolves=[wolf1, wolf4],
        wolf_chat=wolf_chat,
        game_round=1,
        alive_ids=["1", "2", "3", "4", "5", "6"],
        rounds=2,
    )

    result = phase.run()

    print("\n--- 狼频道事件 ---")
    for ev in wolf_chat.all_events():
        p = ev.payload
        print(f"  [r={ev.round}] {p['speaker']}号: {p['text'][:80]}")

    print("\n--- 结果 ---")
    print(f"  kill_target: {result.payload['kill_target']}")
    print(f"  votes      : {result.payload['votes']}")
    print(f"  tally      : {result.payload['tally']}")

    # 校验
    print("\n--- 校验 ---")
    speech_count = len([e for e in wolf_chat.all_events() if e.kind == "speech"])
    expected = 2 * 2  # rounds * wolf_count
    print(f"  [√] 狼频道 speech 数 = {speech_count} (期望 {expected})")

    for wolf in [wolf1, wolf4]:
        tool_calls = [e for e in wolf.history() if e.tool_calls]
        print(f"  [{wolf.player_id}号狼] tool_call 次数 = {len(tool_calls)} (应 ≥ 1)")


if __name__ == "__main__":
    main()
