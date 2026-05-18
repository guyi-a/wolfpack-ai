"""ModelAdapter: 把统一 HistoryEntry 喂模型 / 把模型 response 归一化回 HistoryEntry.

两条路径覆盖全部 5 个模型 (见 CLAUDE.md "模型行为观察"):
  - DeepSeekStyleAdapter : content 是 list[thinking, text] — deepseek/flash/mimo/glm
  - ClaudeStyleAdapter   : content 是 plain string         — pa/claude-opus-4-7

读侧 (to_messages):
  - 把 HistoryEntry 展开成 LangChain BaseMessage 列表
  - 默认带 thinking (复盘视角); include_thinking=False 时不带 (对局视角)
  - 喂 claude-opus 时, thinking 字段无论如何丢弃 (协议无此通道)

写侧 (normalize):
  - 把 LangChain response (AIMessage) 拆成 (text, thinking, tool_calls)
  - 返回单条 assistant HistoryEntry
"""

from typing import Any, Protocol

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agent.contexts.history import HistoryEntry


class ModelAdapter(Protocol):
    """模型适配协议: 双向转换 HistoryEntry ↔ LangChain messages."""

    def normalize(self, response: AIMessage) -> HistoryEntry: ...

    def to_messages(
        self,
        entries: list[HistoryEntry],
        *,
        include_thinking: bool = False,
    ) -> list[BaseMessage]: ...


def _entry_to_basic_message(entry: HistoryEntry) -> BaseMessage | None:
    """所有 adapter 共用的入口路径: system/user/tool 三类直接转, assistant 由 adapter 各自处理."""
    if entry.role == "system":
        return SystemMessage(entry.text)
    if entry.role == "user":
        return HumanMessage(entry.text)
    if entry.role == "tool":
        return ToolMessage(
            content=entry.text,
            tool_call_id=entry.tool_call_id,
            name=entry.name or None,
        )
    return None  # assistant 由 adapter 自己拼


class DeepSeekStyleAdapter:
    """适用 deepseek / mimo / glm 等 thinking-list 协议模型."""

    def normalize(self, response: AIMessage) -> HistoryEntry:
        text, thinking = "", ""
        content = response.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for b in content:
                if not isinstance(b, dict):
                    continue
                t = b.get("type")
                if t == "text":
                    text += b.get("text", "")
                elif t == "thinking":
                    thinking += b.get("thinking", "")

        tool_calls: list[dict[str, Any]] = []
        for tc in getattr(response, "tool_calls", []) or []:
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                }
            )
        return HistoryEntry(
            role="assistant",
            text=text,
            thinking=thinking,
            tool_calls=tool_calls,
        )

    def to_messages(
        self,
        entries: list[HistoryEntry],
        *,
        include_thinking: bool = False,
    ) -> list[BaseMessage]:
        out: list[BaseMessage] = []
        for e in entries:
            basic = _entry_to_basic_message(e)
            if basic is not None:
                out.append(basic)
                continue
            # assistant: 拼成 list[thinking?, text]
            blocks: list[dict[str, Any]] = []
            if include_thinking and e.thinking:
                blocks.append({"type": "thinking", "thinking": e.thinking})
            if e.text:
                blocks.append({"type": "text", "text": e.text})
            content = blocks if blocks else e.text  # 极端情况兜底成 string
            out.append(
                AIMessage(
                    content=content,
                    tool_calls=e.tool_calls or [],
                )
            )
        return out


class ClaudeStyleAdapter:
    """适用 pa/claude-opus-4-7 — Novita 端点下 content 仅是 string, 无 thinking 通道."""

    def normalize(self, response: AIMessage) -> HistoryEntry:
        text = ""
        content = response.content
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    text += b.get("text", "")
                elif isinstance(b, str):
                    text += b
        tool_calls: list[dict[str, Any]] = []
        for tc in getattr(response, "tool_calls", []) or []:
            tool_calls.append(
                {
                    "id": tc.get("id", ""),
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                }
            )
        return HistoryEntry(
            role="assistant",
            text=text,
            thinking="",          # claude-opus 没独立 thinking
            tool_calls=tool_calls,
        )

    def to_messages(
        self,
        entries: list[HistoryEntry],
        *,
        include_thinking: bool = False,  # 接受参数但忽略, 协议不支持
    ) -> list[BaseMessage]:
        out: list[BaseMessage] = []
        for e in entries:
            basic = _entry_to_basic_message(e)
            if basic is not None:
                out.append(basic)
                continue
            out.append(
                AIMessage(
                    content=e.text,  # 永远 string
                    tool_calls=e.tool_calls or [],
                )
            )
        return out


# 模型 → adapter 的映射表. 新增模型时在这加一行
_ADAPTER_REGISTRY: dict[str, ModelAdapter] = {
    "deepseek/deepseek-v4-pro": DeepSeekStyleAdapter(),
    "deepseek/deepseek-v4-flash": DeepSeekStyleAdapter(),
    "xiaomimimo/mimo-v2.5-pro": DeepSeekStyleAdapter(),
    "zai-org/glm-5.1": DeepSeekStyleAdapter(),
    "pa/claude-opus-4-7": ClaudeStyleAdapter(),
}


def get_adapter(model_name: str) -> ModelAdapter:
    if model_name not in _ADAPTER_REGISTRY:
        raise ValueError(
            f"模型 {model_name!r} 没有注册 adapter. "
            f"已注册: {list(_ADAPTER_REGISTRY)}. "
            f"请在 app/agent/contexts/adapters.py _ADAPTER_REGISTRY 加一行映射."
        )
    return _ADAPTER_REGISTRY[model_name]
