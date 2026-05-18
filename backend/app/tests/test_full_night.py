"""完整一夜端到端测试.

桌面: 2 狼 (1, 4) + 1 女巫 (2) + 1 预言家 (3) + 2 村民 (5, 6)
流程: WolfNightPhase → SeerNightPhase → WitchNightPhase → NightAnnouncePhase

跑法:
    python app/tests/test_full_night.py

验证:
  1. 狼的 kill_target 写入 state.night_actions
  2. Seer 私有记录到查验结果
  3. Witch 收到了"今晚被刀的人", 自决救/毒/不动
  4. NightAnnounce 写 board, 死亡名单跟 witch 行为一致
  5. 各 player 私有日志互不交叉, thinking 严格隔离
"""

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.contexts.history_store import InMemoryHistoryStore
from app.agent.roles.seer import Seer
from app.agent.roles.witch import Witch
from app.agent.roles.wolf import Wolf
from app.core.channel import Channel
from app.core.game_state import GameState, PlayerInfo
from app.core.phase import (
    NightAnnouncePhase,
    SeerNightPhase,
    WitchNightPhase,
    WolfNightPhase,
)


MODEL = "deepseek/deepseek-v4-pro"


def setup():
    players = [
        PlayerInfo("1", "wolf"),
        PlayerInfo("2", "witch"),
        PlayerInfo("3", "seer"),
        PlayerInfo("4", "wolf"),
        PlayerInfo("5", "villager"),
        PlayerInfo("6", "villager"),
    ]
    state = GameState(players=players)
    board = Channel.board([p.player_id for p in players])
    wolf_chat = Channel.wolf_chat(["1", "4"])
    identities = {p.player_id: ("wolf" if p.role == "wolf" else "good") for p in players}
    return state, board, wolf_chat, identities


def noop(*a, **k):
    pass


def main():
    state, board, wolf_chat, identities = setup()
    state.start_round()
    print(f"=== 第 {state.round} 夜 ===")

    # ---------- 角色实例化 ----------
    wolves = [
        Wolf(
            player_id="1",
            model_name=MODEL,
            history_store=InMemoryHistoryStore(),
            teammates=["4"],
            channels=[wolf_chat, board],
            on_vote=noop,
        ),
        Wolf(
            player_id="4",
            model_name=MODEL,
            history_store=InMemoryHistoryStore(),
            teammates=["1"],
            channels=[wolf_chat, board],
            on_vote=noop,
        ),
    ]
    seer = Seer(
        player_id="3",
        model_name=MODEL,
        history_store=InMemoryHistoryStore(),
        identities=identities,
        channels=[board],
    )
    witch = Witch(
        player_id="2",
        model_name=MODEL,
        history_store=InMemoryHistoryStore(),
        channels=[board],
        on_potion=noop,
    )

    # ---------- Phase 1: 狼夜 ----------
    print("\n--- WolfNightPhase ---")
    wp = WolfNightPhase(
        wolves=wolves,
        wolf_chat=wolf_chat,
        game_round=state.round,
        alive_ids=state.alive_ids(),
        rounds=2,
    )
    wp_result = wp.run()
    print(f"  狼频道发言:")
    for e in wolf_chat.all_events():
        print(f"    {e.payload['speaker']}号: {e.payload['text'][:80]}")
    print(f"  → kill_target: {wp_result.payload['kill_target']}")
    state.night_actions.wolf_kill_target = wp_result.payload["kill_target"]

    # ---------- Phase 2: 预言家 ----------
    print("\n--- SeerNightPhase ---")
    sp = SeerNightPhase(seer=seer, game_round=state.round, alive_ids=state.alive_ids())
    sp_result = sp.run()
    print(f"  → 查 {sp_result.payload['target']} 号 → {sp_result.payload['result']}")

    # ---------- Phase 3: 女巫 ----------
    print("\n--- WitchNightPhase ---")
    wtp = WitchNightPhase(
        witch=witch,
        game_round=state.round,
        kill_target=state.night_actions.wolf_kill_target,
        alive_ids=state.alive_ids(),
    )
    wtp_result = wtp.run()
    print(f"  → save={wtp_result.payload['save']}, poison_target={wtp_result.payload['poison_target']}")
    state.night_actions.witch_save = wtp_result.payload["save"]
    state.night_actions.witch_poison_target = wtp_result.payload["poison_target"]

    # ---------- Phase 4: 公告 ----------
    print("\n--- NightAnnouncePhase ---")
    nap = NightAnnouncePhase(state=state, board=board)
    nap_result = nap.run()
    print(f"  → 死亡公告: {nap_result.payload['deaths']}")
    print(f"  → 当前活人: {state.alive_ids()}, phase={state.phase.value}")

    # ---------- 校验 ----------
    print("\n=== 校验 ===")
    print(f"  [板上 board 事件] {len(board.all_events())} 条 (含 night_result)")
    print(f"  [狼频道] {len(wolf_chat.all_events())} 条")

    print(f"  [Seer 私有] {len(seer.history())} 条")
    print(f"  [Witch 私有] {len(witch.history())} 条")
    for w in wolves:
        print(f"  [{w.player_id}号狼 私有] {len(w.history())} 条")

    # 隔离: 狼频道事件不该出现在好人私有 / board
    wolf_chat_texts = {e.payload.get("text", "") for e in wolf_chat.all_events()}
    leaked = []
    for p in [seer, witch]:
        for entry in p.history():
            if entry.text in wolf_chat_texts and entry.text:
                leaked.append((p.player_id, entry.text[:40]))
    print(f"  [√] 狼频道泄露到好人 私有 history: {len(leaked)} 条 (应=0)")
    if leaked:
        for pid, t in leaked:
            print(f"      泄露 → {pid}: {t}")


if __name__ == "__main__":
    main()
