"""Judge — 对局生命周期管理.

极简: while not game.is_over(): god.act('继续主持本轮'). 兜底超时.

God 内部走 LLM, 自决调用 run_phase / check_winner. Judge 只负责"再让 God 跑一次"
和"对局确实结束时停止".
"""

from __future__ import annotations

from app.agent.roles.god import God
from app.core.game_state import GameState


def play_game(god: God, state: GameState, max_rounds: int = 10) -> dict:
    """跑一局直到 game over.

    Args:
        god: 已配置好工具集与 ctx 的 God 实例.
        state: GameState 实例 (god.ctx.state 共享同一个).
        max_rounds: 兜底最大轮数, 超过强制结束 (防 God LLM 卡死).

    Returns:
        {winner, rounds_played, ended_normally}
    """
    iterations = 0
    while not state.is_over() and iterations < max_rounds:
        iterations += 1
        god.act(
            f"继续主持本对局. 当前是第 {state.round} 轮 (或第一夜还未开始). "
            "请按 prompt 中的 phase 顺序调用工具推进. "
            "完成本轮所有 phase 后或胜负已分时停止调用工具."
        )

    return {
        "winner": state.winner(),
        "rounds_played": state.round,
        "ended_normally": state.is_over(),
        "iterations": iterations,
    }
