"""把一局对局的完整数据 (game + players + events + histories) 渲染成 markdown 复盘文档.

供 GET /games/{id}/export?format=markdown 用. 也方便用户分享一局对局.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, Iterable

from app.models.game import Game, GameEvent, GamePlayer, PlayerPrivateHistory


_ROLE_CN = {
    "wolf": "狼人",
    "seer": "预言家",
    "witch": "女巫",
    "villager": "村民",
}

_CAUSE_CN = {
    "killed_at_night": "夜里被刀",
    "voted_out": "白天投票出局",
    "poisoned": "女巫毒杀",
}

_PHASE_CN = {
    "night_start": "夜晚开始",
    "wolf_night": "狼人行动",
    "seer_night": "预言家行动",
    "witch_night": "女巫行动",
    "night_announce": "天亮公告",
    "day_start": "白天开始",
    "day_speech": "白天发言",
    "day_vote": "白天投票",
    "last_words_voted": "出局遗言",
    "last_words_killed": "夜死遗言",
}


def render_markdown(
    game: Game,
    players: Iterable[GamePlayer],
    events: Iterable[GameEvent],
    histories: dict[str, list[PlayerPrivateHistory]],
) -> str:
    """渲染一局完整对局成 markdown."""
    players = list(players)
    events = list(events)

    parts: list[str] = []
    parts.append(_render_header(game, players))
    parts.append(_render_events(events, players))
    parts.append(_render_histories(histories, players))
    return "\n\n".join(parts).rstrip() + "\n"


# ----------------------------------------------------------------------------
# 头部 (元信息 + 玩家配置 + 结果)
# ----------------------------------------------------------------------------


def _render_header(game: Game, players: list[GamePlayer]) -> str:
    lines: list[str] = []
    lines.append(f"# 对局 #{game.id} · 复盘")
    lines.append("")

    started = _fmt_time(game.started_at)
    ended = _fmt_time(game.ended_at)
    duration = _fmt_duration(game.started_at, game.ended_at)
    winner_cn = {"good": "好人胜", "wolf": "狼人胜"}.get(game.winner or "", "未结")

    lines.append("## 元信息")
    lines.append("")
    lines.append(f"- **状态**: {game.status}")
    lines.append(f"- **结果**: {winner_cn}")
    lines.append(f"- **轮数**: {game.rounds_played}")
    lines.append(f"- **God 模型**: `{game.god_model}`")
    lines.append(f"- **开始**: {started}")
    lines.append(f"- **结束**: {ended}")
    lines.append(f"- **用时**: {duration}")
    if game.error_message:
        lines.append(f"- **错误**: {game.error_message}")
    lines.append("")

    lines.append("## 玩家配置")
    lines.append("")
    lines.append("| 座位 | 角色 | 模型 | 终态 |")
    lines.append("|------|------|------|------|")
    for p in players:
        role_cn = _ROLE_CN.get(p.role, p.role)
        if p.alive:
            fate = "存活"
        else:
            cause = _CAUSE_CN.get(p.death_cause or "", p.death_cause or "未知")
            fate = f"R{p.died_at_round} {cause}"
        lines.append(
            f"| {p.player_id} 号 | {role_cn} | `{p.model}` | {fate} |"
        )
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 事件流 (按 round 分章, round 内按 phase 分节)
# ----------------------------------------------------------------------------


def _render_events(events: list[GameEvent], players: list[GamePlayer]) -> str:
    if not events:
        return "## 对局过程\n\n(无事件)"

    # name 解析: "1" → "1 号 (狼人/deepseek-v4-pro)"
    name_of = {p.player_id: _player_short(p) for p in players}

    lines: list[str] = ["## 对局过程"]
    rounds: dict[int, list[GameEvent]] = {}
    for e in events:
        rounds.setdefault(e.round, []).append(e)

    for r in sorted(rounds):
        lines.append("")
        lines.append(f"### Round {r}")
        # 按 phase 分组: 用 phase_change 事件切片
        current_phase = "未知阶段"
        for e in rounds[r]:
            payload = e.payload or {}
            if e.kind == "phase_change":
                phase = str(payload.get("phase", ""))
                current_phase = _PHASE_CN.get(phase, phase)
                lines.append("")
                lines.append(f"#### {current_phase}")
                continue
            lines.append(_render_event_line(e, name_of))
    return "\n".join(lines)


def _render_event_line(
    e: GameEvent, name_of: dict[str, str]
) -> str:
    payload = e.payload or {}
    ch_mark = "🐺" if e.channel == "wolf_chat" else ""

    if e.kind == "speech":
        speaker = str(payload.get("speaker", "?"))
        text = str(payload.get("text", "")).strip()
        return f"- {ch_mark} **{name_of.get(speaker, speaker)}**: {text}"

    if e.kind == "last_words":
        speaker = str(payload.get("speaker", "?"))
        text = str(payload.get("text", "")).strip()
        reason = str(payload.get("reason", ""))
        reason_cn = _CAUSE_CN.get(reason, reason)
        return f"- ⚰️ **{name_of.get(speaker, speaker)} 遗言** ({reason_cn}): {text}"

    if e.kind == "vote":
        voter = str(payload.get("voter", "?"))
        target = str(payload.get("target", "?"))
        verb = "投" if e.channel == "board" else "刀"
        return f"- 🗳️ {name_of.get(voter, voter)} {verb} → {name_of.get(target, target)}"

    if e.kind == "vote_result":
        loser = payload.get("loser")
        tally = payload.get("tally", {}) or {}
        abstentions = payload.get("abstentions", []) or []
        tally_str = ", ".join(
            f"{name_of.get(t, t)}: {n}" for t, n in tally.items()
        )
        loser_str = (
            name_of.get(str(loser), str(loser)) if loser else "**平票 (无人出局)**"
        )
        abs_str = (
            f" · 弃权 {', '.join(name_of.get(a, a) for a in abstentions)}"
            if abstentions
            else ""
        )
        return f"- 📊 **投票结果**: {loser_str} · {tally_str}{abs_str}"

    if e.kind == "night_result":
        deaths = payload.get("deaths", []) or []
        if not deaths:
            return "- 🌅 **天亮公告**: 昨夜平安无事"
        names = ", ".join(name_of.get(d, d) for d in deaths)
        return f"- 🌅 **天亮公告**: {names} 倒下"

    if e.kind == "game_end":
        winner = payload.get("winner", "?")
        winner_cn = {"good": "好人胜", "wolf": "狼人胜"}.get(str(winner), str(winner))
        return f"- 🏁 **对局结束**: {winner_cn}"

    # fallback
    return f"- *{e.kind}*: `{json.dumps(payload, ensure_ascii=False)}`"


# ----------------------------------------------------------------------------
# 内心戏 (按 player 列每 round 的 thinking / tool / text)
# ----------------------------------------------------------------------------


def _render_histories(
    histories: dict[str, list[PlayerPrivateHistory]],
    players: list[GamePlayer],
) -> str:
    if not histories:
        return "## 内心戏\n\n(无私有 history)"

    role_of = {p.player_id: p.role for p in players}
    model_of = {p.player_id: p.model for p in players}

    lines: list[str] = ["## 内心戏 (上帝视角)"]
    # player_id 按 "1"/"2"/.../"god" 排; god 排最后
    ordered = sorted(
        histories.keys(),
        key=lambda pid: (pid == "god", _natural_key(pid)),
    )
    for pid in ordered:
        entries = histories[pid]
        if not entries:
            continue
        if pid == "god":
            title = "上帝 (God)"
            sub = f"`{model_of.get('god', '?')}`"
        else:
            role_cn = _ROLE_CN.get(role_of.get(pid, ""), role_of.get(pid, ""))
            title = f"{pid} 号 · {role_cn}"
            sub = f"`{model_of.get(pid, '?')}`"
        lines.append("")
        lines.append(f"### {title} · {sub}")
        for block in _fold_history(entries):
            lines.append("")
            lines.append(f"**Round {block['round']}**")
            if block["thinking"]:
                lines.append("")
                lines.append("> 💭 " + _quote_multiline(block["thinking"]))
            for tc in block["tool_calls"]:
                args_str = ", ".join(
                    f"{k}={json.dumps(v, ensure_ascii=False)}"
                    for k, v in (tc.get("args") or {}).items()
                )
                result = tc.get("result")
                result_str = f" → `{result}`" if result is not None else ""
                lines.append(f"- 🔧 `{tc.get('name')}({args_str})`{result_str}")
            if block["text"]:
                lines.append("")
                lines.append("> 💬 " + _quote_multiline(block["text"]))

    return "\n".join(lines)


def _fold_history(entries: list[PlayerPrivateHistory]) -> list[dict[str, Any]]:
    """把一个 player 的 history entries 按 act (role=user 边界) 折叠成块.

    跟前端 foldHistory 同构, 但简化一些.
    """
    out: list[dict[str, Any]] = []
    bucket: list[PlayerPrivateHistory] = []
    bucket_round = 0

    def flush() -> None:
        if not bucket:
            return
        thinking_parts: list[str] = []
        text_parts: list[str] = []
        tools: list[dict[str, Any]] = []
        id_to_rec: dict[str, dict[str, Any]] = {}
        for e in bucket:
            if e.role == "assistant":
                if e.thinking:
                    thinking_parts.append(e.thinking)
                if e.text:
                    text_parts.append(e.text)
                for tc in (e.tool_calls or []):
                    rec = {
                        "name": tc.get("name", ""),
                        "args": tc.get("args", {}),
                        "result": None,
                    }
                    tools.append(rec)
                    if tc.get("id"):
                        id_to_rec[tc["id"]] = rec
            elif e.role == "tool":
                rec = id_to_rec.get(e.tool_call_id)
                if rec is not None:
                    rec["result"] = e.text
        if thinking_parts or text_parts or tools:
            out.append({
                "round": bucket_round,
                "thinking": "\n".join(thinking_parts),
                "text": "\n".join(text_parts),
                "tool_calls": tools,
            })

    for e in entries:
        if e.role == "user":
            flush()
            bucket = []
            bucket_round = e.round
        else:
            bucket.append(e)
    flush()
    return out


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------


def _player_short(p: GamePlayer) -> str:
    role_cn = _ROLE_CN.get(p.role, p.role)
    model_tail = p.model.split("/")[-1]
    return f"{p.player_id} 号 ({role_cn}/{model_tail})"


def _fmt_time(t: dt.datetime | None) -> str:
    if t is None:
        return "—"
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _fmt_duration(start: dt.datetime | None, end: dt.datetime | None) -> str:
    if start is None or end is None:
        return "—"
    secs = int((end - start).total_seconds())
    if secs < 60:
        return f"{secs}s"
    return f"{secs // 60}m {secs % 60}s"


def _quote_multiline(s: str) -> str:
    return s.replace("\n", "\n> ")


def _natural_key(pid: str) -> tuple[int, str]:
    try:
        return (0, f"{int(pid):05d}")
    except ValueError:
        return (1, pid)
