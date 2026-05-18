"""Witch — 女巫 (好人神职).

夜里被告知今晚被刀的人, 可选: 用解药救 (一瓶, 用过即无) / 用毒药毒人 (一瓶, 用过即无) / 不动.
白天发言伪装普通好人 (是否跳女巫由战术决定).

工具 use_potion(potion_type, target_id?):
  - potion_type='save': 用解药救今晚被刀的人 (target_id 可省略)
  - potion_type='poison': 用毒药毒人 (target_id 必填)
  - 用过的药再次调用会返回失败信息

潜在选型: 是否允许"同一晚救+毒"? 标准规则下许可, 第一版也允许 (女巫自决).
"""

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

from langchain_core.tools import tool

from app.agent.base import Player
from app.agent.contexts.history_store import HistoryStore
from app.agent.roles.wolf import make_cast_vote_tool
from app.core.channel import Channel


WITCH_SYSTEM_PROMPT = """\
你是狼人杀里的女巫 (好人阵营核心神职).
- 阵营: 好人
- 你有两瓶药:
  - 解药 (save): 救今晚被狼刀的人, 一瓶
  - 毒药 (poison): 毒死指定玩家, 一瓶
- 每晚 task 会告诉你"今晚被狼刀的人是 X 号", 你自己决定救/毒/不动
  - 调 use_potion('save') 救人 (target_id 可省略, 默认救今晚被刀的人)
  - 调 use_potion('poison', target_id='X') 毒人
  - 啥也不调 = 不动
- 用过的药不能再用
- 白天可以选择跳女巫报药信息, 也可以隐身
- 白天投票时, 调 cast_vote(target_id) 把票投给你想放逐的人
- 风格: 谨慎果断, 一两句话.
"""


@dataclass
class PotionState:
    save_available: bool = True
    poison_available: bool = True


def make_use_potion_tool(state: PotionState, on_potion: Callable[[str, Optional[str]], None]):
    """构造 use_potion 工具.

    Args:
        state: 共享的 PotionState. 工具内部检查 + 标记消耗.
        on_potion: (potion_type, target_id) -> None 回调, 由 phase 收集实际动作.
    """

    @tool
    def use_potion(potion_type: str, target_id: Optional[str] = None) -> str:
        """用药. potion_type='save' 用解药 (target_id 可省略, 默认救今晚被刀的人); 'poison' 用毒药 (必填 target_id)."""
        if potion_type == "save":
            if not state.save_available:
                return "解药已经用过, 无法再用"
            state.save_available = False
            on_potion("save", target_id)
            return f"已用解药救人 (target={target_id or '今晚被刀的人'})"
        if potion_type == "poison":
            if not state.poison_available:
                return "毒药已经用过, 无法再用"
            if not target_id:
                return "毒药必须指定 target_id"
            state.poison_available = False
            on_potion("poison", target_id)
            return f"已用毒药毒 {target_id}号"
        return f"未知的药类型: {potion_type!r}, 应为 'save' 或 'poison'"

    return use_potion


class Witch(Player):
    """女巫. 持有 use_potion + cast_vote 两个工具."""

    def __init__(
        self,
        player_id: str,
        model_name: str,
        history_store: HistoryStore,
        channels: Sequence[Channel],
        on_potion: Callable[[str, Optional[str]], None],
        on_vote: Callable[[str, str], None] = lambda *a, **k: None,
        *,
        potion_state: Optional[PotionState] = None,
        **kwargs,
    ) -> None:
        self.potion_state = potion_state or PotionState()
        tool_fn = make_use_potion_tool(self.potion_state, on_potion)
        vote_tool = make_cast_vote_tool(on_vote, voter_id=player_id)
        super().__init__(
            player_id=player_id,
            model_name=model_name,
            system_prompt=WITCH_SYSTEM_PROMPT,
            history_store=history_store,
            tools=[tool_fn, vote_tool],
            channels=channels,
            **kwargs,
        )
