"""GameState — 对局核心状态对象 (上帝视角).

只描述"事实", 不知道任何 LLM / agent / Redis 细节. 所有 Player / Supervisor / Judge
都从这里读, 按规则改.

第一版只支持 6 人板:
    2 狼 + 1 预言家 + 1 女巫 + 2 村民

注意:
  - 玩家公开发言原文不存这里, 存 board Channel (单点真相)
  - thinking / 私有 (查验结果, 女巫药状态) 也不存这里, 存 player private log
  - GameState 只管: 谁是谁、谁还活着、当前阶段、夜间结算暂存、出局清单
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


Camp = Literal["good", "wolf"]
Role = Literal["villager", "seer", "witch", "wolf"]

ROLE_CAMP: dict[Role, Camp] = {
    "villager": "good",
    "seer": "good",
    "witch": "good",
    "wolf": "wolf",
}


class Phase(str, Enum):
    """对局阶段. 一轮的顺序: NIGHT -> DAY_SPEECH -> DAY_VOTE -> NIGHT ..."""

    NIGHT = "night"
    DAY_SPEECH = "day_speech"
    DAY_VOTE = "day_vote"
    ENDED = "ended"


@dataclass
class PlayerInfo:
    player_id: str
    role: Role
    alive: bool = True

    @property
    def camp(self) -> Camp:
        return ROLE_CAMP[self.role]


@dataclass
class NightActions:
    """单轮夜间动作暂存. 阶段切到 DAY_SPEECH 时由 Judge 结算到 GameState."""

    wolf_kill_target: Optional[str] = None     # 狼刀目标
    witch_save: bool = False                   # 女巫救人 (针对今晚被刀的人)
    witch_poison_target: Optional[str] = None  # 女巫毒人


@dataclass
class GameState:
    """对局上帝视角. 可变对象, apply_xxx 方法就地修改."""

    players: list[PlayerInfo]
    round: int = 0                              # 第几轮 (从 1 开始, 0 = 未开始)
    phase: Phase = Phase.NIGHT
    night_actions: NightActions = field(default_factory=NightActions)
    eliminated_today: Optional[str] = None      # 当天白天被票出的人
    deaths_announced_today: list[str] = field(default_factory=list)
                                                # 今天公布的死亡名单 (夜间死 + 投票死)

    # ----------------------------------------------------------------- 读侧

    def get(self, player_id: str) -> PlayerInfo:
        for p in self.players:
            if p.player_id == player_id:
                return p
        raise KeyError(f"无此玩家: {player_id}")

    def alive_players(self) -> list[PlayerInfo]:
        return [p for p in self.players if p.alive]

    def alive_ids(self) -> list[str]:
        return [p.player_id for p in self.players if p.alive]

    def role_of(self, player_id: str) -> Role:
        return self.get(player_id).role

    def camp_of(self, player_id: str) -> Camp:
        return self.get(player_id).camp

    def teammates_of(self, player_id: str) -> list[str]:
        """同阵营队友 (不含自己). 第一版只对狼人有意义."""
        me = self.get(player_id)
        return [
            p.player_id
            for p in self.players
            if p.player_id != player_id and p.camp == me.camp
        ]

    def alive_count_by_camp(self) -> dict[Camp, int]:
        counts: dict[Camp, int] = {"good": 0, "wolf": 0}
        for p in self.alive_players():
            counts[p.camp] += 1
        return counts

    def is_over(self) -> bool:
        counts = self.alive_count_by_camp()
        # 狼全死 → 好人赢; 狼 >= 好人 → 狼赢 (屠边/屠城近似)
        return counts["wolf"] == 0 or counts["wolf"] >= counts["good"]

    def winner(self) -> Optional[Camp]:
        if not self.is_over():
            return None
        counts = self.alive_count_by_camp()
        return "good" if counts["wolf"] == 0 else "wolf"

    # ----------------------------------------------------------------- 写侧

    def kill(self, player_id: str) -> None:
        self.get(player_id).alive = False

    def start_round(self) -> None:
        """进入下一轮的夜晚. round +=1, phase 复位到 NIGHT, 清掉单轮暂存."""
        self.round += 1
        self.phase = Phase.NIGHT
        self.night_actions = NightActions()
        self.eliminated_today = None
        self.deaths_announced_today = []

    def settle_night(self) -> list[str]:
        """夜间结算: 狼刀 (女巫救则取消) + 女巫毒. 返回今夜死亡的玩家 id 列表."""
        deaths: list[str] = []
        na = self.night_actions
        if na.wolf_kill_target and not na.witch_save:
            self.kill(na.wolf_kill_target)
            deaths.append(na.wolf_kill_target)
        if na.witch_poison_target:
            self.kill(na.witch_poison_target)
            deaths.append(na.witch_poison_target)
        self.deaths_announced_today = list(deaths)
        self.phase = Phase.DAY_SPEECH
        return deaths

    def settle_vote(self, vote_loser: Optional[str]) -> None:
        """白天投票结算: 出局玩家 (可能平票为 None)."""
        if vote_loser:
            self.kill(vote_loser)
            self.eliminated_today = vote_loser
            self.deaths_announced_today.append(vote_loser)
        if self.is_over():
            self.phase = Phase.ENDED
        else:
            self.phase = Phase.NIGHT  # 等 start_round 推进到下一轮
