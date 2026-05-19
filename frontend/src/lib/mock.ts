import type { ChannelEvent, GameDetail, InnerView, Player } from "@/lib/types";

/** 完整一局的 mock 数据 — 用于 Phase 1/2 视觉开发, 不连后端 */

export const MOCK_GAME: GameDetail = {
  id: 15,
  status: "running",
  winner: null,
  rounds_played: 2,
  god_model: "deepseek/deepseek-v4-pro",
  created_at: "2026-05-19T13:30:00Z",
  started_at: "2026-05-19T13:30:12Z",
  ended_at: null,
  error_message: null,
  config_json: {},
  players: [
    { player_id: "1", role: "wolf",     model: "deepseek/deepseek-v4-pro",   alive: true },
    { player_id: "2", role: "witch",    model: "pa/claude-opus-4-7",         alive: true },
    { player_id: "3", role: "seer",     model: "zai-org/glm-5.1",            alive: true },
    { player_id: "4", role: "wolf",     model: "deepseek/deepseek-v4-flash", alive: true },
    { player_id: "5", role: "villager", model: "deepseek/deepseek-v4-pro",   alive: false, died_at_round: 1, death_cause: "voted_out" },
    { player_id: "6", role: "villager", model: "zai-org/glm-5.1",            alive: true },
  ],
};

export const MOCK_EVENTS: ChannelEvent[] = [
  // Round 1 night
  { seq: 1, channel: "board", kind: "phase_change", round: 1, payload: { phase: "night_start" } },
  { seq: 2, channel: "board", kind: "phase_change", round: 1, payload: { phase: "wolf_night" } },
  { seq: 3, channel: "wolf_chat", kind: "speech", round: 1, payload: { speaker: "1", text: "投了 5 号,看 4 号兄弟意见" } },
  { seq: 4, channel: "wolf_chat", kind: "speech", round: 1, payload: { speaker: "4", text: "跟了,5 号可以,先这样" } },
  { seq: 5, channel: "board", kind: "phase_change", round: 1, payload: { phase: "seer_night" } },
  { seq: 6, channel: "board", kind: "phase_change", round: 1, payload: { phase: "witch_night" } },
  { seq: 7, channel: "board", kind: "phase_change", round: 1, payload: { phase: "day_start" } },
  { seq: 8, channel: "board", kind: "phase_change", round: 1, payload: { phase: "night_announce" } },
  { seq: 9, channel: "board", kind: "night_result", round: 1, payload: { deaths: [] } },

  // Round 1 day speech
  { seq: 10, channel: "board", kind: "phase_change", round: 1, payload: { phase: "day_speech" } },
  { seq: 11, channel: "board", kind: "speech", round: 1, payload: { speaker: "1", text: "平安夜没信息,我也懵。先听后面发言" } },
  { seq: 12, channel: "board", kind: "speech", round: 1, payload: { speaker: "2", text: "平安夜大概率女巫救人。我是民,听后面发言" } },
  { seq: 13, channel: "board", kind: "speech", round: 1, payload: { speaker: "3", text: "我是预言家,昨晚查 1 号是狼!好人跟我走" } },
  { seq: 14, channel: "board", kind: "speech", round: 1, payload: { speaker: "4", text: "3 号查杀 1 号?先不急站边,等看对跳" } },
  { seq: 15, channel: "board", kind: "speech", round: 1, payload: { speaker: "5", text: "平安夜+查杀,3 号有力度。1 号反应偏软" } },
  { seq: 16, channel: "board", kind: "speech", round: 1, payload: { speaker: "6", text: "无人对跳 3 号,单边预言家可信度高。跟 3 号" } },

  // Round 1 vote
  { seq: 17, channel: "board", kind: "phase_change", round: 1, payload: { phase: "day_vote" } },
  { seq: 18, channel: "board", kind: "vote", round: 1, payload: { voter: "1", target: "5" } },
  { seq: 19, channel: "board", kind: "vote", round: 1, payload: { voter: "2", target: "5" } },
  { seq: 20, channel: "board", kind: "vote", round: 1, payload: { voter: "3", target: "5" } },
  { seq: 21, channel: "board", kind: "vote", round: 1, payload: { voter: "4", target: "5" } },
  { seq: 22, channel: "board", kind: "vote", round: 1, payload: { voter: "5", target: "3" } },
  { seq: 23, channel: "board", kind: "vote", round: 1, payload: { voter: "6", target: "5" } },
  { seq: 24, channel: "board", kind: "vote_result", round: 1, payload: { loser: "5", tally: { "5": 5, "3": 1 }, abstentions: [] } },
  { seq: 25, channel: "board", kind: "phase_change", round: 1, payload: { phase: "last_words_voted" } },
  { seq: 26, channel: "board", kind: "last_words", round: 1, payload: { speaker: "5", text: "我是民,5 号倒。3 号查杀给力,大家信他", reason: "voted_out" } },

  // Round 2 night - 部分
  { seq: 27, channel: "board", kind: "phase_change", round: 2, payload: { phase: "night_start" } },
  { seq: 28, channel: "board", kind: "phase_change", round: 2, payload: { phase: "wolf_night" } },
  { seq: 29, channel: "wolf_chat", kind: "speech", round: 2, payload: { speaker: "1", text: "刀 3 号预言家,断好人信息" } },
  { seq: 30, channel: "wolf_chat", kind: "speech", round: 2, payload: { speaker: "4", text: "同意,刀 3 号" } },
  { seq: 31, channel: "board", kind: "phase_change", round: 2, payload: { phase: "seer_night" } },
];

