"""Wolf — 狼人.

夜里在 wolf_chat channel 商量, 每只狼调一次 cast_vote(target_id) 投票出今晚刀谁.
白天在 board channel 发言, 必须伪装好人.

cast_vote 工具是通用机制 (狼夜投票 / 白天投票共用), 内部把投票推给 phase 的
on_vote 回调; phase 统计票数决定结果. Wolf 自己只管"投谁", 不关心结果汇总.
"""

from typing import Callable, Sequence

from langchain_core.tools import tool

from app.agent.base import Player
from app.agent.contexts.history_store import HistoryStore
from app.core.channel import Channel


WOLF_SYSTEM_PROMPT_TEMPLATE = """\
你是狼人杀里的狼人 (狼人阵营).
- 阵营: 狼
- 你的同伴狼人: {teammates}
- 目标: 团灭好人 (好人神职优先, 然后是村民)
- 你能看见 [狼频道] 里的同伴讨论, 跟同伴商量今晚刀谁
- 白天必须伪装好人, 不能暴露自己是狼或暴露同伴
- 风格: 自然, 不要刻意装好人 (反而暴露). 一两句话.
"""


def _normalize_player_id(raw: str) -> str:
    """容错: 去掉 '号' 后缀 / 空白, 拿到纯 player_id."""
    if raw is None:
        return ""
    s = str(raw).strip()
    if s.endswith("号"):
        s = s[:-1].strip()
    return s


def make_cast_vote_tool(on_vote: Callable[[str, str], None], voter_id: str):
    """构造 cast_vote 工具.

    Args:
        on_vote: 工具被调用时的回调, 签名 (voter_id, target_id) -> None.
                 由 phase 提供, 用于汇总投票.
        voter_id: 调用方的 player_id, 闭包提前绑定; LLM 不需要传.
    """

    @tool
    def cast_vote(target_id: str) -> str:
        """投票给目标玩家. 用于狼夜投票决定刀谁 / 白天投票决定放逐谁. 返回确认信息."""
        normalized = _normalize_player_id(target_id)
        on_vote(voter_id, normalized)
        return f"已投票: {voter_id}号 -> {normalized}号"

    return cast_vote


class Wolf(Player):
    """狼人. 工具集只有 cast_vote, 加入 board + wolf_chat 两个 channel."""

    def __init__(
        self,
        player_id: str,
        model_name: str,
        history_store: HistoryStore,
        teammates: Sequence[str],
        channels: Sequence[Channel],
        on_vote: Callable[[str, str], None],
        **kwargs,
    ) -> None:
        teammates_str = (
            "、".join(f"{tid}号" for tid in teammates) if teammates else "(无, 你是孤狼)"
        )
        prompt = WOLF_SYSTEM_PROMPT_TEMPLATE.format(teammates=teammates_str)
        vote_tool = make_cast_vote_tool(on_vote, voter_id=player_id)
        super().__init__(
            player_id=player_id,
            model_name=model_name,
            system_prompt=prompt,
            history_store=history_store,
            tools=[vote_tool],
            channels=channels,
            **kwargs,
        )
