/** 后端 API 调用封装.
 *
 * dev (vite): API_BASE = "/api", Vite proxy 把前缀 rewrite 掉转发到 :8080
 * prod (electron 加载本地 HTML): 没 proxy, 走 preload 注入的
 *   window.__WOLFPACK__.apiBase (端口由 Electron Main 动态找, 8081 起递增).
 *   兜底用 http://127.0.0.1:8080 (preload 没注入时 — 实际不该发生).
 *
 * 暴露 apiUrl() 给非 fetch 场景用 (EventSource SSE).
 */

import type {
  ChannelEvent,
  GameDetail,
  GameSummary,
  PrivateHistoryOut,
} from "@/lib/types";

function resolveApiBase(): string {
  if (!import.meta.env.PROD) return "/api";
  const injected =
    typeof window !== "undefined" ? window.__WOLFPACK__?.apiBase : undefined;
  return injected || "http://127.0.0.1:8080";
}

const API = resolveApiBase();

/** 拼后端 URL. path 以 / 开头, 如 "/games/1/stream". */
export const apiUrl = (path: string): string => API + path;

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const res = await fetch(input, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return (await res.json()) as T;
}

/** fetcher 给 SWR 用 */
export const fetcher = <T = unknown>(url: string): Promise<T> => request<T>(API + url);

// ============================================================================
// Meta
// ============================================================================

export interface GameConfig {
  god_model: string;
  players: Array<{ player_id: string; role: "wolf" | "seer" | "witch" | "villager"; model: string }>;
  rules?: Record<string, unknown>;
}

export const getModels = (): Promise<{ models: string[] }> =>
  request(`${API}/models`);

export const getDefaultConfig = (): Promise<GameConfig> =>
  request(`${API}/games/default-config`);

// ============================================================================
// Games
// ============================================================================

export const listGames = (limit = 50): Promise<GameSummary[]> =>
  request(`${API}/games?limit=${limit}`);

export const getGame = (id: number | string): Promise<GameDetail> =>
  request(`${API}/games/${id}`);

export const listEvents = (
  id: number | string,
  channel?: string,
): Promise<ChannelEvent[]> => {
  const qs = channel ? `?channel=${encodeURIComponent(channel)}` : "";
  return request(`${API}/games/${id}/events${qs}`);
};

export const createGame = (config: GameConfig): Promise<GameDetail> =>
  request(`${API}/games`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });

export const startGame = (
  id: number | string,
  maxRounds = 8,
): Promise<{ status: string; game_id: number }> =>
  request(`${API}/games/${id}/start?max_rounds=${maxRounds}`, {
    method: "POST",
  });

export const deleteGame = async (id: number | string): Promise<void> => {
  const res = await fetch(`${API}/games/${id}`, { method: "DELETE" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
};

// ============================================================================
// Histories (复盘)
// ============================================================================

export const getPlayerHistory = (
  gameId: number | string,
  playerId: string,
): Promise<PrivateHistoryOut> =>
  request(`${API}/games/${gameId}/players/${playerId}/history`);

export const getAllHistories = (
  gameId: number | string,
): Promise<PrivateHistoryOut[]> =>
  request(`${API}/games/${gameId}/histories`);

// ============================================================================
// Stats (Home 用)
// ============================================================================

export interface StatsByRole {
  role: "wolf" | "seer" | "witch" | "villager";
  total: number;
  wins: number;
}

export interface StatsByModel {
  model: string;
  total: number;
  wins: number;
}

export interface StatsByModelRole {
  model: string;
  role: StatsByRole["role"];
  total: number;
  wins: number;
}

export interface GameStats {
  total_games: number;
  ended_games: number;
  good_wins: number;
  wolf_wins: number;
  aborted: number;
  avg_rounds: number;
  by_role: StatsByRole[];
  by_model: StatsByModel[];
  by_model_role: StatsByModelRole[];
}

export const getStats = (): Promise<GameStats> => request(`${API}/games/stats`);

// ============================================================================
// Settings
// ============================================================================

export interface AppSettings {
  anthropic_api_key: string;
  anthropic_base_url: string;
  updated_at: string | null;
}

export const getSettings = (): Promise<AppSettings> =>
  request(`${API}/settings`);

export const updateSettings = (
  body: Partial<Pick<AppSettings, "anthropic_api_key" | "anthropic_base_url">>,
): Promise<AppSettings> =>
  request(`${API}/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
