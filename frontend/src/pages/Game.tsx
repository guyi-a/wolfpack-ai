import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router";
import useSWR, { useSWRConfig } from "swr";

import { TopBar } from "@/components/TopBar";
import { PlayerCard } from "@/components/PlayerCard";
import { EventStream } from "@/components/EventStream";
import { InnerViewPanel } from "@/components/InnerViewPanel";
import { PhaseStepper } from "@/components/PhaseStepper";
import { ReplayScrubber } from "@/components/ReplayScrubber";
import { getGame, getAllHistories, apiUrl } from "@/lib/api";
import { useGameStore } from "@/lib/game-store";
import { useEventSource } from "@/lib/useEventSource";
import type { ChannelEvent, InnerView, Player } from "@/lib/types";

export default function GamePage() {
  const { id } = useParams<{ id: string }>();
  const gameId = id ?? "";
  const { mutate } = useSWRConfig();

  // 对局元信息 (players / status); 跑中轮询拿状态, 结束后停
  const {
    data: game,
    error: gameErr,
    isLoading: gameLoading,
  } = useSWR(gameId ? ["game", gameId] : null, () => getGame(gameId), {
    refreshInterval: (latest) =>
      latest && (latest.status === "ended" || latest.status === "aborted") ? 0 : 3000,
  });

  // 对局变为终态时, 戳一下 Home 那边的 list/stats cache, 让用户返回首页立刻看到最新胜率
  useEffect(() => {
    if (game?.status === "ended" || game?.status === "aborted") {
      mutate("games-list");
      mutate("games-stats");
    }
  }, [game?.status, mutate]);

  // SSE store
  const apply = useGameStore((s) => s.apply);
  const reset = useGameStore((s) => s.reset);
  const loadReplay = useGameStore((s) => s.loadReplay);
  const events = useGameStore((s) => s.events);
  const playerStates = useGameStore((s) => s.playerStates);
  const liveTokens = useGameStore((s) => s.liveTokens);
  const pastInners = useGameStore((s) => s.pastInners);
  const sseActive = useGameStore((s) => s.active);
  const ended = useGameStore((s) => s.ended);
  const replayCursor = useGameStore((s) => s.replayCursor);
  const setReplayCursor = useGameStore((s) => s.setReplayCursor);

  // 切换对局时清掉旧 store
  useEffect(() => {
    reset();
  }, [gameId, reset]);

  useEventSource(
    gameId ? apiUrl(`/games/${gameId}/stream`) : null,
    apply,
  );

  // 进页面就拉一次 history (含 running 局): 用于跨刷新/重进恢复 inner_view.
  // 跑中也行 — 后端每次 act 结束都增量写 player_private_history.
  useEffect(() => {
    if (!gameId) return;
    getAllHistories(gameId)
      .then(loadReplay)
      .catch((err) => console.warn("加载 history 失败:", err));
  }, [gameId, loadReplay]);

  const [pinnedId, setPinnedId] = useState<string | null>(null);

  // 复盘模式: status=ended 时启用 replayCursor 截断数据
  const isReplay = game?.status === "ended" || game?.status === "aborted";
  const effectiveCursor = isReplay ? replayCursor : null;

  // cursor 截断的事件流 / 内心戏
  const visibleEvents = useMemo(
    () =>
      effectiveCursor === null
        ? events
        : events.filter((e) => e.round <= effectiveCursor),
    [events, effectiveCursor],
  );
  const visibleInners = useMemo(
    () =>
      effectiveCursor === null
        ? pastInners
        : pastInners.filter((iv) => iv.round <= effectiveCursor),
    [pastInners, effectiveCursor],
  );

  // 所有已发生的 round 编号 (从 events 推导, 升序去重)
  const allRounds = useMemo(() => {
    const set = new Set<number>();
    for (const e of events) set.add(e.round);
    return [...set].sort((a, b) => a - b);
  }, [events]);

  // 从事件流推导 round / phase
  const { currentRound, currentPhase } = useMemo(
    () => derivePhase(visibleEvents),
    [visibleEvents],
  );

  // 从事件流推导 deadIds (跑中 game_player.alive 滞后, 用事件流兜底)
  const deadInfo = useMemo(() => deriveDeaths(visibleEvents), [visibleEvents]);

  // 从公开事件反推最近一个有动作的 player (兜底 sseActive 在重进/重连后为空)
  const lastActor = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const p = events[i].payload as Record<string, unknown>;
      const candidate = p.speaker ?? p.voter;
      if (typeof candidate === "string") return candidate;
    }
    return null;
  }, [events]);

  if (gameErr) return <ErrorBox msg={`加载失败: ${gameErr.message}`} />;
  if (gameLoading || !game) return <LoadingBox />;

  // active: pinned > SSE active > 事件流最近 actor > 第一个 player
  const activeId = pinnedId ?? sseActive ?? lastActor ?? game.players[0]?.player_id ?? "1";
  const activePlayer: Player =
    game.players.find((p) => p.player_id === activeId) ?? game.players[0];

  // 合并 game.players + 事件流推导的死亡 (后者更实时)
  const playersWithDeaths: Player[] = game.players.map((p) => {
    const dead = deadInfo[p.player_id];
    if (dead) {
      return { ...p, alive: false, died_at_round: dead.round, death_cause: dead.cause };
    }
    return p;
  });

  // 同步修正 activePlayer 显示
  const activePlayerWithDeath = playersWithDeaths.find((p) => p.player_id === activePlayer.player_id) ?? activePlayer;

  // 该 player 全部历史 act (复盘时被 cursor 截断)
  const playerViews = visibleInners.filter((iv) => iv.player_id === activePlayer.player_id);
  // 当前 live act (复盘模式禁用)
  const liveView = isReplay
    ? null
    : buildLiveView(activePlayer, currentRound, liveTokens, playerStates);

  const togglePin = () => {
    if (pinnedId) setPinnedId(null);
    else setPinnedId(activePlayer.player_id);
  };

  const currentToolName: Record<string, string | undefined> = {};
  Object.entries(playerStates).forEach(([pid, info]) => {
    currentToolName[pid] = info.tool_name;
  });

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-bg text-ivory">
      <TopBar
        gameId={game.id}
        round={currentRound}
        phase={currentPhase}
        streaming={!ended && game.status === "running"}
        showExport={isReplay}
      />

      <div className="grid grid-cols-[320px_1fr_460px] flex-1 min-h-0">
        <div className="border-r border-line px-6 py-8 overflow-y-auto min-h-0">
          <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-5">
            PLAYERS · {game.players.length} SEATS
            <span className="flex-1 h-px bg-line-soft" />
          </div>
          <div className="flex flex-col gap-2.5">
            {playersWithDeaths.map((p) => (
              <PlayerCard
                key={p.player_id}
                player={p}
                state={playerStates[p.player_id]?.state ?? "idle"}
                toolName={currentToolName[p.player_id]}
                active={p.player_id === activePlayer.player_id}
                onClick={() => setPinnedId(p.player_id)}
              />
            ))}
          </div>
        </div>

        <div className="border-r border-line min-w-0 min-h-0 overflow-hidden">
          <EventStream events={visibleEvents} currentRound={currentRound} />
        </div>

        <div className="min-h-0 overflow-hidden">
          <InnerViewPanel
            player={activePlayerWithDeath}
            views={playerViews}
            liveView={liveView}
            pinned={pinnedId !== null}
            onTogglePin={togglePin}
          />
        </div>
      </div>

      {isReplay ? (
        <ReplayScrubber
          rounds={allRounds}
          cursor={replayCursor}
          onChange={setReplayCursor}
          winner={game.winner}
        />
      ) : (
        <PhaseStepper
          currentPhase={currentPhase}
          pinnedPlayerId={pinnedId}
          followMode={pinnedId === null}
          onResetFollow={() => setPinnedId(null)}
        />
      )}
    </div>
  );
}