/** Mock 3 号预言家的当前内心戏 (round 2 seer_night) */
export const MOCK_INNER_VIEW: InnerView = {
  player_id: "3",
  round: 2,
  state: "thinking",
  thinking:
    "1 号被票出后,我之前查的\"狼\"已经被处决,场上现在只剩 4 号一只狼。但 4 号在白天非常稳,跟 6 号互相站队像是埋伏。今晚再查一刀,目标应该是 4 号 — 如果查出狼,明天直接报双查杀,5 号留底牌……",
  tool_calls: [
    { name: "check_player", args: { target_id: "4" }, result: "wolf" },
  ],
  text: "明天直接报 4 号铁查杀,女巫有毒可直接洒 4。",
};

/** 当前模拟的状态: 谁在 active, 在哪个阶段 */
export const MOCK_STATE = {
  current_round: 2,
  current_phase: "seer_night",
  active_player_id: "3" as string | null,
  player_states: {
    "1": "idle" as const,
    "2": "idle" as const,
    "3": "thinking" as const,
    "4": "tool_calling" as const,
    "5": "idle" as const, // 死
    "6": "idle" as const,
  } satisfies Record<string, "idle" | "thinking" | "tool_calling" | "speaking">,
  current_tool_name: { "4": "cast_vote" } as Record<string, string | undefined>,
};

/** 历史 inner views (各 player 各 round) */
export const MOCK_PAST_INNERS: InnerView[] = [
  {
    player_id: "3",
    round: 1,
    state: "idle",
    thinking: "第一夜没什么信息,中间位置查 1 号试试。",
    tool_calls: [{ name: "check_player", args: { target_id: "1" }, result: "wolf" }],
    text: "查 1 号是狼!明天直接报查杀,警徽流先 2 后 6。",
  },
];

/** 把 role 中文映射 */
export const ROLE_LABEL: Record<Player["role"], { upper: string; cn: string; icon: string }> = {
  wolf:     { upper: "WOLF",     cn: "狼人",   icon: "🐺" },
  witch:    { upper: "WITCH",    cn: "女巫",   icon: "🧪" },
  seer:     { upper: "SEER",     cn: "预言家", icon: "🔮" },
  villager: { upper: "VILLAGER", cn: "村民",   icon: "👤" },
};

export const PHASE_ORDER = [
  "wolf_night",
  "seer_night",
  "witch_night",
  "night_announce",
  "day_speech",
  "day_vote",
] as const;

/** 历史对局列表 mock — Home 页用 */
export const MOCK_GAMES_LIST: import("@/lib/types").GameSummary[] = [
  { id: 15, status: "running", winner: null,   rounds_played: 2, god_model: "deepseek/deepseek-v4-pro", created_at: "2026-05-19T13:30:00Z", started_at: "2026-05-19T13:30:12Z", ended_at: null },
  { id: 14, status: "ended",   winner: "good", rounds_played: 2, god_model: "deepseek/deepseek-v4-pro", created_at: "2026-05-18T22:15:00Z", started_at: "2026-05-18T22:15:08Z", ended_at: "2026-05-18T22:23:50Z" },
  { id: 13, status: "ended",   winner: "wolf", rounds_played: 1, god_model: "deepseek/deepseek-v4-pro", created_at: "2026-05-18T20:42:00Z", started_at: "2026-05-18T20:42:11Z", ended_at: "2026-05-18T20:45:23Z" },
  { id: 12, status: "aborted", winner: null,   rounds_played: 0, god_model: "deepseek/deepseek-v4-pro", created_at: "2026-05-18T18:01:00Z", started_at: "2026-05-18T18:01:05Z", ended_at: "2026-05-18T18:01:30Z" },
  { id: 11, status: "ended",   winner: "good", rounds_played: 3, god_model: "deepseek/deepseek-v4-pro", created_at: "2026-05-17T19:20:00Z", started_at: "2026-05-17T19:20:08Z", ended_at: "2026-05-17T19:35:11Z" },
  { id: 10, status: "ended",   winner: "wolf", rounds_played: 2, god_model: "deepseek/deepseek-v4-pro", created_at: "2026-05-17T15:10:00Z", started_at: "2026-05-17T15:10:08Z", ended_at: "2026-05-17T15:18:33Z" },
];

/** 模型清单 mock — Lobby 用 */
export const MOCK_MODELS: string[] = [
  "deepseek/deepseek-v4-pro",
  "deepseek/deepseek-v4-flash",
  "pa/claude-opus-4-7",
  "zai-org/glm-5.1",
  "xiaomimimo/mimo-v2.5-pro",
];

/** 默认 6 人板配置 mock */
export const MOCK_DEFAULT_CONFIG = {
  god_model: "deepseek/deepseek-v4-pro",
  players: [
    { player_id: "1", role: "wolf"     as const, model: "deepseek/deepseek-v4-pro" },
    { player_id: "2", role: "witch"    as const, model: "pa/claude-opus-4-7" },
    { player_id: "3", role: "seer"     as const, model: "zai-org/glm-5.1" },
    { player_id: "4", role: "wolf"     as const, model: "deepseek/deepseek-v4-flash" },
    { player_id: "5", role: "villager" as const, model: "deepseek/deepseek-v4-pro" },
    { player_id: "6", role: "villager" as const, model: "zai-org/glm-5.1" },
  ],
};
