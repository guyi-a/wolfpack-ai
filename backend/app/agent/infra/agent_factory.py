"""通用 Agent 工厂 (测试阶段, 不绑狼人杀角色).

基于 LangGraph 的 create_react_agent 封装一层, 给定模型名 / system prompt / 工具列表,
返回一个能 .invoke({"messages": [...]}) 的编译图.

工具列表为空时即为纯 chat agent; 传工具就是 ReAct agent (模型自主决定何时调).

跑法 (内置 demo, 验证连通性):
    python app/agent/infra/agent_factory.py
"""

import sys
from pathlib import Path
from typing import Sequence

_BACKEND = Path(__file__).resolve().parent.parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain.agents import create_agent
from langchain_core.tools import BaseTool

from app.agent.infra.llm_factory import get_chat_model


def build_agent(
    model_name: str,
    system_prompt: str | None = None,
    tools: Sequence[BaseTool] | None = None,
    **llm_kwargs,
):
    """构造通用 agent (LangGraph 编译图).

    Args:
        model_name: 模型 ID, 必须在 app/agent/config/models.json 的 models 列表里.
        system_prompt: 可选 system prompt, 不传则模型按默认行为响应.
        tools: 可选工具列表; 为空时退化为纯 chat agent.
        **llm_kwargs: 透传给 ChatAnthropic (temperature / max_tokens 等).

    Returns:
        编译后的 LangGraph CompiledStateGraph, 调用方式::

            agent.invoke({"messages": [HumanMessage("...")]} )
            # 返回 {"messages": [...]}, 最后一条是 AI 的最终回复
    """
    llm = get_chat_model(model_name, **llm_kwargs)
    return create_agent(
        llm,
        list(tools) if tools else [],
        system_prompt=system_prompt,
    )


if __name__ == "__main__":
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import tool

    MODEL = "deepseek/deepseek-v4-pro"

    # ---------- demo 1: 纯 chat agent (无工具) ----------
    print("=" * 60)
    print(f"demo 1 — 纯 chat agent  (model={MODEL})")
    print("=" * 60)
    chat_agent = build_agent(
        MODEL,
        system_prompt="你是个简洁直接的助手, 一句话回答, 不要解释.",
    )
    result = chat_agent.invoke({"messages": [HumanMessage("一年有几天?")]})
    print(f"final: {result['messages'][-1].content!r}")

    # ---------- demo 2: 带工具的 react agent ----------
    print("\n" + "=" * 60)
    print(f"demo 2 — react agent + 工具调用  (model={MODEL})")
    print("=" * 60)

    @tool
    def add_numbers(a: int, b: int) -> int:
        """对两个整数求和."""
        return a + b

    react_agent = build_agent(
        MODEL,
        system_prompt="如果遇到加法运算, 必须用 add_numbers 工具计算, 不要心算.",
        tools=[add_numbers],
    )
    result = react_agent.invoke({"messages": [HumanMessage("帮我算 137 + 264")]})
    print("messages 流:")
    for m in result["messages"]:
        kind = type(m).__name__
        if hasattr(m, "tool_calls") and m.tool_calls:
            print(f"  {kind:15s} tool_calls={m.tool_calls}")
        else:
            content = m.content if isinstance(m.content, str) else str(m.content)[:120]
            print(f"  {kind:15s} {content!r}")
