"""验证流式调用 (token 级 + step 级).

跑法:
    python app/tests/test_streaming.py

观察重点:
  1. token 级流 (stream_mode='messages'): 是否能边生成边拿到增量 chunk
  2. step 级流 (stream_mode='updates'): 工具调用全过程 (LLM → tool → LLM)
  3. thinking block 在流中的形态 (是先全部 thinking 再 text, 还是混合?)

前端的"打字机"效果就靠 token 级流; 操作日志靠 step 级流.
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from app.agent.infra.agent_factory import build_agent


MODEL = "deepseek/deepseek-v4-pro"


def render_chunk_content(content) -> str:
    """把一个 chunk.content 渲染成可打印片段, 区分 thinking / text / 其他."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "thinking":
                s = b.get("thinking", "")
                if s:
                    parts.append(f"\033[90m{s}\033[0m")     # 灰色 = thinking
            elif t == "text":
                s = b.get("text", "")
                if s:
                    parts.append(s)
            elif t == "tool_use":
                parts.append(f"[tool_use:{b.get('name')}]")
        return "".join(parts)
    return ""


def test_token_stream():
    """场景 1: 纯 chat agent + token 级流 (stream_mode='messages')."""
    print("=" * 72)
    print(f"场景 1 — 纯 chat agent / token 级流  (model={MODEL})")
    print("(灰色 = thinking 增量,  正常色 = text 增量)")
    print("=" * 72)

    agent = build_agent(
        MODEL,
        system_prompt="你是个简洁助手, 一段话以内回答, 不要列点.",
    )

    chunk_count = 0
    for chunk, metadata in agent.stream(
        {"messages": [HumanMessage("简单介绍一下狼人杀这个桌游, 不超过两句")]},
        stream_mode="messages",
    ):
        chunk_count += 1
        rendered = render_chunk_content(chunk.content)
        if rendered:
            print(rendered, end="", flush=True)
    print(f"\n\n[共 {chunk_count} 个 chunk]")


def test_step_stream():
    """场景 2: react agent + 工具调用 + step 级流 (stream_mode='updates')."""
    print("\n" + "=" * 72)
    print(f"场景 2 — react agent / step 级流 + 工具调用  (model={MODEL})")
    print("=" * 72)

    @tool
    def get_weather(city: str) -> str:
        """查询某城市今天的天气."""
        return f"{city} 今天 22°C, 晴, 微风."

    agent = build_agent(
        MODEL,
        system_prompt="问到天气必须调 get_weather 工具, 不要心算或编造.",
        tools=[get_weather],
    )

    for step_idx, update in enumerate(agent.stream(
        {"messages": [HumanMessage("北京今天天气怎么样?")]},
        stream_mode="updates",
    ), start=1):
        for node, payload in update.items():
            print(f"\n--- step {step_idx} : 节点 {node!r} ---")
            messages = payload.get("messages", []) if isinstance(payload, dict) else []
            for m in messages:
                kind = type(m).__name__
                if getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        print(f"  {kind}: tool_call = {tc['name']}({tc['args']})")
                else:
                    content = m.content
                    if isinstance(content, str):
                        preview = content[:200].replace("\n", " ")
                        print(f"  {kind}: {preview!r}")
                    elif isinstance(content, list):
                        kinds = [b.get("type") if isinstance(b, dict) else "?" for b in content]
                        print(f"  {kind}: blocks={kinds}")
                        for b in content:
                            if isinstance(b, dict) and b.get("type") == "text":
                                preview = b.get("text", "")[:200].replace("\n", " ")
                                print(f"      text: {preview!r}")


def main():
    test_token_stream()
    test_step_stream()


if __name__ == "__main__":
    main()
