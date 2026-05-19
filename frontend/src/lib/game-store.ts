import { create } from "zustand";

import type {
  ChannelEvent,
  InnerView,
  PlayerState,
  PrivateHistoryEntry,
  PrivateHistoryOut,
  SseEvent,
} from "@/lib/types";

interface LiveTokens {
  thinking: string;
  text: string;
}

interface PlayerStateInfo {
  state: PlayerState;
  tool_name?: string;
}

interface GameStore {
  events: ChannelEvent[];
  playerStates: Record<string, PlayerStateInfo>;
  innerViews: Record<string, InnerView>;   // player_id -> 最近一次完整 inner_view
  pastInners: InnerView[];                 // 全量历史 (含所有 player 所有 round)
  liveTokens: Record<string, LiveTokens>;  // act 进行中的实时累积
  active: string | null;                   // 最近 thinking/tool_calling 的 player_id
  ended: boolean;
  endReason: string | null;
  apply: (e: SseEvent) => void;
  loadReplay: (histories: PrivateHistoryOut[]) => void;
  reset: () => void;
}

const INITIAL = {
  events: [] as ChannelEvent[],
  playerStates: {} as Record<string, PlayerStateInfo>,
  innerViews: {} as Record<string, InnerView>,
  pastInners: [] as InnerView[],
  liveTokens: {} as Record<string, LiveTokens>,
  active: null as string | null,
  ended: false,
  endReason: null as string | null,
};

export const useGameStore = create<GameStore>((set) => ({
  ...INITIAL,

  apply: (e: SseEvent) =>
    set((s) => {
      // stream_end
      if (e.kind === "stream_end") {
        return { ended: true, endReason: e.payload?.reason ?? null };
      }

      // player_state
      if (e.kind === "player_state") {
        const { player_id, state, tool_name } = e.payload;
        const playerStates = {
          ...s.playerStates,
          [player_id]: { state, tool_name },
        };
        let active = s.active;
        let liveTokens = s.liveTokens;
        if (state === "thinking" || state === "tool_calling" || state === "speaking") {
          active = player_id;
          if (state === "thinking" && !liveTokens[player_id]) {
            liveTokens = { ...liveTokens, [player_id]: { thinking: "", text: "" } };
          }
        } else if (state === "idle") {
          // 不清 liveTokens, 让 inner_view 来覆盖
        }
        return { playerStates, active, liveTokens };
      }

      // token_chunk
      if (e.kind === "token_chunk") {
        const { player_id, phase, delta } = e.payload;
        const prev = s.liveTokens[player_id] ?? { thinking: "", text: "" };
        const next: LiveTokens = {
          thinking: phase === "thinking" ? prev.thinking + delta : prev.thinking,
          text: phase === "text" ? prev.text + delta : prev.text,
        };
        return { liveTokens: { ...s.liveTokens, [player_id]: next } };
      }

      // inner_view (act 结束的汇总)
      if (e.kind === "inner_view") {
        const view: InnerView = {
          player_id: e.payload.player_id,
          round: e.payload.round,
          state: "idle",
          thinking: e.payload.thinking,
          tool_calls: e.payload.tool_calls,
          text: e.payload.text,
        };
        return {
          innerViews: { ...s.innerViews, [view.player_id]: view },
          pastInners: [...s.pastInners, view],
          // act 结束, 清掉这个 player 的 liveTokens
          liveTokens: Object.fromEntries(
            Object.entries(s.liveTokens).filter(([pid]) => pid !== view.player_id),
          ),
        };
      }

      // 业务事件 (有 seq + channel)
      if ("seq" in e && "channel" in e) {
        // 简单去重 (按 seq)
        if (s.events.some((x) => x.seq === e.seq)) return {};
        const events = [...s.events, e].sort((a, b) => a.seq - b.seq);
        return { events };
      }

      return {};
    }),

  reset: () => set({ ...INITIAL }),

  loadReplay: (histories: PrivateHistoryOut[]) =>
    set(() => {
      const allInners: InnerView[] = [];
      const latestByPlayer: Record<string, InnerView> = {};
      for (const h of histories) {
        if (h.player_id === "god") continue;  // 复盘视图不展示 god 自言自语
        const inners = foldHistory(h.player_id, h.entries);
        allInners.push(...inners);
        const last = inners[inners.length - 1];
        if (last) latestByPlayer[h.player_id] = last;
      }
      return {
        pastInners: allInners,
        innerViews: latestByPlayer,
      };
    }),
}));

/** 把私有 history entries 按 act 边界 (role="user") 切分, 每段折叠成一个 InnerView. */
function foldHistory(playerId: string, entries: PrivateHistoryEntry[]): InnerView[] {
  const out: InnerView[] = [];
  let bucket: PrivateHistoryEntry[] = [];
  let bucketRound = 0;

  const flush = () => {
    if (bucket.length === 0) return;
    const view = foldOneAct(playerId, bucketRound, bucket);
    if (view) out.push(view);
    bucket = [];
  };

  for (const e of entries) {
    if (e.role === "user") {
      flush();
      bucketRound = e.round;
      // user 本身不进 bucket (那只是任务描述)
    } else {
      bucket.push(e);
    }
  }
  flush();
  return out;
}

/** 单个 act 内的 entries (不含 user) → 一个 InnerView, 跟后端 _publish_inner_view 同构. */
function foldOneAct(
  playerId: string,
  round: number,
  entries: PrivateHistoryEntry[],
): InnerView | null {
  const thinkingParts: string[] = [];
  const textParts: string[] = [];
  const toolRecords: Array<{ name: string; args: Record<string, unknown>; result: string | null }> = [];
  const idToRec = new Map<string, { name: string; args: Record<string, unknown>; result: string | null }>();

  for (const e of entries) {
    if (e.role === "assistant") {
      if (e.thinking) thinkingParts.push(e.thinking);
      if (e.text) textParts.push(e.text);
      const tcs = (e.tool_calls ?? []) as Array<{ id?: string; name?: string; args?: Record<string, unknown> }>;
      for (const tc of tcs) {
        const rec = {
          name: tc.name ?? "",
          args: tc.args ?? {},
          result: null as string | null,
        };
        toolRecords.push(rec);
        if (tc.id) idToRec.set(tc.id, rec);
      }
    } else if (e.role === "tool") {
      const rec = idToRec.get(e.tool_call_id);
      if (rec) rec.result = e.text;
    }
  }

  if (thinkingParts.length === 0 && textParts.length === 0 && toolRecords.length === 0) return null;

  return {
    player_id: playerId,
    round,
    state: "idle",
    thinking: thinkingParts.join("\n"),
    tool_calls: toolRecords,
    text: textParts.join("\n"),
  };
}
