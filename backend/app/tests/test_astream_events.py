"""验证 astream_events 全事件流 (Ling-Agent 同款生产形态).

跟 stream_mode 不同, astream_events 一次拿到所有粒度:
  - on_chat_model_start / on_chat_model_stream / on_chat_model_end  — token 级
  - on_tool_start / on_tool_end                                     — 工具调用级
  - on_chain_start / on_chain_end                                   — 节点级

跑法:
    python app/tests/test_astream_events.py

观察重点:
  1. 每种 event 的出现频次和 metadata 形态
  2. on_chat_model_stream 里 chunk.content 在 thinking 模型上的形态
  3. tool 调用全过程能不能完整复原 (start → end + 输入输出)
"""

import asyncio
import sys
from collections import Counter
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agent.infra.agent_factory import build_agent


MODEL = "deepseek/deepseek-v4-pro"

# 仅打印这些 kind, 其它(on_prompt_start 等)忽略防刷屏
INTERESTING = {
    "on_chain_start",
    "on_chain_end",
    "on_chat_model_start",
    "on_chat_model_stream",
    "on_chat_model_end",
    "on_tool_start",
    "on_tool_end",
}


def extract_token(chunk) -> tuple[str, list]:
    """从 AIMessageChunk 抽出 (text 增量, tool_call_chunks)."""
    if chunk is None:
        return "", []
    content = chunk.content if hasattr(chunk, "content") else chunk.get("content", "")
    tc_chunks = (
        getattr(chunk, "tool_call_chunks", None)
        or (chunk.get("tool_call_chunks") if isinstance(chunk, dict) else None)
        or []
    )
    if isinstance(content, str):
        return content, tc_chunks
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", ""))
            elif t == "thinking":
                s = b.get("thinking", "")
                if s:
                    parts.append(f"⟨thk:{s}⟩")
        return "".join(parts), tc_chunks
    return "", tc_chunks


async def trace_events(agent, user_message: str, label: str):
    print("=" * 76)
    print(label)
    print("=" * 76)

    counter: Counter[str] = Counter()
    stream_chunks = 0  # 把高频的 on_chat_model_stream 摘要打印, 不一行一行刷

    async for event in agent.astream_events(
        {"messages": [HumanMessage(user_message)]},
        version="v2",
    ):
        kind = event.get("event", "")
        counter[kind] += 1
        if kind not in INTERESTING:
            continue

        name = event.get("name", "")
        node = event.get("metadata", {}).get("langgraph_node", "-")

        if kind == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            text, tcs = extract_token(chunk)
            stream_chunks += 1
            # 只打印有内容的, 且 token 级 chunk 量大, 截短显示
            if text:
                preview = text.replace("\n", " ")
                print(f"  [stream] node={node:8s} +{preview!r}")
            if tcs:
                tc_brief = [(tc.get("name", ""), tc.get("args", "")) for tc in tcs]
                print(f"  [stream] node={node:8s} tool_call_chunks={tc_brief}")
            continue

        if kind == "on_tool_start":
            tool_input = event.get("data", {}).get("input", {})
            print(f"  [tool_start ] name={name!r} input={tool_input}")
            continue

        if kind == "on_tool_end":
            output = event.get("data", {}).get("output", "")
            print(f"  [tool_end   ] name={name!r} output={str(output)[:80]!r}")
            continue

        # chain / model 边界事件
        marker = {
            "on_chain_start": "chain_start",
            "on_chain_end": "chain_end",
            "on_chat_model_start": "model_start",
            "on_chat_model_end": "model_end",
        }[kind]
        print(f"  [{marker:11s}] name={name!r} node={node}")

    print(f"\n--- event 统计 (共 {sum(counter.values())} 个事件, "
          f"其中 {stream_chunks} 个 chat_model_stream) ---")
    for kind, count in counter.most_common():
        print(f"  {kind:32s} {count}")


async def main():
    # ---------- 场景 1: 纯 chat ----------
    chat_agent = build_agent(
        MODEL,
        system_prompt="你是简洁助手, 一句话回答, 不要解释.",
    )
    await trace_events(
        chat_agent,
        "一年有几天?",
        f"场景 1 — 纯 chat agent  (model={MODEL})",
    )

    # ---------- 场景 2: react + tool ----------
    @tool
    def get_weather(city: str) -> str:
        """查询某城市今天天气."""
        return f"{city} 今天 22°C, 晴, 微风."

    react_agent = build_agent(
        MODEL,
        system_prompt="问到天气必须调 get_weather 工具, 不要心算或编造.",
        tools=[get_weather],
    )
    print()
    await trace_events(
        react_agent,
        "北京今天天气?",
        f"场景 2 — react agent + tool  (model={MODEL})",
    )


if __name__ == "__main__":
    asyncio.run(main())
