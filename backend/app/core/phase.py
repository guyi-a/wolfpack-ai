"""Phase — 群体级别的流程单元.

一个 Phase 自包含一段"完整阶段" (狼夜杀/预言家查验/女巫用药/白天发言/白天投票...),
内部串调 sub-agents 的 act(), 最后返回 PhaseResult.

Phase 由 God (supervisor) 通过 run_phase 工具触发, 也可以直接被 Judge / CLI 调用测试.

设计原则:
  - Phase 本身不写 channel (它不知道当前是不是要广播); 由调用方拿 PhaseResult 后决定
  - 例外: 在 phase 内部由 sub-agent 产生的发言会被即时写入 phase 关联的 channel
    (e.g. 狼发言要立即让别的狼看到), 这是 phase 的内部机制
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from app.agent.base import Player
from app.agent.roles.seer import Seer
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.game_state import GameState


@dataclass
class PhaseResult:
    """Phase 执行结果. 不同 phase 在 payload 里塞各自的关键字段."""

    name: str
    payload: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 工具: 投票收集器
# ---------------------------------------------------------------------------


class VoteCollector:
    """阶段内的投票收集器.

    - 同一 voter 多次投票以最后一次为准
    - 不投票 = 弃权 (调用方在 phase 结束时统计 alive_voters - voted_voters)
    - 平票 = winner() 返回 None (调用方按规则处理, e.g. 白天投票平票 = 平安天)
    """

    def __init__(self) -> None:
        self._votes: dict[str, str] = {}

    def collect(self, voter_id: str, target_id: str) -> None:
        self._votes[voter_id] = target_id

    def tally(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for target in self._votes.values():
            counts[target] = counts.get(target, 0) + 1
        return counts

    def abstentions(self, all_voter_ids: Sequence[str]) -> list[str]:
        """从 alive voter id 列表里, 挑出那些没投票的 (弃权)."""
        voted = set(self._votes.keys())
        return [pid for pid in all_voter_ids if pid not in voted]

    def winner(self, tie_breaker: Optional[Sequence[str]] = None) -> Optional[str]:
        """得票最多者.

        平票时:
          - 若 tie_breaker 未给, 返回 None (例如白天投票 -> 平安天)
          - 若 tie_breaker 给了, 按 tie_breaker 顺序优先 (e.g. 狼夜杀人用此兜底)
        无任何票 → None
        """
        counts = self.tally()
        if not counts:
            return None
        max_votes = max(counts.values())
        leaders = [pid for pid, c in counts.items() if c == max_votes]
        if len(leaders) == 1:
            return leaders[0]
        if tie_breaker is None:
            return None
        for pid in tie_breaker:
            if pid in leaders:
                return pid
        return None

    def raw_votes(self) -> dict[str, str]:
        return dict(self._votes)


# ---------------------------------------------------------------------------
# WolfNightPhase
# ---------------------------------------------------------------------------


class WolfNightPhase:
    """狼夜阶段.

    流程:
      - 每只狼按存活顺序轮流 act, 给的 task 提示"商量 + 投票决定刀谁"
      - 狼调 cast_vote 工具时, 投票被 VoteCollector 收集
      - 每只狼的回复 text 同时写入 wolf_chat channel, 让下一只狼能看到
      - 跑完 rounds 轮后, 取 VoteCollector.winner() 作为今晚刀的目标

    Args:
        wolves: 活着的狼 Player 列表 (Wolf 实例). 内部不创建 wolf, 用户传入.
        wolf_chat: 狼频道 (用于狼之间发言可见性).
        game_round: 当前是第几轮 (用于事件 round 字段).
        alive_ids: 当前所有活着的玩家 id 列表 (含狼自己). 用来限定刀的目标范围,
                   防止模型瞎刀已死或不存在的玩家.
        rounds: 狼之间讨论多少轮 (每轮所有狼各发言一次). 默认 2.
    """

    def __init__(
        self,
        wolves: Sequence[Wolf],
        wolf_chat: Channel,
        game_round: int,
        alive_ids: Sequence[str],
        rounds: int = 2,
    ) -> None:
        self.wolves = list(wolves)
        self.wolf_chat = wolf_chat
        self.game_round = game_round
        self.alive_ids = list(alive_ids)
        self.rounds = rounds

    async def run(self) -> PhaseResult:
        if not self.wolves:
            return PhaseResult(
                name="wolf_night",
                payload={"kill_target": None, "votes": {}, "reason": "no_wolves_alive"},
            )

        collector = VoteCollector()
        # 重绑每只狼的 on_vote 到本 phase 的 collector
        # (Wolf 在 init 时绑了一次, 这里换成 phase 的, 因为 phase 是新建的)
        self._rebind_vote_callbacks(collector)

        for round_idx in range(1, self.rounds + 1):
            for wolf in self.wolves:
                task = self._build_task(round_idx, wolf, collector)
                speech = await wolf.act(task, round=self.game_round)
                self.wolf_chat.append_speech(self.game_round, wolf.player_id, speech)

        tie_breaker = [w.player_id for w in self.wolves]
        kill_target = collector.winner(tie_breaker=tie_breaker)
        return PhaseResult(
            name="wolf_night",
            payload={
                "kill_target": kill_target,
                "votes": collector.raw_votes(),
                "tally": collector.tally(),
            },
        )

    # ---------------------------------------------------------------- helpers

    def _rebind_vote_callbacks(self, collector: VoteCollector) -> None:
        """重新创建并替换 wolf.tools 里的 cast_vote, 让它把投票推给 collector."""
        from app.agent.roles.wolf import make_cast_vote_tool

        for wolf in self.wolves:
            new_tool = make_cast_vote_tool(collector.collect, voter_id=wolf.player_id)
            wolf.tools = [new_tool]
            # set_model 会用新 tools 重编译 agent
            wolf.set_model(wolf.model_name)

    def _build_task(
        self,
        round_idx: int,
        wolf: Wolf,
        collector: VoteCollector,
    ) -> str:
        # 候选目标 = 活着 且 不是狼自己 (狼通常不刀同伴)
        wolf_ids = {w.player_id for w in self.wolves}
        candidates = [pid for pid in self.alive_ids if pid not in wolf_ids]

        current_votes = collector.raw_votes()
        my_prev = current_votes.get(wolf.player_id)
        ctx_lines = [
            f"现在是第 {self.game_round} 夜, 狼人讨论第 {round_idx}/{self.rounds} 轮.",
            f"你是 {wolf.player_id} 号狼人.",
            f"可刀目标 (活着的非狼): {', '.join(f'{pid}号' for pid in candidates)}.",
        ]
        if current_votes:
            tally = collector.tally()
            ctx_lines.append(f"当前狼队投票分布: {tally}.")
        if my_prev:
            ctx_lines.append(f"你上一轮投了 {my_prev}号, 可改投也可保持.")
        if round_idx < self.rounds:
            ctx_lines.append(
                "请在 [狼频道] 发表你的看法 (短句), "
                "并调 cast_vote(target_id) 投票. target_id 必须是纯数字 (例如 '5', 不要带'号'字), "
                "后面还会有商量轮."
            )
        else:
            ctx_lines.append(
                "这是最后一轮, 请确认你的投票. 必须调 cast_vote(target_id) 决定今晚刀谁. "
                "target_id 必须是纯数字 (例如 '5', 不要带'号'字), 必须从上述候选里选."
            )
        return " ".join(ctx_lines)


# ---------------------------------------------------------------------------
# SeerNightPhase
# ---------------------------------------------------------------------------


class SeerNightPhase:
    """预言家夜阶段: 派一次任务给 Seer 自决查验.

    Args:
        seer: Seer 实例 (持有 check_player 工具).
        game_round: 当前轮数.
        alive_ids: 活着的玩家 id (排除已死).
    """

    def __init__(
        self,
        seer: Seer,
        game_round: int,
        alive_ids: Sequence[str],
    ) -> None:
        self.seer = seer
        self.game_round = game_round
        self.alive_ids = list(alive_ids)

    async def run(self) -> PhaseResult:
        result_box: dict[str, str] = {}

        def on_check(target_id: str, result: str) -> None:
            result_box["target"] = target_id
            result_box["result"] = result

        # 重绑 check_player 工具的 on_check
        from app.agent.roles.seer import make_check_player_tool

        new_tool = make_check_player_tool(self.seer.identities, on_check=on_check)
        self.seer.tools = [new_tool]
        self.seer.set_model(self.seer.model_name)

        # 候选 = 活着 且 不是自己
        candidates = [pid for pid in self.alive_ids if pid != self.seer.player_id]
        task = (
            f"现在是第 {self.game_round} 夜. 你是预言家 {self.seer.player_id} 号, "
            f"可查验候选 (活着的非己): {', '.join(f'{p}号' for p in candidates)}. "
            f"请选择一名玩家用 check_player(target_id) 查验. target_id 必须从候选里选."
        )
        await self.seer.act(task, round=self.game_round)

        return PhaseResult(
            name="seer_night",
            payload={
                "target": result_box.get("target"),
                "result": result_box.get("result"),
            },
        )


# ---------------------------------------------------------------------------
# WitchNightPhase
# ---------------------------------------------------------------------------


class WitchNightPhase:
    """女巫夜阶段.

    流程:
      - 告知 Witch 今晚被狼刀的人 (kill_target, 可能为 None — 狼没刀人)
      - Witch 自决调 use_potion('save') / use_potion('poison', target) / 啥也不调
      - 工具回调 (on_potion) 把动作收集到 PhaseResult

    Args:
        witch: Witch 实例 (持有 use_potion 工具 + PotionState).
        game_round: 当前轮数.
        kill_target: 今晚被狼刀的人 (None 表示狼没成功刀).
        alive_ids: 活着的玩家 id (排除已死).
    """

    def __init__(
        self,
        witch: Witch,
        game_round: int,
        kill_target: Optional[str],
        alive_ids: Sequence[str],
    ) -> None:
        self.witch = witch
        self.game_round = game_round
        self.kill_target = kill_target
        self.alive_ids = list(alive_ids)

    async def run(self) -> PhaseResult:
        actions: dict[str, Optional[str]] = {"save": None, "poison": None}

        def on_potion(potion_type: str, target_id: Optional[str]) -> None:
            actions[potion_type] = target_id or "_self_"

        # 重绑 use_potion 工具
        from app.agent.roles.witch import make_use_potion_tool

        new_tool = make_use_potion_tool(self.witch.potion_state, on_potion)
        self.witch.tools = [new_tool]
        self.witch.set_model(self.witch.model_name)

        kill_desc = f"{self.kill_target}号" if self.kill_target else "(狼没刀人或刀空了)"
        state = self.witch.potion_state
        potion_status = (
            f"解药剩余: {'有' if state.save_available else '无'}, "
            f"毒药剩余: {'有' if state.poison_available else '无'}"
        )
        candidates = ", ".join(f"{p}号" for p in self.alive_ids)
        task = (
            f"现在是第 {self.game_round} 夜. 你是女巫 {self.witch.player_id} 号. "
            f"今晚狼人刀的目标是: {kill_desc}. "
            f"{potion_status}. "
            f"活着的玩家: {candidates}. "
            f"请决定: 用解药救人 (use_potion('save'))、用毒药毒人 (use_potion('poison', target_id))、"
            f"或者啥也不做 (不调工具). 注意: 如果两瓶药都没有, 直接不调."
        )
        await self.witch.act(task, round=self.game_round)

        # 保存动作 (后续 phase 把它 apply 到 GameState.night_actions)
        save_done = actions["save"] is not None
        poison_target = actions["poison"] if actions["poison"] not in (None, "_self_") else None
        return PhaseResult(
            name="witch_night",
            payload={
                "save": save_done,
                "poison_target": poison_target,
            },
        )


# ---------------------------------------------------------------------------
# NightAnnouncePhase (纯代码, 不调 LLM)
# ---------------------------------------------------------------------------


class NightAnnouncePhase:
    """夜间结算公告. 把 night_actions 落到 GameState, 写 board.

    需要前置 phase 已经把:
      - wolf_kill_target / witch_save / witch_poison_target
    填到 state.night_actions 里.
    """

    def __init__(self, state: GameState, board: Channel) -> None:
        self.state = state
        self.board = board

    async def run(self) -> PhaseResult:
        deaths = self.state.settle_night()
        self.board.append_night_result(self.state.round, deaths)
        return PhaseResult(
            name="night_announce",
            payload={"deaths": list(deaths)},
        )


# ---------------------------------------------------------------------------
# LastWordsPhase — 死者留遗言
# ---------------------------------------------------------------------------


class LastWordsPhase:
    """让指定的死者发表遗言, 写 board.

    Args:
        dying: 即将/已经出局的 Player. Phase 不真改 GameState (那是公告/投票 phase 干的),
               只是让此 player 自由发言.
        board: 全场频道.
        game_round: 当前轮数.
        reason: 'killed_at_night' (夜间被刀) 或 'voted_out' (白天被票出).
        word_limit: 软上限.
    """

    def __init__(
        self,
        dying: Player,
        board: Channel,
        game_round: int,
        reason: str,
        word_limit: int = 60,
    ) -> None:
        self.dying = dying
        self.board = board
        self.game_round = game_round
        self.reason = reason
        self.word_limit = word_limit

    async def run(self) -> PhaseResult:
        reason_zh = {
            "killed_at_night": "昨晚被狼刀",
            "voted_out": "刚被投票放逐",
        }.get(self.reason, "出局")
        task = (
            f"现在是第 {self.game_round} 天. 你 ({self.dying.player_id}号) {reason_zh}, 即将出局. "
            f"按惯例你可以留下一段遗言 ({self.word_limit} 字以内). "
            "如果你是神职 (预言家 / 女巫) 这里通常会公开身份并传递信息 (查验结果 / 药情况); "
            "如果你是村民可以表达对场上的看法; 如果你是狼可以选择继续装好人混淆视听. "
            "请发表遗言."
        )
        text = await self.dying.act(task, round=self.game_round)
        self.board.append_last_words(self.game_round, self.dying.player_id, text, self.reason)
        return PhaseResult(
            name="last_words",
            payload={"speaker": self.dying.player_id, "text": text, "reason": self.reason},
        )


# ---------------------------------------------------------------------------
# DaySpeechPhase — 所有活人按 id 顺序发言, 写 board
# ---------------------------------------------------------------------------


class DaySpeechPhase:
    """白天发言阶段. 按 player_id 顺序每人说一句, 写入 board.

    Args:
        speakers: 活着的 Player 列表 (任何 Role 都行). 顺序就是发言顺序.
        board: 全场频道.
        game_round: 当前轮数.
        word_limit: 一句话上限提示 (软约束, 给 prompt 用).
    """

    def __init__(
        self,
        speakers: Sequence[Player],
        board: Channel,
        game_round: int,
        word_limit: int = 40,
    ) -> None:
        self.speakers = list(speakers)
        self.board = board
        self.game_round = game_round
        self.word_limit = word_limit

    async def run(self) -> PhaseResult:
        speeches: list[tuple[str, str]] = []
        n = len(self.speakers)
        for i, speaker in enumerate(self.speakers, start=1):
            task = (
                f"现在是第 {self.game_round} 天白天发言. "
                f"你是 {speaker.player_id} 号. "
                f"发言顺序是 {i}/{n}. "
                f"请综合昨晚公告和已有发言, 用一段话 ({self.word_limit} 字以内) 表态."
            )
            text = await speaker.act(task, round=self.game_round)
            self.board.append_speech(self.game_round, speaker.player_id, text)
            speeches.append((speaker.player_id, text))
        return PhaseResult(
            name="day_speech",
            payload={"speeches": speeches},
        )


# ---------------------------------------------------------------------------
# DayVotePhase — 全员 cast_vote, 写 board, 决出 loser
# ---------------------------------------------------------------------------


class DayVotePhase:
    """白天投票阶段.

    流程:
      - 给每个 voter 重绑 cast_vote.on_vote 到本 phase 的 VoteCollector
      - 按 id 顺序每人 act 一次任务"请投票"
      - 投票事件写 board (voter -> target)
      - 跑完后 VoteCollector.winner() 给出出局者, vote_result 写 board

    Args:
        voters: 活着的 Player 列表 (任何 Role 都行).
        board: 全场频道.
        game_round: 当前轮数.
        alive_ids: 候选 = 活着的所有人 (含自己; 是否允许自投由 prompt 说).
    """

    def __init__(
        self,
        voters: Sequence[Player],
        board: Channel,
        game_round: int,
        alive_ids: Sequence[str],
    ) -> None:
        self.voters = list(voters)
        self.board = board
        self.game_round = game_round
        self.alive_ids = list(alive_ids)

    async def run(self) -> PhaseResult:
        collector = VoteCollector()
        self._rebind_vote_callbacks(collector)

        # 第一步: 所有 voter 顺序调 cast_vote, 但不把投票写 board
        # (避免后置 voter 通过 board / messages 看到前面的票引发跟票)
        for voter in self.voters:
            task = self._build_task(voter)
            await voter.act(task, round=self.game_round)

        # 第二步: 全部投完后, 按 voter 顺序 append 投票事件到 board
        # 此时是同时亮票, 顺序只是写入顺序, 玩家在投票时是看不到的
        for voter in self.voters:
            target = collector.raw_votes().get(voter.player_id)
            if target is not None:
                self.board.append_vote(self.game_round, voter.player_id, target)

        tally = collector.tally()
        all_ids = [v.player_id for v in self.voters]
        abstentions = collector.abstentions(all_ids)
        loser = collector.winner(tie_breaker=None)
        self.board.append_vote_result(self.game_round, loser, tally, abstentions)

        return PhaseResult(
            name="day_vote",
            payload={
                "votes": collector.raw_votes(),
                "tally": tally,
                "loser": loser,
                "abstentions": abstentions,
            },
        )

    # ---------------------------------------------------------------- helpers

    def _rebind_vote_callbacks(self, collector: VoteCollector) -> None:
        """重新创建并替换每个 voter 的 cast_vote 工具, 让它把投票推给 collector.

        前提: 每个 Player 子类都把 cast_vote 放在 self.tools 里 (Wolf/Villager/Seer/Witch 都遵守).
        """
        from app.agent.roles.wolf import make_cast_vote_tool

        for voter in self.voters:
            new_vote = make_cast_vote_tool(collector.collect, voter_id=voter.player_id)
            new_tools = []
            replaced = False
            for t in voter.tools:
                # 用名字识别原 cast_vote 工具
                if getattr(t, "name", "") == "cast_vote":
                    new_tools.append(new_vote)
                    replaced = True
                else:
                    new_tools.append(t)
            if not replaced:
                new_tools.append(new_vote)
            voter.tools = new_tools
            voter.set_model(voter.model_name)  # 重编译 agent

    def _build_task(self, voter: Player) -> str:
        candidates = ", ".join(f"{pid}号" for pid in self.alive_ids if pid != voter.player_id)
        return (
            f"现在是第 {self.game_round} 天投票阶段. 你是 {voter.player_id} 号. "
            f"投票是同时进行的, 你看不到别人投了谁, 也不能跟票. "
            f"候选 (活着的非己): {candidates}. "
            f"请基于已知信息, 用 cast_vote(target_id) 投一票. "
            f"target_id 必须是纯数字字符串 (例如 '5', 不要带'号'字), 必须从候选里选. "
            f"\n规则提示: 默认你应该投票, 平票会导致无人出局 (平安天). "
            f"只有当你确实无法判断时, 才可以弃权 (本回合不调任何工具直接回复); "
            f"经常弃权会让其他玩家怀疑你划水或偷狼."
        )
