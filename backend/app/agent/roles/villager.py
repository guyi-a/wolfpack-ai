"""Villager — 普通村民, 没有夜间技能, 但白天能投票 (持有 cast_vote)."""

from typing import Callable, Sequence

from langchain_core.tools import BaseTool

from app.agent.base import Player
from app.agent.contexts.history_store import HistoryStore
from app.agent.roles.wolf import make_cast_vote_tool


VILLAGER_SYSTEM_PROMPT = """\
你是狼人杀里的村民 (好人阵营), 没有任何特殊能力.
- 身份: 村民
- 阵营: 好人
- 目标: 通过白天发言推理、投票放逐, 找出并淘汰所有狼人
- 风格: 说话直率, 逻辑清晰; 不要装神 (谎称自己是预言家 / 女巫). 一次发言一两句话就好, 别啰嗦.
- 你看不到任何夜间私密信息, 只能基于公开发言推理.
- 白天投票时, 调 cast_vote(target_id) 把票投给你想放逐的人.
"""


def _noop_on_vote(*args, **kwargs):
    pass


class Villager(Player):
    """村民: 持有 cast_vote 工具用于白天投票. on_vote 默认 noop, phase 用时重绑."""

    def __init__(
        self,
        player_id: str,
        model_name: str,
        history_store: HistoryStore,
        *,
        on_vote: Callable[[str, str], None] = _noop_on_vote,
        extra_tools: Sequence[BaseTool] | None = None,
        **kwargs,
    ) -> None:
        vote_tool = make_cast_vote_tool(on_vote, voter_id=player_id)
        tools = [vote_tool] + (list(extra_tools) if extra_tools else [])
        super().__init__(
            player_id=player_id,
            model_name=model_name,
            system_prompt=VILLAGER_SYSTEM_PROMPT,
            history_store=history_store,
            tools=tools,
            **kwargs,
        )
