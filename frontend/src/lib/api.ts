/** 后端 API 调用封装. vite 已把 /api 代理到 :8080 */

import type {
  ChannelEvent,
  GameDetail,
  GameSummary,
  PrivateHistoryOut,
} from "@/lib/types";

const API = "/api";

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
