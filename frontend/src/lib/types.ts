/** 对局公开事件 (channel + kind + payload), 跟后端 SSE 一致 */
export type ChannelName = "board" | "wolf_chat" | "lovers";

export type Role = "wolf" | "seer" | "witch" | "villager";

export type PlayerState = "thinking" | "tool_calling" | "speaking" | "idle";

/** 业务事件 — 跟后端 SSE / game_event 表 schema 对齐 */
export interface ChannelEvent {
  seq: number;
  channel: ChannelName;
  kind:
    | "phase_change"
    | "speech"
    | "last_words"
    | "vote"
    | "vote_result"
    | "night_result"
    | "game_end";
  round: number;
  payload: Record<string, unknown>;
}

/** SSE 推过来的流式事件 (player_state / token_chunk / inner_view) */
export interface PlayerStateEvent {
  kind: "player_state";
  payload: {
    player_id: string;
    state: PlayerState;
    tool_name?: string;
  };
}

export interface TokenChunkEvent {
  kind: "token_chunk";
  payload: {
    player_id: string;
    phase: "thinking" | "text";
    delta: string;
  };
}

export interface InnerViewEvent {
  kind: "inner_view";
  payload: {
    player_id: string;
    round: number;
    thinking: string;
    tool_calls: Array<{ name: string; args: Record<string, unknown>; result: string | null }>;
    text: string;
  };
}

export interface StreamEnd {
  kind: "stream_end";
  payload?: { reason: string };
}

export type SseEvent =
  | (ChannelEvent & { game_id?: number })
  | PlayerStateEvent
  | TokenChunkEvent
  | InnerViewEvent
  | StreamEnd;

/** 玩家 (合并配置 + 终态) */
export interface Player {
  player_id: string;
  role: Role;
  model: string;
  alive: boolean;
  died_at_round?: number | null;
  death_cause?: string | null;
}

/** 对局摘要 (列表用) */
export interface GameSummary {
  id: number;
  status: "pending" | "running" | "ended" | "aborted";
  winner: "good" | "wolf" | null;
  rounds_played: number;
  god_model: string;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface GameDetail extends GameSummary {
  config_json: Record<string, unknown>;
  error_message: string | null;
  players: Player[];
}

/** 某 player 的完整私有 history (复盘) */
export interface PrivateHistoryEntry {
  seq: number;
  role: string;
  text: string;
  thinking: string;
  tool_calls: unknown[];
  tool_call_id: string;
  name: string;
  round: number;
}

export interface PrivateHistoryOut {
  player_id: string;
  entries: PrivateHistoryEntry[];
}

/** 内心戏 (player_state + 累积的 thinking/tools/text) */
export interface InnerView {
  player_id: string;
  round: number;
  state: PlayerState;
  tool_name?: string;
  thinking: string;
  tool_calls: Array<{ name: string; args: Record<string, unknown>; result: string | null }>;
  text: string;
}
