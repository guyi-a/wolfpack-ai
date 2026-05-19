"""God — 上帝视角的 supervisor 角色.

God 跟其他 Player 同构 (LLM + 工具集), 但工具粒度是 Phase 而非单 player.
通过 prompt 强约束顺序: wolf_night → seer_night → witch_night → night_announce →
last_words_killed → day_speech → day_vote → last_words_voted → 下一轮.

God 持有 GodContext (含 GameState + channels + 全员 player 实例), 工具用闭包拿到这些.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from langchain_core.tools import tool

from app.agent.base import Player
from app.agent.contexts.history_store import HistoryStore
from app.agent.roles.seer import Seer
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.game_state import GameState
from app.core.phase import (
    DaySpeechPhase,
    DayVotePhase,
    LastWordsPhase,
    NightAnnouncePhase,
    SeerNightPhase,
    WitchNightPhase,
    WolfNightPhase,
)


GOD_SYSTEM_PROMPT = """\
你是这局狼人杀的上帝 (主持人 / 裁判). 你不参与博弈, 只负责调度整局流程.

== 工具集 ==
- get_round_state(): 查询当前状态 (轮数, 阶段, 活着的人, 今天已死的人).
- run_phase(name): 跑一个阶段, 返回结果摘要. 合法 name:
    "wolf_night"         — 狼夜商量 + 投票决定刀谁
    "seer_night"         — 预言家查验
    "witch_night"        — 女巫救/毒决策
    "night_announce"     — 夜间结算 + 公告
    "day_speech"         — 全员白天发言
    "day_vote"           — 全员投票
    "last_words_voted"   — 让今天被票出的玩家留遗言 (若有)
- announce(text): 在公开频道发一条公告 (你可选用, e.g. 宣布警长). 第一版可不用.
- check_winner(): 检查胜负. 返回 {is_over, winner}.

== 流程 (严格按顺序调用 run_phase) ==
每一轮的固定顺序:
    1. run_phase("wolf_night")
    2. run_phase("seer_night")
    3. run_phase("witch_night")
    4. run_phase("night_announce")    ← 这里会结算并公告夜里死亡
    5. check_winner — 如果 is_over 直接停止 (回复 '对局结束', 不再调工具).
    6. run_phase("day_speech")
    7. run_phase("day_vote")          ← 平票则无人出局
    8. 如果第 7 步返回的 loser 不为 None:
         run_phase("last_words_voted")
    9. check_winner — 同上.
    10. 重复 1~9 (进入下一夜).