function buildLiveView(
  player: Player,
  round: number,
  liveTokens: Record<string, { thinking: string; text: string }>,
  playerStates: Record<string, { state: string; tool_name?: string }>,
): InnerView | null {
  const pid = player.player_id;
  const live = liveTokens[pid];
  const stateInfo = playerStates[pid];
  if (!live || (!live.thinking && !live.text)) return null;
  return {
    player_id: pid,
    round,
    state: (stateInfo?.state as InnerView["state"]) ?? "thinking",
    tool_name: stateInfo?.tool_name,
    thinking: live.thinking,
    tool_calls: [],
    text: live.text,
  };
}

function derivePhase(events: ChannelEvent[]): {
  currentRound: number;
  currentPhase: string;
} {
  let currentRound = 1;
  let currentPhase = "night_start";
  for (const e of events) {
    if (e.round > currentRound) currentRound = e.round;
    if (e.kind === "phase_change" && typeof e.payload.phase === "string") {
      currentPhase = e.payload.phase;
    }
    if (e.kind === "game_end") {
      currentPhase = "ended";
    }
  }
  return { currentRound, currentPhase };
}

/** 从公开事件流推导死亡: night_result.deaths + vote_result.loser. */
function deriveDeaths(
  events: ChannelEvent[],
): Record<string, { round: number; cause: string }> {
  const out: Record<string, { round: number; cause: string }> = {};
  for (const e of events) {
    if (e.channel !== "board") continue;
    if (e.kind === "night_result") {
      const deaths = (e.payload.deaths as string[] | undefined) ?? [];
      for (const pid of deaths) {
        if (!out[pid]) out[pid] = { round: e.round, cause: "killed_at_night" };
      }
    } else if (e.kind === "vote_result") {
      const loser = e.payload.loser as string | null | undefined;
      if (loser && !out[loser]) out[loser] = { round: e.round, cause: "voted_out" };
    }
  }
  return out;
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-bg gap-4">
      <p className="font-mono text-[12px] text-blood tracking-[0.1em]">⚠ {msg}</p>
      <Link to="/" className="font-mono text-[10px] text-smoke hover:text-ivory tracking-[0.1em]">
        ← 返回首页
      </Link>
    </div>
  );
}

function LoadingBox() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-bg">
      <p className="font-mono text-[11px] text-smoke tracking-[0.2em] uppercase">loading game...</p>
    </div>
  );
}
