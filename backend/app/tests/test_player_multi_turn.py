"""Player 真实多轮 + 跨模型测试.

跑法:
    python app/tests/test_player_multi_turn.py

验证目标:
  1. 多轮对话: player 能记住上轮内容 (上下文连续)
  2. 跨模型切换: 同一份 history 被 deepseek 写入, claude 也能正常读、继续对话
  3. 信息隔离: 默认对局视角下, 喂给 LLM 的 messages 不包含上轮 thinking
"""

import sys
import asyncio
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.base import Player
from app.agent.contexts.adapters import get_adapter
from app.agent.contexts.history_store import InMemoryHistoryStore


DEEPSEEK = "deepseek/deepseek-v4-pro"
CLAUDE = "pa/claude-opus-4-7"


def dump_history(player: Player, label: str) -> None:
    print(f"\n--- history of {player.player_id} ({label}) ---")
    for i, e in enumerate(player.history()):
        thk = f"  thinking({len(e.thinking)} 字符)" if e.thinking else ""
        tc = f"  tool_calls={e.tool_calls}" if e.tool_calls else ""
        print(f"  [{i}] {e.role:9s} text={e.text[:80]!r}{thk}{tc}")


def test_multi_turn():
    print("=" * 72)
    print("场景 1 — 多轮对话, 上下文连续")
    print("=" * 72)

    store = InMemoryHistoryStore()
    p = Player(
        player_id="multi_turn_p1",
        model_name=DEEPSEEK,
        system_prompt="你是一个数学助手, 一句话回答, 不要解释.",
        history_store=store,
    )

    r1 = await p.act("我有 7 个苹果")
    print(f"\nturn1 → {r1!r}")
    r2 = await p.act("又拿到 5 个, 现在多少?")
    print(f"turn2 → {r2!r}")
    r3 = await p.act("吃掉一半, 还剩多少?")
    print(f"turn3 → {r3!r}")

    dump_history(p, DEEPSEEK)

    history = p.history()
    assistant_entries = [e for e in history if e.role == "assistant"]
    has_thinking = sum(1 for e in assistant_entries if e.thinking)
    print(f"\n[校验] assistant 条数 = {len(assistant_entries)} (应=3)")
    print(f"[校验] 带 thinking 的 assistant 数 = {has_thinking} (deepseek 应 ≈ 3)")
    return store


def test_cross_model(store: InMemoryHistoryStore):
    print("\n" + "=" * 72)
    print("场景 2 — 同一份 history 切到 claude-opus, 继续对话不报错")
    print("=" * 72)

    p = Player(
        player_id="multi_turn_p1",                # 复用上一场景的 player_id
        model_name=CLAUDE,
        system_prompt="(忽略, 已有 system)",
        history_store=store,
    )
    r4 = await p.act("再买 10 个, 现在多少?")
    print(f"\nturn4 (model=claude) → {r4!r}")

    dump_history(p, CLAUDE)


def test_isolation_view():
    print("\n" + "=" * 72)
    print("场景 3 — 信息隔离: 默认视角下, 喂模型的 messages 不含 thinking")
    print("=" * 72)

    store = InMemoryHistoryStore()
    p = Player(
        player_id="iso_p1",
        model_name=DEEPSEEK,
        system_prompt="你是助手, 一句话回答.",
        history_store=store,
    )
    await p.act("写一句诗")
    # 第二轮调用前: 看看 adapter 会喂什么给模型 (模拟 act 内部)
    adapter = get_adapter(DEEPSEEK)
    entries = store.load("iso_p1")

    public_msgs = adapter.to_messages(entries, include_thinking=False)
    full_msgs = adapter.to_messages(entries, include_thinking=True)

    def has_thinking_in_msgs(msgs) -> bool:
        for m in msgs:
            c = getattr(m, "content", None)
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        return True
        return False

    print(f"对局视角 (include_thinking=False) → thinking in messages? "
          f"{has_thinking_in_msgs(public_msgs)} (应=False)")
    print(f"复盘视角 (include_thinking=True)  → thinking in messages? "
          f"{has_thinking_in_msgs(full_msgs)} (应=True if deepseek 有思考)")


async def main():
    store = test_multi_turn()
    test_cross_model(store)
    test_isolation_view()


if __name__ == "__main__":
    asyncio.run(main())
