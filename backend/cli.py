"""Wolfpack 命令行入口.

两种模式:

  默认 (本地直跑):
      python cli.py
      python cli.py --model pa/claude-opus-4-7
    内部直接 setup_game + play_game, 不需要起 server.
    边跑边打印每条事件 (挂 print sink).

  watch 模式 (走 server SSE):
      python cli.py --watch
    需要先在另一个终端起 server: uvicorn app.server:app --port 8080
    内部调 POST /games + POST /games/{id}/start, 然后 SSE 订阅事件流.
    跟将来 Electron app 同源路径.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# 兼容 `python backend/cli.py` 和 `python -m backend.cli` 两种跑法
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.god import God, GodContext
from app.agent.roles.seer import Seer
from app.agent.roles.villager import Villager
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel, ChannelEvent
from app.core.game_state import GameState, PlayerInfo
from app.core.judge import play_game


# 6 人板默认配置
DEFAULT_LAYOUT = [
    ("1", "wolf"),
    ("2", "witch"),
    ("3", "seer"),
    ("4", "wolf"),
    ("5", "villager"),
    ("6", "villager"),
]

DEFAULT_MODELS = {
    "god": "deepseek/deepseek-v4-pro",
    "1": "deepseek/deepseek-v4-pro",
    "2": "pa/claude-opus-4-7",
    "3": "zai-org/glm-5.1",
    "4": "xiaomimimo/mimo-v2.5-pro",
    "5": "deepseek/deepseek-v4-flash",
    "6": "deepseek/deepseek-v4-pro",
}


# ============================================================================
# 渲染 (本地 + watch 共用)
# ============================================================================


def render_event(channel: str, kind: str, round_num: int, payload: dict) -> str | None:
    """把一条事件渲染成可读的一行 (返回 None 表示跳过)."""
    if channel == "wolf_chat":
        if kind == "speech":
            return f"  🐺 [狼频道 r{round_num}] {payload['speaker']}号: {payload['text']}"
        return None

    # board
    if kind == "phase_change":
        ph = payload.get("phase", "")
        labels = {
            "night_start": "🌑 ───── 第 {r} 夜 ─────",
            "wolf_night": "  🐺 狼人睁眼",
            "seer_night": "  🔮 预言家睁眼",
            "witch_night": "  🧪 女巫睁眼",
            "day_start": "☀️ ───── 第 {r} 天 ─────",
            "night_announce": "  📢 夜结算公告",
            "last_words_killed": "  ⚰️ (死者遗言)",
            "day_speech": "  💬 自由发言阶段",
            "day_vote": "  🗳️ 投票阶段",
            "last_words_voted": "  ⚰️ (出局者遗言)",
        }
        tmpl = labels.get(ph)
        if tmpl:
            return tmpl.format(r=round_num)
        return None
    if kind == "night_result":
        deaths = payload.get("deaths") or []
        if deaths:
            who = "、".join(f"{d}号" for d in deaths)
            return f"  📢 公告: {who} 死亡"
        return f"  📢 公告: 平安夜, 无人死亡"
    if kind == "last_words":
        reason = "夜死" if payload.get("reason") == "killed_at_night" else "票出"
        return f"  ⚰️ [{reason} 遗言] {payload['speaker']}号: {payload['text']}"
    if kind == "speech":
        return f"  💬 [{payload['speaker']}号]: {payload['text']}"
    if kind == "vote":
        return f"     🗳️  {payload['voter']}号 → {payload['target']}号"
    if kind == "vote_result":
        ab = payload.get("abstentions") or []
        ab_str = f", 弃权 {ab}" if ab else ""
        loser = payload.get("loser")
        tally = payload.get("tally", {})
        if loser:
            return f"  📊 投票结果: {loser}号 出局  票数 {tally}{ab_str}"
        return f"  📊 投票结果: 平票, 无人出局  票数 {tally}{ab_str}"
    if kind == "game_end":
        return f"\n  🏁 对局结束: {payload['winner']} 方胜利!\n"
    return None


def print_event(channel: str, kind: str, round_num: int, payload: dict) -> None:
    line = render_event(channel, kind, round_num, payload)
    if line:
        print(line, flush=True)


# ============================================================================
# 模式 1: 本地直跑 (默认)
# ============================================================================


def _noop(*args, **kwargs):
    pass


def setup_local_game(models: dict) -> tuple:
    """models = {player_id: model, "god": model}."""
    players_info = [PlayerInfo(pid, role) for pid, role in DEFAULT_LAYOUT]
    state = GameState(players=players_info)
    board = Channel.board([p.player_id for p in players_info])
    wolf_chat = Channel.wolf_chat([p.player_id for p in players_info if p.role == "wolf"])
    identities = {p.player_id: ("wolf" if p.role == "wolf" else "good") for p in players_info}

    # 给两个 channel 都挂 print sink, 边跑边显示
    board.add_sink(lambda ch, ev: print_event(ch.name, ev.kind, ev.round, ev.payload))
    wolf_chat.add_sink(lambda ch, ev: print_event(ch.name, ev.kind, ev.round, ev.payload))

    players = {}
    for pid, role in DEFAULT_LAYOUT:
        model = models.get(pid, "deepseek/deepseek-v4-pro")
        if role == "wolf":
            teammates = [other for other, r in DEFAULT_LAYOUT if r == "wolf" and other != pid]
            players[pid] = Wolf(
                pid, model, InMemoryHistoryStore(),
                teammates=teammates, channels=[wolf_chat, board], on_vote=_noop,
            )
        elif role == "witch":
            players[pid] = Witch(
                pid, model, InMemoryHistoryStore(), channels=[board], on_potion=_noop,
            )
        elif role == "seer":
            players[pid] = Seer(
                pid, model, InMemoryHistoryStore(), identities=identities, channels=[board],
            )
        else:
            players[pid] = Villager(pid, model, InMemoryHistoryStore(), channels=[board])

    ctx = GodContext(state=state, board=board, wolf_chat=wolf_chat, players=players)
    god = God("god", models.get("god", "deepseek/deepseek-v4-pro"),
              InMemoryHistoryStore(), ctx=ctx)
    return god, state


async def run_local(args) -> None:
    models = {pid: args.model for pid, _ in DEFAULT_LAYOUT}
    models["god"] = args.model

    print("=" * 76)
    print("              W O L F P A C K   ·   AI 狼人杀")
    print("=" * 76)
    print(f"  模型     : {args.model} (全员)")
    print(f"  最大轮数 : {args.max_rounds}")
    print(f"  桌面     : {DEFAULT_LAYOUT}")
    print("=" * 76)
    print()

    god, state = setup_local_game(models)

    t0 = time.time()
    result = await play_game(god, state, max_rounds=args.max_rounds)
    elapsed = time.time() - t0

    print()
    print("=" * 76)
    print(f"  结束: winner={result['winner']}, "
          f"轮数={result['rounds_played']}, "
          f"耗时={elapsed:.1f}s")
    print("=" * 76)


# ============================================================================
# 模式 2: watch (走 server SSE)
# ============================================================================


def run_watch(args) -> None:
    base = args.server.rstrip("/")

    # 1. healthz
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=3) as r:
            r.read()
    except Exception as e:
        print(f"❌ 连不上 server {base}: {e}")
        print(f"   先在另一个终端起 server:")
        print(f"     cd backend && venv/bin/python -m uvicorn app.server:app --port 8080")
        sys.exit(1)

    # 2. 拿默认配置
    print(f"[watch] 从 {base}/games/default-config 取默认配置...")
    with urllib.request.urlopen(f"{base}/games/default-config") as r:
        config = json.loads(r.read())

    print("=" * 76)
    print("              W O L F P A C K   ·   AI 狼人杀  (watch 模式)")
    print("=" * 76)
    print(f"  server   : {base}")
    print(f"  god      : {config['god_model']}")
    print(f"  players  :")
    for p in config["players"]:
        print(f"    {p['player_id']}号 {p['role']:8s} → {p['model']}")
    print("=" * 76)
    print()

    # 3. POST /games
    req = urllib.request.Request(
        f"{base}/games",
        data=json.dumps(config).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        game = json.loads(r.read())
    game_id = game["id"]
    print(f"[watch] 建好 game {game_id}, 启动后台跑...")

    # 4. POST /games/{id}/start
    req = urllib.request.Request(
        f"{base}/games/{game_id}/start?max_rounds={args.max_rounds}",
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        r.read()
    print(f"[watch] 已 start. 开始订阅事件流...\n")

    # 5. SSE 订阅, 边跑边渲染
    t0 = time.time()
    stream_url = f"{base}/games/{game_id}/stream"
    with urllib.request.urlopen(stream_url) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if not line.startswith("data: "):
                continue
            payload_str = line[len("data: "):]
            try:
                event = json.loads(payload_str)
            except Exception:
                continue
            if event.get("kind") == "stream_end":
                print(f"\n[watch] stream 结束: {event.get('reason')}")
                break
            print_event(
                event.get("channel", "?"),
                event.get("kind", ""),
                event.get("round", 0),
                event.get("payload", {}),
            )

    elapsed = time.time() - t0
    # 6. 拿最终结果
    with urllib.request.urlopen(f"{base}/games/{game_id}") as r:
        final = json.loads(r.read())
    print()
    print("=" * 76)
    print(f"  结束: winner={final['winner']}, rounds={final['rounds_played']}, "
          f"耗时 (从 SSE 连接起) ≈ {elapsed:.1f}s")
    print(f"  GET {base}/games/{game_id} 看完整详情")
    print("=" * 76)


# ============================================================================
# main
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Wolfpack — 跑一局狼人杀 (6 人板默认)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="走 server SSE 模式 (需要先起 server). 默认在本进程内直跑.",
    )
    parser.add_argument(
        "--server",
        default="http://127.0.0.1:8080",
        help="watch 模式连接的 server URL (默认 http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--model",
        default="deepseek/deepseek-v4-pro",
        help="本地模式下全员共用的 LLM (默认: deepseek-v4-pro). watch 模式使用 server 的默认配置",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=8,
        help="最大轮数兜底 (默认 8)",
    )
    args = parser.parse_args()

    if args.watch:
        run_watch(args)
    else:
        import asyncio
        asyncio.run(run_local(args))


if __name__ == "__main__":
    main()
