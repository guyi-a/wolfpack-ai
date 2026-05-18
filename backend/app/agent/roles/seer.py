"""Seer (预言家) — 夜间能查验 1 名玩家身份的好人.

第一版工具实现走 mock: identities 字典直接说明每个 player_id 是 wolf 还是 good.
等 GameState 接入后, 工具实现改成读 game_state.role_of(target_id), Role 类本身不动.
"""

from typing import Callable, Mapping, Optional

from langchain_core.tools import tool

from app.agent.base import Player
from app.agent.contexts.history_store import HistoryStore
from app.agent.roles.wolf import make_cast_vote_tool


SEER_SYSTEM_PROMPT = """\
你是狼人杀里的预言家 (好人阵营核心神职).
- 身份: 预言家
- 阵营: 好人
- 能力: 每晚可用工具 check_player(target_id) 查验 1 名玩家身份 (返回 wolf / good)
- 目标: 通过查验找出狼人, 在白天发言时巧妙传递信息, 但避免被狼人针对
- 风格: 冷静理性. 白天可能选择跳出来报查验, 也可能藏身份 (战术自定).
- 你看不到其他玩家的私密信息. 你的查验历史只有你自己知道.
- 白天投票时, 调 cast_vote(target_id) 把票投给你想放逐的人.
"""


def make_check_player_tool(
    identities: Mapping[str, str],
    on_check: Optional[Callable[[str, str], None]] = None,
):
    """构造 check_player 工具.

    Args:
        identities: {player_id: "wolf" | "good"} 身份表.
        on_check: (target_id, result) -> None 回调, 工具被调用时同步通知 phase.

    Returns:
        一个 LangChain @tool 装饰的可调用对象.
    """

    @tool
    def check_player(target_id: str) -> str:
        """查验指定玩家身份, 返回 'wolf' 或 'good' (未知玩家返回 'unknown')."""
        result = identities.get(target_id, "unknown")
        if on_check is not None:
            on_check(target_id, result)
        return result

    return check_player


def _noop_on_vote(*args, **kwargs):
    pass


class Seer(Player):
    """预言家 Player: 自带 check_player 工具 + cast_vote (白天投票用)."""

    def __init__(
        self,
        player_id: str,
        model_name: str,
        history_store: HistoryStore,
        identities: Mapping[str, str],
        on_check: Optional[Callable[[str, str], None]] = None,
        on_vote: Callable[[str, str], None] = _noop_on_vote,
        **kwargs,
    ) -> None:
        # 保存身份表, 后面 phase 重绑 on_check 时复用
        self.identities = dict(identities)
        check_tool = make_check_player_tool(identities, on_check=on_check)
        vote_tool = make_cast_vote_tool(on_vote, voter_id=player_id)
        super().__init__(
            player_id=player_id,
            model_name=model_name,
            system_prompt=SEER_SYSTEM_PROMPT,
            history_store=history_store,
            tools=[check_tool, vote_tool],
            **kwargs,
        )
