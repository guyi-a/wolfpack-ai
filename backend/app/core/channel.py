"""Channel — 有限可见的事件流抽象.

一个 Channel = 一群成员能共享的事件流. 全场公开发言是 board channel,
狼夜聊是 wolf_chat channel, 情侣是 lovers channel.

设计原则:
  - Channel 自己不强制做 ACL: 是否允许某 player 写入由调用方控制
    (反正第一版只有 supervisor / role 自己往里写, 不存在恶意 player 越权)
  - Channel 不知道 thinking 是什么; 写入什么是写入方的责任
  - 一个 Channel 实例对应一个 "圈子", 由 members 列表声明
  - Player 持有自己加入的 channels 列表; 渲染时挑出自己能看的事件

事件流的真实顺序由调用方按 round / phase 推进时 append 的次序决定;
本第一版不内置时间戳, 后面要 interleave 多 channel 时再加.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional


EventKind = Literal[
    "speech",        # 发言 / 聊天
    "last_words",    # 遗言 (死者临死发言)
    "vote",          # 投票
    "vote_result",   # 投票结果
    "night_result",  # 夜间结算公告; 在 wolf_chat 里也可以用来记 "决定刀 X"
    "phase_change",
    "game_end",
]


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------


@dataclass
class ChannelEvent:
    kind: EventKind
    round: int
    payload: dict


@dataclass
class Channel:
    """一个频道. name 用于渲染前缀; members 是允许看到/写入的 player_id 集合."""

    name: str
    members: list[str] = field(default_factory=list)
    events: list[ChannelEvent] = field(default_factory=list)

    # ------------------------------------------ 工厂方法 (常见频道)

    @classmethod
    def board(cls, all_player_ids: Iterable[str]) -> "Channel":
        """全场公开频道."""
        return cls(name="board", members=list(all_player_ids))

    @classmethod
    def wolf_chat(cls, wolf_ids: Iterable[str]) -> "Channel":
        """狼夜聊."""
        return cls(name="wolf_chat", members=list(wolf_ids))

    @classmethod
    def lovers(cls, a: str, b: str) -> "Channel":
        """情侣 (后续才会用上)."""
        return cls(name="lovers", members=[a, b])

    # ------------------------------------------ 读

    def is_visible_to(self, player_id: str) -> bool:
        return player_id in self.members

    def all_events(self) -> list[ChannelEvent]:
        return list(self.events)

    def read_until(
        self,
        round: int,
        kinds: Optional[Iterable[EventKind]] = None,
    ) -> list[ChannelEvent]:
        kind_set = set(kinds) if kinds else None
        out: list[ChannelEvent] = []
        for e in self.events:
            if e.round > round:
                break
            if kind_set is None or e.kind in kind_set:
                out.append(e)
        return out

    # ------------------------------------------ 写 (便捷方法, 语义化)

    def append(self, event: ChannelEvent) -> None:
        self.events.append(event)

    def append_speech(self, round: int, speaker: str, text: str) -> None:
        self.append(ChannelEvent("speech", round, {"speaker": speaker, "text": text}))

    def append_last_words(
        self, round: int, speaker: str, text: str, reason: str
    ) -> None:
        self.append(
            ChannelEvent(
                "last_words",
                round,
                {"speaker": speaker, "text": text, "reason": reason},
            )
        )

    def append_vote(self, round: int, voter: str, target: str) -> None:
        self.append(ChannelEvent("vote", round, {"voter": voter, "target": target}))

    def append_vote_result(
        self,
        round: int,
        loser: Optional[str],
        tally: dict[str, int],
        abstentions: Optional[list[str]] = None,
    ) -> None:
        self.append(
            ChannelEvent(
                "vote_result",
                round,
                {
                    "loser": loser,
                    "tally": dict(tally),
                    "abstentions": list(abstentions or []),
                },
            )
        )

    def append_night_result(self, round: int, deaths: list[str]) -> None:
        self.append(ChannelEvent("night_result", round, {"deaths": list(deaths)}))

    def append_phase_change(self, round: int, phase: str) -> None:
        self.append(ChannelEvent("phase_change", round, {"phase": phase}))

    def append_game_end(self, round: int, winner: str) -> None:
        self.append(ChannelEvent("game_end", round, {"winner": winner}))
