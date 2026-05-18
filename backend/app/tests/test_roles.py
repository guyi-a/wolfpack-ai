"""Villager / Seer roles 测试.

跑法:
    python app/tests/test_roles.py

验证目标:
  1. Villager 多轮发言 (verify Role 继承链通)
  2. Seer 调 check_player 工具 -> 工具结果回写 history
  3. 第二轮 Seer 能看到自己上轮的查验记录 (history 跨轮工具记忆)
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager


MODEL = "deepseek/deepseek-v4-pro"


def dump_history(player, label: str):
    print(f"\n--- history of {player.player_id} ({label}) ---")
    for i, e in enumerate(player.history()):
        bits = [f"role={e.role}"]
        if e.text:
            bits.append(f"text={e.text[:80]!r}")
        if e.thinking:
            bits.append(f"thinking({len(e.thinking)} 字符)")
        if e.tool_calls:
            simplified = [(tc.get("name"), tc.get("args")) for tc in e.tool_calls]
            bits.append(f"tool_calls={simplified}")
        if e.tool_call_id:
            bits.append(f"tool_call_id={e.tool_call_id[:16]}...")
        if e.name:
            bits.append(f"name={e.name}")
        print(f"  [{i}] " + "  ".join(bits))


def test_villager():
    print("=" * 72)
    print("场景 1 — Villager 多轮发言")
    print("=" * 72)
    store = InMemoryHistoryStore()
    v = Villager(player_id="p3_villager", model_name=MODEL, history_store=store)

    r1 = v.act("现在是第 1 天白天, 请你作为 3 号玩家做一段开场发言.")
    print(f"\n[发言1] {r1}")
    r2 = v.act(
        "5 号玩家刚才跳预言家, 自报昨晚查 1 号是狼. "
        "现在轮到你 (3 号) 接着发言, 请基于这个信息表态."
    )
    print(f"\n[发言2] {r2}")
    dump_history(v, "Villager")


def test_seer():
    print("\n" + "=" * 72)
    print("场景 2 — Seer 调 check_player 工具 + 工具结果回写 + 跨轮记忆")
    print("=" * 72)
    identities = {
        "1": "wolf",
        "2": "good",
        "4": "wolf",
        "5": "good",
        "6": "good",
    }
    store = InMemoryHistoryStore()
    s = Seer(
        player_id="p3_seer",
        model_name=MODEL,
        history_store=store,
        identities=identities,
    )

    r1 = s.act("现在是第 1 天夜晚, 你是 3 号预言家, 请查验 1 号玩家.")
    print(f"\n[夜1 action] {r1}")
    r2 = s.act("现在是第 2 天夜晚, 请查验 4 号玩家.")
    print(f"\n[夜2 action] {r2}")
    r3 = s.act(
        "现在是第 2 天白天发言, 请总结你这两晚查验的信息, "
        "然后给出你认为最可能是狼人的玩家编号."
    )
    print(f"\n[白2 发言] {r3}")
    dump_history(s, "Seer")

    h = s.history()
    tool_call_entries = [e for e in h if e.tool_calls]
    tool_result_entries = [e for e in h if e.role == "tool"]
    print(f"\n[校验] tool_call 数 = {len(tool_call_entries)} (应 ≥ 2)")
    print(f"[校验] tool_result 数 = {len(tool_result_entries)} (应 ≥ 2)")


def main():
    test_villager()
    test_seer()


if __name__ == "__main__":
    main()
