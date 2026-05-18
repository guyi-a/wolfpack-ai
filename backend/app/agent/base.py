"""Player 基类 — 多 Agent 系统里的 "玩家" 协议.

每个 player 持有:
  - player_id        : 唯一标识 (Redis key, history 隔离的边界)
  - model_name       : 用哪个 LLM (运行时可换 → adapter 跟着换)
  - system_prompt    : 角色 prompt (注入 build_agent, 不入 history)
  - tools            : 可选工具列表
  - history_store    : 私有 history (assistant 的 thinking / tool 结果, 仅自己可见)
  - channels         : 加入的频道列表 (board / wolf_chat / lovers 等). 通过 is_visible_to
                       自动隔离, 不需要 player 自己写权限检查
  - 内部按 model_name 解析 adapter + 编译 agent (build_agent)

act(task) 一次轮回:
  1. 读私有 history → adapter.to_messages
  2. 遍历所有可见 channels 渲染成 HumanMessage 列表
  3. 末尾追加 HumanMessage(task)
  4. agent.invoke → 拿一轮新 messages
  5. 把新 AI / Tool 全部 normalize, 写回 private store
  6. 返回最终 text

注意: 公开发言 / 狼频道发言由调用方 (supervisor) 在 act() 之后 append 到 channel,
       Player 不主动写 channel — 它不知道当前 round/phase.
"""

from typing import Optional, Sequence

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agent.contexts.adapters import get_adapter
from app.agent.contexts.history import HistoryEntry
from app.agent.contexts.history_store import HistoryStore
from app.agent.infra.agent_factory import build_agent
from app.core.channel import Channel, ChannelEvent


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
        include_thinking_in_context: bool = False,
        **llm_kwargs,
    ) -> None:
        self.player_id = player_id
        self.system_prompt = system_prompt
        self.history_store = history_store
        self.channels: list[Channel] = list(channels) if channels else []
        self.tools = list(tools) if tools else []
        self.include_thinking_in_context = include_thinking_in_context
        self._llm_kwargs = llm_kwargs
        self.set_model(model_name)

    # ------------------------------------------------------------------ public

    def act(self, task: str, *, round: int = 0) -> str:
        messages = self._build_messages(task)
        baseline = len(messages) - 1
        result = self.agent.invoke({"messages": messages})
        new_msgs = result["messages"][baseline:]

        self.history_store.append(
            self.player_id, HistoryEntry(role="user", text=task, round=round)
        )

        last_text = ""
        for m in new_msgs:
            if isinstance(m, HumanMessage):
                continue
            if isinstance(m, AIMessage):
                entry = self.adapter.normalize(m)
                entry.round = round
                self.history_store.append(self.player_id, entry)
                if entry.text:
                    last_text = entry.text
            elif isinstance(m, ToolMessage):
                content = m.content if isinstance(m.content, str) else str(m.content)
                self.history_store.append(
                    self.player_id,
                    HistoryEntry(
                        role="tool",
                        text=content,
                        tool_call_id=getattr(m, "tool_call_id", "") or "",
                        name=getattr(m, "name", "") or "",
                        round=round,
                    ),
                )
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

    # ------------------------------------------------------------------ helpers

    def _build_messages(self, task: str) -> list:
        """从所有可见 channel + 私有 history 拼出本次 invoke 的 messages.

        排序策略:
          - 主键: round 升序 (round=0 视为最早, 比所有具体轮次都早)
          - 同 round 内: 先 channels (按 self.channels list 顺序), 再私有 history
          - 私有 history / channel 内部各自按 append 顺序保持稳定
        最后追加本轮 task (HumanMessage), task 自身不入排序.
        """
        entries = self.history_store.load(self.player_id)
        # 私有 history → 一次性转成 messages, 跟 entries 一一对应保留 round
        private_msgs = self.adapter.to_messages(
            entries,
            include_thinking=self.include_thinking_in_context,
        )
        # to_messages 输出 len 跟 entries 不一定一致 (会跳过 None);
        # 我们直接按 entries 长度迭代, 用 entries[i].round 作为 key
        private_with_round: list[tuple[int, int, object]] = []  # (round, seq, message)
        # 简单兜底: 若 to_messages 输出条数等于 entries, 一一对应; 否则按顺序对齐前 N 条
        n = min(len(entries), len(private_msgs))
        for i in range(n):
            private_with_round.append((entries[i].round, i, private_msgs[i]))

        # channels → 同样组织成 (round, seq, message), seq 由 (channel_idx, event_idx) 组合
        channel_msgs: list[tuple[int, int, object]] = []
        for ch_idx, channel in enumerate(self.channels):
            if not channel.is_visible_to(self.player_id):
                continue
            for ev_idx, event in enumerate(channel.events):
                text = _render_event(channel, event)
                if text:
                    # 用 (channel_idx, event_idx) 编码成稳定 seq, channel 之间靠 ch_idx 决定优先级
                    seq = ch_idx * 100000 + ev_idx
                    channel_msgs.append((event.round, seq, HumanMessage(text)))

        # channels 在前, private 在后 (同 round 内): 给 channel_msgs 的 seq 让一档
        # 做法: 私有 seq + 大偏移
        OFFSET = 10_000_000
        merged: list[tuple[int, int, object]] = list(channel_msgs) + [
            (r, s + OFFSET, m) for (r, s, m) in private_with_round
        ]
        merged.sort(key=lambda x: (x[0], x[1]))

        return [m for (_, _, m) in merged] + [HumanMessage(task)]
