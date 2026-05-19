"""验证 Player.act 流式事件 publish 是否到达 bus.

不调真 LLM (mock agent), 只验证管道:
  - Player.act 启动 → bus 收到 player_state(thinking)
  - 中间 mock astream_events 推 chunk → bus 收到 token_chunk
  - 中间 mock astream_events 推 on_tool_start → bus 收到 player_state(tool_calling)
  - act 完 → bus 收到 player_state(idle) + inner_view

跑法:
    python app/tests/test_player_stream_events.py
"""

import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from langchain_core.messages import AIMessage, HumanMessage

from app.agent.base import Player
from app.agent.contexts.history_store import InMemoryHistoryStore
from app.infra.event_bus import EventBus


class FakeChunk:
    """模拟 AIMessageChunk."""
    def __init__(self, content):
        self.content = content
        self.tool_call_chunks = []


class FakeAgent:
    """模拟 LangGraph create_agent 的产物. 只实现 astream_events / invoke."""

    def __init__(self):
        # mock 事件序列: 思考开始 → 流 thinking 几片 → 流 text 几片 → 调工具 → 模型结束 → chain end
        self.events = [
            {"event": "on_chat_model_start", "name": "ChatAnthropic", "metadata": {"langgraph_node": "model"}, "data": {}},
            {"event": "on_chat_model_stream", "data": {"chunk": FakeChunk([{"type": "thinking", "thinking": "我考虑"}])}},
            {"event": "on_chat_model_stream", "data": {"chunk": FakeChunk([{"type": "thinking", "thinking": "一下..."}])}},
            {"event": "on_chat_model_stream", "data": {"chunk": FakeChunk([{"type": "text", "text": "查"}])}},
            {"event": "on_chat_model_stream", "data": {"chunk": FakeChunk([{"type": "text", "text": "5号"}])}},
            {"event": "on_tool_start", "name": "check_player", "data": {"input": {"target_id": "5"}}},
            {"event": "on_chat_model_end", "name": "ChatAnthropic", "metadata": {"langgraph_node": "model"}, "data": {}},
            {"event": "on_chain_end", "name": "LangGraph", "data": {"output": {"messages": [
                HumanMessage("(任务)"),
                AIMessage(content=[{"type": "thinking", "thinking": "我考虑一下..."}, {"type": "text", "text": "查5号"}]),
            ]}}},
        ]

    async def astream_events(self, input, version="v2", config=None):
        for ev in self.events:
            yield ev

    def invoke(self, input):
        # 兜底, 不该被走到
        return {"messages": []}


async def main():
    bus = EventBus("test")
    captured: list[dict] = []
    q = bus.subscribe()

    async def reader():
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                break
            if ev is None:
                break
            captured.append(ev)

    # 构造一个最简 Player, 把 agent 替成 FakeAgent
    p = Player(
        player_id="3",
        model_name="deepseek/deepseek-v4-pro",  # 只用来选 adapter, FakeAgent 不真调
        system_prompt="你是测试 player",
        history_store=InMemoryHistoryStore(),
        bus=bus,
    )
    p.agent = FakeAgent()   # 替换掉真 agent

    # 起读流的协程
    reader_task = asyncio.create_task(reader())

    # 跑 act
    text = await p.act("请查 5 号", round=1)
    print(f"act 返回 text = {text!r}")

    # 给 bus 时间把事件 drain 完
    await asyncio.sleep(0.3)
    reader_task.cancel()

    # 统计
    print(f"\n捕获事件 {len(captured)} 条:")
    kinds = {}
    for ev in captured:
        kinds[ev.get("kind")] = kinds.get(ev.get("kind"), 0) + 1
    print(f"按 kind 分布: {kinds}")

    print("\n详情:")
    for ev in captured:
        print(f"  {ev}")

    # 校验
    must_have = {"player_state", "token_chunk", "inner_view"}
    got = set(kinds.keys())
    missing = must_have - got
    if missing:
        print(f"\n❌ 缺失事件类型: {missing}")
        sys.exit(1)
    print(f"\n✅ 三种事件类型全部出现")


if __name__ == "__main__":
    asyncio.run(main())
