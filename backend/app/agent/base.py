"""Player 基类 — 多 Agent 系统里的 "玩家" 协议.

每个 player 持有:
  - player_id        : 唯一标识 (Redis key, history 隔离的边界)
  - model_name       : 用哪个 LLM (运行时可换 → adapter 跟着换)
  - system_prompt    : 角色 prompt (注入 build_agent, 不入 history)
  - tools            : 可选工具列表
  - history_store    : 私有 history (assistant 的 thinking / tool 结果, 仅自己可见)
  - channels         : 加入的频道列表 (board / wolf_chat / lovers 等)
  - bus              : 可选 EventBus, 传入则 act 时推流式事件 (player_state / token_chunk / inner_view)
  - 内部按 model_name 解析 adapter + 编译 agent (build_agent)

act(task) 一次轮回 (async, 走 astream_events):
  1. 读私有 history → adapter.to_messages + 拼 channel 事件 → messages
  2. publish player_state(thinking)
  3. async for event in agent.astream_events:
       on_chat_model_stream → publish token_chunk (thinking / text)
       on_tool_start        → publish player_state(tool_calling, tool_name)
       on_tool_end          → (no-op, 工具结果作为 ToolMessage 写 history)
  4. publish player_state(idle)
  5. 把新 AI / Tool 全部 normalize 写回 store
  6. publish inner_view (一次性汇总本轮 thinking + tool_calls + text)
  7. 返回最终 text

注意: 公开发言由调用方 (phase / supervisor) 在 act() 之后 append 到 channel,
       Player 不主动写 channel — 它不知道当前 round/phase.
"""

from typing import Any, Awaitable, Callable, Optional, Sequence

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agent.contexts.adapters import get_adapter
from app.agent.contexts.history import HistoryEntry
from app.agent.contexts.history_store import HistoryStore
from app.agent.infra.agent_factory import build_agent
from app.core.channel import Channel, ChannelEvent
from app.infra.event_bus import EventBus


# 每次 act 结束后的钩子: (player_id, 本次新增的 entries) -> awaitable
# 由外层 (e.g. GameRuntime) 用来增量落库 player_private_history
ActFinishedHook = Callable[[str, list[HistoryEntry]], Awaitable[None]]


# 频道名 → 渲染前缀模板. 每条事件再叠上 kind 决定具体内容.
_CHANNEL_PREFIX: dict[str, str] = {
    "board": "[第{r}天",          # 全场 — 第N天
    "wolf_chat": "[第{r}夜 狼频道",  # 狼夜聊 — 第N夜
    "lovers": "[第{r}夜 情侣频道",   # 情侣 — 第N夜
}


def _render_event(channel: Channel, event: ChannelEvent) -> Optional[str]:
    """渲染 channel 里的一条事件成喂模型的文本; 返回 None 表示跳过."""
    prefix = _CHANNEL_PREFIX.get(channel.name, f"[第{{r}}轮 {channel.name}")
    head = prefix.format(r=event.round)
    p = event.payload

    if event.kind == "speech":
        return f"{head}] {p['speaker']}号: {p['text']}"
    if event.kind == "last_words":
        reason_zh = {
            "killed_at_night": "夜间被刀",
            "voted_out": "被票出局",
        }.get(p.get("reason", ""), "出局")
        return f"{head} 遗言 ({reason_zh})] {p['speaker']}号: {p['text']}"
    if event.kind == "vote":
        return f"{head}] {p['voter']}号 -> {p['target']}号"
    if event.kind == "vote_result":
        abstain = p.get("abstentions") or []
        abstain_part = f", 弃权: {', '.join(f'{a}号' for a in abstain)}" if abstain else ""
        if p.get("loser"):
            return (
                f"{head} 投票结果] {p['loser']}号 被票出局. "
                f"票数: {p['tally']}{abstain_part}"
            )
        return f"{head} 投票结果] 平票, 无人出局. 票数: {p['tally']}{abstain_part}"
    if event.kind == "night_result":
        deaths = p.get("deaths") or []
        if channel.name == "wolf_chat":
            # 在狼频道里, 用 night_result 装"我们决定刀谁"
            target = deaths[0] if deaths else None
            return f"{head}] 决定刀: {target}号" if target else None
        if deaths:
            who = "号、".join(deaths) + "号"
            return f"{head} 公告] 昨晚死亡: {who}"
        return f"{head} 公告] 昨晚平安夜, 无人死亡"
    if event.kind == "phase_change":
        return None
    if event.kind == "game_end":
        return f"[对局结束] 胜利方: {p['winner']}"
    return None