== 重要规则 ==
- 你是机械调度员, 不参与博弈, 不发表对玩家身份的评论. 一切都通过 run_phase 工具完成.
- 每个 run_phase 调用后, 你看到工具返回的摘要后, 不需要复述; 直接调下一个 phase.
- 当 check_winner 返回 is_over=true, 你回复 "对局结束: <winner>方胜利", 不再调用任何工具.
- 夜间死亡者 (被刀 / 被毒) 不留遗言. 只有白天被票出的玩家通过 last_words_voted 留遗言.
"""


@dataclass
class GodContext:
    """God 的上下文 — 工具闭包通过它访问对局.

    God 自己也是个 Player, 但工具用闭包绑定这些引用, 不污染 prompt.
    """

    state: GameState
    board: Channel
    wolf_chat: Channel
    players: dict[str, Player]   # player_id -> Player 实例
    # 记录最近一次 phase 结果, 主要给后续 phase 引用
    last_phase_result: dict = None


def _build_god_tools(ctx: GodContext):
    """构造 God 的 4 个工具, 全部用闭包持有 ctx."""

    @tool
    def get_round_state() -> dict:
        """查询当前对局状态."""
        s = ctx.state
        return {
            "round": s.round,
            "phase": s.phase.value,
            "alive": s.alive_ids(),
            "deaths_today": list(s.deaths_announced_today),
            "is_over": s.is_over(),
        }

    @tool
    async def run_phase(name: str) -> dict:
        """跑一个阶段. name ∈ {wolf_night, seer_night, witch_night, night_announce, day_speech, day_vote, last_words_voted}."""
        s = ctx.state
        if name == "wolf_night":
            # 若进入新一轮, start_round (从 ENDED 不会到这, is_over 会被 check_winner 截掉)
            if s.phase.name in ("ENDED",):
                return {"error": "game already ended"}
            if s.round == 0 or s.phase.name == "DAY_VOTE":
                s.start_round()
            # 第一个夜阶段, 同时发"夜晚开始"信号
            ctx.board.append_phase_change(s.round, "night_start")
            ctx.board.append_phase_change(s.round, "wolf_night")
            wolves = [
                p for p in ctx.players.values() if isinstance(p, Wolf) and s.get(p.player_id).alive
            ]
            phase = WolfNightPhase(
                wolves=wolves,
                wolf_chat=ctx.wolf_chat,
                game_round=s.round,
                alive_ids=s.alive_ids(),
                rounds=2,
            )
            result = await phase.run()
            s.night_actions.wolf_kill_target = result.payload["kill_target"]
            ctx.last_phase_result = result.payload
            return {"kill_target": result.payload["kill_target"]}

        if name == "seer_night":
            seer = next((p for p in ctx.players.values() if isinstance(p, Seer) and s.get(p.player_id).alive), None)
            if seer is None:
                return {"skipped": "no seer alive"}
            ctx.board.append_phase_change(s.round, "seer_night")
            phase = SeerNightPhase(seer=seer, game_round=s.round, alive_ids=s.alive_ids())
            result = await phase.run()
            ctx.last_phase_result = result.payload
            return {"target": result.payload.get("target"), "result": result.payload.get("result")}

        if name == "witch_night":
            witch = next((p for p in ctx.players.values() if isinstance(p, Witch) and s.get(p.player_id).alive), None)
            if witch is None:
                return {"skipped": "no witch alive"}
            ctx.board.append_phase_change(s.round, "witch_night")
            phase = WitchNightPhase(
                witch=witch,
                game_round=s.round,
                kill_target=s.night_actions.wolf_kill_target,
                alive_ids=s.alive_ids(),
            )
            result = await phase.run()
            s.night_actions.witch_save = result.payload["save"]
            s.night_actions.witch_poison_target = result.payload["poison_target"]
            ctx.last_phase_result = result.payload
            return {"save": result.payload["save"], "poison_target": result.payload["poison_target"]}

        if name == "night_announce":
            # 夜结束, 进入白天: 先发"白天开始"信号, 再走 NightAnnouncePhase 发死亡公告
            ctx.board.append_phase_change(s.round, "day_start")
            ctx.board.append_phase_change(s.round, "night_announce")
            phase = NightAnnouncePhase(state=s, board=ctx.board)
            result = await phase.run()
            ctx.last_phase_result = result.payload
            return {"deaths": result.payload["deaths"]}

        if name == "day_speech":
            ctx.board.append_phase_change(s.round, "day_speech")
            speakers = [ctx.players[pid] for pid in s.alive_ids() if pid in ctx.players]
            phase = DaySpeechPhase(speakers=speakers, board=ctx.board, game_round=s.round)
            result = await phase.run()
            ctx.last_phase_result = result.payload
            return {"speech_count": len(result.payload["speeches"])}

        if name == "day_vote":
            ctx.board.append_phase_change(s.round, "day_vote")
            voters = [ctx.players[pid] for pid in s.alive_ids() if pid in ctx.players]
            phase = DayVotePhase(
                voters=voters,
                board=ctx.board,
                game_round=s.round,
                alive_ids=s.alive_ids(),
            )
            result = await phase.run()
            ctx.last_phase_result = result.payload
            s.settle_vote(result.payload["loser"])
            return {
                "loser": result.payload["loser"],
                "tally": result.payload["tally"],
                "abstentions": result.payload["abstentions"],
            }

        if name == "last_words_voted":
            loser = s.eliminated_today
            if not loser or loser not in ctx.players:
                return {"skipped": "no one voted out"}
            ctx.board.append_phase_change(s.round, "last_words_voted")
            phase = LastWordsPhase(
                dying=ctx.players[loser],
                board=ctx.board,
                game_round=s.round,
                reason="voted_out",
            )
            r = await phase.run()
            return {"speaker": loser, "text": r.payload["text"]}

        return {"error": f"unknown phase: {name!r}"}

    @tool
    def announce(text: str) -> str:
        """以上帝身份在 board 发一条公告."""
        ctx.board.append_speech(ctx.state.round, "上帝", text)
        return "已公告"

    @tool
    def check_winner() -> dict:
        """检查胜负. 返回 {is_over, winner}."""
        is_over = ctx.state.is_over()
        winner = ctx.state.winner() if is_over else None
        if is_over and winner:
            ctx.board.append_game_end(ctx.state.round, winner)
        return {"is_over": is_over, "winner": winner}

    return [get_round_state, run_phase, announce, check_winner]


class God(Player):
    """上帝. 不参与博弈, 只通过工具调度 Phase. 不入任何 channel (它有全视角, 不需要)."""

    def __init__(
        self,
        player_id: str,
        model_name: str,
        history_store: HistoryStore,
        ctx: GodContext,
        **kwargs,
    ) -> None:
        self.ctx = ctx
        tools = _build_god_tools(ctx)
        super().__init__(
            player_id=player_id,
            model_name=model_name,
            system_prompt=GOD_SYSTEM_PROMPT,
            history_store=history_store,
            tools=tools,
            channels=[],   # God 不订阅 channel, 用 get_round_state 主动拉
            **kwargs,
        )
