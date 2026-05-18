"""验证 _build_messages 的顺序 / 内容.

跑法: python app/tests/test_message_assembly.py

不调 LLM, 全是手工构造 channel / history 后看 player._build_messages 拼出来啥.
重点确认:
  1. 多个 channel 时, 当前实现是按 channels list 顺序逐个展开
  2. 同 channel 内事件按 append 顺序
  3. 私有 history (assistant / tool) 在所有 channel 之后
  4. 本轮 task 在最末尾
  5. 别人的 thinking 绝对不会出现在自己 messages 里
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history import HistoryEntry
from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel


MODEL = "deepseek/deepseek-v4-pro"  # 不会真 invoke, 只要 build_agent 能编出来


def render(msg) -> str:
    cls = type(msg).__name__
    c = msg.content
    if isinstance(c, str):
        return f"{cls:13s} | {c[:90]}{'…' if len(c) > 90 else ''}"
    if isinstance(c, list):
        kinds = []
        for b in c:
            if isinstance(b, dict):
                t = b.get("type", "?")
                if t == "thinking":
                    kinds.append(f"thinking({len(b.get('thinking', ''))} 字符)")
                elif t == "text":
                    kinds.append(f"text({(b.get('text') or '')[:30]!r})")
                else:
                    kinds.append(t)
            else:
                kinds.append(type(b).__name__)
        return f"{cls:13s} | blocks={kinds}"
    return f"{cls:13s} | {c!r}"


def main():
    board = Channel.board(["1", "2", "3", "4", "5", "6"])
    wolf_chat = Channel.wolf_chat(["1", "4"])

    # --- 模拟若干公开事件 (board) ---
    board.append_night_result(round=1, deaths=["5"])
    board.append_speech(1, "2", "5号倒牌, 听预言家报查验。")
    board.append_speech(1, "3", "我是预言家, 查 1 号是狼。")

    # --- 模拟狼频道事件 (wolf_chat) ---
    wolf_chat.append_speech(1, "1", "第一夜没信息, 先刀 5 号看看。")
    wolf_chat.append_speech(1, "4", "已投5号, 稳的。")

    # --- 构造 1 号狼 ---
    store = InMemoryHistoryStore()
    # 给 1 号狼塞一条上轮 (第 1 夜) assistant 私有 history (带 thinking + tool_call)
    store.append(
        "1",
        HistoryEntry(
            role="assistant",
            text="第一夜先刀 5 号, 安全为主。",
            thinking="我考虑了 5 号, 因为他位置在中间, 出局影响最小。",
            tool_calls=[{"id": "call_x", "name": "cast_vote", "args": {"target_id": "5"}}],
            round=1,
        ),
    )
    store.append(
        "1",
        HistoryEntry(
            role="tool",
            text="已投票: 1号 -> 5号",
            tool_call_id="call_x",
            name="cast_vote",
            round=1,
        ),
    )

    wolf1 = Wolf(
        player_id="1",
        model_name=MODEL,
        history_store=store,
        teammates=["4"],
        channels=[board, wolf_chat],
        on_vote=lambda *a, **k: None,
    )

    task = "现在是第 2 夜, 请商量并 cast_vote 投票"
    msgs = wolf1._build_messages(task)

    print("=" * 80)
    print(f"1号狼 (channels=[board, wolf_chat]) _build_messages 输出共 {len(msgs)} 条:")
    print("=" * 80)
    for i, m in enumerate(msgs):
        print(f"  [{i:>2}] {render(m)}")

    # --- 切换 channels 顺序看变化 ---
    wolf1.channels = [wolf_chat, board]
    msgs2 = wolf1._build_messages(task)
    print("\n" + "=" * 80)
    print(f"channels 改为 [wolf_chat, board] 后, 重新拼:")
    print("=" * 80)
    for i, m in enumerate(msgs2):
        print(f"  [{i:>2}] {render(m)}")

    # --- 校验: 别人的 thinking 不出现 ---
    def find_thinking_owner(msgs) -> list[int]:
        idxs = []
        for i, m in enumerate(msgs):
            c = getattr(m, "content", None)
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "thinking":
                        idxs.append(i)
        return idxs

    own_thk_idx = find_thinking_owner(msgs)
    print("\n" + "=" * 80)
    print("校验 thinking 归属")
    print("=" * 80)
    print(f"  thinking block 出现位置: {own_thk_idx}")
    print(f"  (应只出现在私有 history 来源的 AIMessage 上, 不该出现在 HumanMessage 上)")


if __name__ == "__main__":
    main()