def _extract_chunk_text(chunk: Any) -> tuple[str, str]:
    """从 LangChain AIMessageChunk 抽出 (thinking_delta, text_delta).

    deepseek/glm/mimo: content 是 list[{type:thinking}, {type:text}]
    claude-opus: content 是 string (直接当 text)
    """
    if chunk is None:
        return "", ""
    content = chunk.content if hasattr(chunk, "content") else None
    if isinstance(content, str):
        return "", content
    if isinstance(content, list):
        thinking, text = "", ""
        for b in content:
            if isinstance(b, dict):
                t = b.get("type")
                if t == "thinking":
                    thinking += b.get("thinking", "")
                elif t == "text":
                    text += b.get("text", "")
        return thinking, text
    return "", ""


class Player:
    """单 Agent 玩家. 外层 supervisor 只通过 act(task) 跟它交互."""

    def __init__(
        self,
        player_id: str,
        model_name: str,
        system_prompt: str,
        history_store: HistoryStore,
        tools: Sequence[BaseTool] | None = None,
        *,
        channels: Optional[Sequence[Channel]] = None,
        bus: Optional[EventBus] = None,
        on_act_finished: Optional[ActFinishedHook] = None,
        include_thinking_in_context: bool = False,
        **llm_kwargs,
    ) -> None:
        self.player_id = player_id
        self.system_prompt = system_prompt
        self.history_store = history_store
        self.channels: list[Channel] = list(channels) if channels else []
        self.tools = list(tools) if tools else []
        self.bus = bus
        self.on_act_finished = on_act_finished
        self.include_thinking_in_context = include_thinking_in_context
        self._llm_kwargs = llm_kwargs
        self.set_model(model_name)

    # ------------------------------------------------------------------ public

    async def act(self, task: str, *, round: int = 0) -> str:
        """异步执行一次 act.

        流式推送 (bus 非空时):
          - player_state(thinking) at model_start
          - token_chunk(thinking/text) at model_stream
          - player_state(tool_calling, tool_name) at tool_start
          - player_state(idle) at model_end (最后一次)
          - inner_view 一次性汇总 (含 thinking + tool_calls + text)
        """
        messages = self._build_messages(task)
        baseline = len(messages) - 1

        self._publish_state("thinking")

        try:
            final_messages = None
            async for event in self.agent.astream_events(
                {"messages": messages},
                version="v2",
                config={"recursion_limit": 200},
            ):
                kind = event.get("event", "")

                if kind == "on_chat_model_start":
                    self._publish_state("thinking")
                elif kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    thinking_delta, text_delta = _extract_chunk_text(chunk)
                    if thinking_delta:
                        self._publish_token("thinking", thinking_delta)
                    if text_delta:
                        self._publish_token("text", text_delta)
                elif kind == "on_tool_start":
                    self._publish_state(
                        "tool_calling",
                        tool_name=event.get("name", ""),
                    )
                elif kind == "on_chain_end" and event.get("name") == "LangGraph":
                    # 整个 graph 跑完, 拿最终 messages
                    output = event.get("data", {}).get("output")
                    if isinstance(output, dict) and "messages" in output:
                        final_messages = output["messages"]
        finally:
            self._publish_state("idle")

        # 兜底: 极端情况 final_messages 没拿到, 退化到非流式 invoke
        if final_messages is None:
            result = self.agent.invoke({"messages": messages})
            final_messages = result["messages"]

        new_msgs = final_messages[baseline:]

        # 写回 history
        user_entry = HistoryEntry(role="user", text=task, round=round)
        self.history_store.append(self.player_id, user_entry)
        last_text = ""
        new_entries: list[HistoryEntry] = []
        for m in new_msgs:
            if isinstance(m, HumanMessage):
                continue
            if isinstance(m, AIMessage):
                entry = self.adapter.normalize(m)
                entry.round = round
                self.history_store.append(self.player_id, entry)
                new_entries.append(entry)
                if entry.text:
                    last_text = entry.text
            elif isinstance(m, ToolMessage):
                content = m.content if isinstance(m.content, str) else str(m.content)
                entry = HistoryEntry(
                    role="tool",
                    text=content,
                    tool_call_id=getattr(m, "tool_call_id", "") or "",
                    name=getattr(m, "name", "") or "",
                    round=round,
                )
                self.history_store.append(self.player_id, entry)
                new_entries.append(entry)

        # 一次性汇总 inner_view (给前端复盘 / 上帝视角)
        self._publish_inner_view(round, new_entries)

        # 增量落库 hook: 本次 act 的所有 entries (含 user task 这条)
        if self.on_act_finished is not None:
            try:
                await self.on_act_finished(self.player_id, [user_entry] + new_entries)
            except Exception:
                # 落库失败不影响游戏继续, 由 sink 自己 log
                pass

        return last_text

    def set_model(self, model_name: str) -> None:
        self.model_name = model_name
        self.adapter = get_adapter(model_name)
        self.agent = build_agent(
            model_name,
            system_prompt=self.system_prompt,
            tools=self.tools,
            **self._llm_kwargs,
        )

    def join(self, channel: Channel) -> None:
        """加入一个频道. 自动也注册到 channel.members."""
        if channel not in self.channels:
            self.channels.append(channel)
        if self.player_id not in channel.members:
            channel.members.append(self.player_id)

    def history(self) -> list[HistoryEntry]:
        """私有 history (仅自己的发言 / thinking / 工具结果)."""
        return self.history_store.load(self.player_id)

    # ------------------------------------------------------------------ bus 推送

    def _publish_state(self, state: str, *, tool_name: str = "") -> None:
        if self.bus is None:
            return
        payload: dict = {"player_id": self.player_id, "state": state}
        if tool_name:
            payload["tool_name"] = tool_name
        self.bus.publish({"kind": "player_state", "payload": payload})

    def _publish_token(self, phase: str, delta: str) -> None:
        if self.bus is None:
            return
        self.bus.publish({
            "kind": "token_chunk",
            "payload": {
                "player_id": self.player_id,
                "phase": phase,   # "thinking" / "text"
                "delta": delta,
            },
        })

    def _publish_inner_view(self, round: int, new_entries: list[HistoryEntry]) -> None:
        if self.bus is None or not new_entries:
            return
        # 汇总本轮 act 内产生的 assistant + tool 条目
        thinking_parts: list[str] = []
        text_parts: list[str] = []
        tool_records: list[dict] = []
        last_tool_call_args: dict[str, dict] = {}
        for e in new_entries:
            if e.role == "assistant":
                if e.thinking:
                    thinking_parts.append(e.thinking)
                if e.text:
                    text_parts.append(e.text)
                for tc in e.tool_calls or []:
                    tc_id = tc.get("id") or ""
                    record = {
                        "id": tc_id,
                        "name": tc.get("name"),
                        "args": tc.get("args"),
                        "result": None,
                    }
                    tool_records.append(record)
                    if tc_id:
                        last_tool_call_args[tc_id] = record
            elif e.role == "tool":
                rec = last_tool_call_args.get(e.tool_call_id)
                if rec is not None:
                    rec["result"] = e.text
        self.bus.publish({
            "kind": "inner_view",
            "payload": {
                "player_id": self.player_id,
                "round": round,
                "thinking": "\n".join(thinking_parts),
                "tool_calls": tool_records,
                "text": "\n".join(text_parts),
            },
        })

    # ------------------------------------------------------------------ helpers

    def _build_messages(self, task: str) -> list:
        """从所有可见 channel + 私有 history 拼出本次 invoke 的 messages.

        排序策略:
          - 主键: round 升序 (round=0 视为最早)
          - 同 round 内: 先 channels, 再私有 history
        最后追加本轮 task (HumanMessage), task 自身不入排序.
        """
        entries = self.history_store.load(self.player_id)
        private_msgs = self.adapter.to_messages(
            entries,
            include_thinking=self.include_thinking_in_context,
        )
        private_with_round: list[tuple[int, int, object]] = []
        n = min(len(entries), len(private_msgs))
        for i in range(n):
            private_with_round.append((entries[i].round, i, private_msgs[i]))

        channel_msgs: list[tuple[int, int, object]] = []
        for ch_idx, channel in enumerate(self.channels):
            if not channel.is_visible_to(self.player_id):
                continue
            for ev_idx, event in enumerate(channel.events):
                text = _render_event(channel, event)
                if text:
                    seq = ch_idx * 100000 + ev_idx
                    channel_msgs.append((event.round, seq, HumanMessage(text)))

        OFFSET = 10_000_000
        merged: list[tuple[int, int, object]] = list(channel_msgs) + [
            (r, s + OFFSET, m) for (r, s, m) in private_with_round
        ]
        merged.sort(key=lambda x: (x[0], x[1]))

        return [m for (_, _, m) in merged] + [HumanMessage(task)]
