"""统一历史记录 schema (跨模型 / 跨存储的 single source of truth).

不论用什么模型 (deepseek / claude / mimo / ...), 也不论存哪里 (内存 / Redis),
一条历史条目都用 HistoryEntry 表示. 写入时 normalize, 读出后由 ModelAdapter
按目标模型展开成 messages.

设计原则:
  - thinking 单独成字段, 由调用方决定要不要带进 messages (信息隔离用)
  - tool_calls / tool_result 用通用 dict 表示, 不绑特定 SDK 类型
  - 不保留 Anthropic signature 等模型私有字段 (跨模型时这些字段无意义)
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


Role = Literal["system", "user", "assistant", "tool"]


class HistoryEntry(BaseModel):
    """一条统一历史. 一次模型轮回 (user 输入 → assistant 输出) 至少两条."""

    role: Role
    text: str = ""                          # 用户可见的纯文本 (对局视角只用这个)
    thinking: str = ""                      # 推理过程 (复盘视角才需要; 隔离机制要剥这一字段)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
                                            # [{name, args, id}, ...]
    tool_call_id: str = ""                  # 仅 role='tool' 用, 指向触发它的 tool_call
    name: str = ""                          # 仅 role='tool' 用, 工具名
    round: int = 0                          # 发生在第几轮 (用于跨源时序排序; 0=未指定)

    def has_thinking(self) -> bool:
        return bool(self.thinking)

    def public_view(self) -> "HistoryEntry":
        """对局视角: 剥掉 thinking 字段后的副本."""
        return self.model_copy(update={"thinking": ""})
