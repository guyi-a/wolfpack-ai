import { Link } from "react-router";
import useSWR from "swr";

import { listGames } from "@/lib/api";
import { MOCK_GAMES_LIST } from "@/lib/mock";
import { cn } from "@/lib/cn";
import type { GameSummary } from "@/lib/types";

export default function HomePage() {
  const { data, error, isLoading } = useSWR<GameSummary[]>("games-list", () => listGames(50), {
    refreshInterval: 5000,
  });

  // 后端没起或没数据时, fallback 到 mock (开发期保留视觉)
  const games = data ?? (error ? MOCK_GAMES_LIST : []);

  // 简单聚合
  const ended = games.filter((g) => g.status === "ended");
  const goodWins = ended.filter((g) => g.winner === "good").length;
  const wolfWins = ended.filter((g) => g.winner === "wolf").length;
  const goodPct = ended.length ? Math.round((goodWins / ended.length) * 100) : 0;
  const wolfPct = ended.length ? 100 - goodPct : 0;

  // 模型出场实时统计 (从 god_model 聚合, 后面接 GET /games/{id} players 再细化)
  const modelMap = games.reduce<Record<string, number>>((acc, g) => {
    const name = g.god_model.split("/").pop() ?? g.god_model;
    acc[name] = (acc[name] ?? 0) + 1;
    return acc;
  }, {});
  const modelCounts = Object.entries(modelMap)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);
  const maxModel = Math.max(...modelCounts.map((m) => m.count), 1);

  return (
    <div className="min-h-screen px-10 py-8">
      <header className="flex items-baseline gap-6 pb-6 border-b border-line">
        <div>
          <h1 className="font-serif text-3xl font-extrabold tracking-[0.06em]">
            WOLFPACK<span className="text-blood">.</span>
          </h1>
          <p className="font-mono text-[11px] tracking-[0.2em] uppercase text-smoke mt-1">
            AI 狼人杀观测台
          </p>
        </div>
        <span className="flex-1" />
        {error && (
          <span className="font-mono text-[10px] text-blood-dim tracking-[0.1em]">
            ⚠ 后端未连通, 显示 mock 数据
          </span>
        )}
        <Link
          to="/lobby"
          className="px-5 py-2.5 border border-candle text-candle text-[11px] tracking-[0.25em] uppercase
                     hover:bg-candle hover:text-bg transition-colors font-mono"
        >
          新开一局 →
        </Link>
      </header>

      <div className="grid grid-cols-[1fr_360px] gap-12 mt-10">
        <section>
          <SectionTitle>
            RECENT GAMES · 最近对局 {isLoading && <span className="text-smoke-dim normal-case ml-2">loading...</span>}
          </SectionTitle>
          {games.length === 0 && !isLoading ? (
            <p className="text-smoke text-sm py-12 text-center">
              暂无对局 — 去 <Link to="/lobby" className="text-candle underline">Lobby</Link> 开一局?
            </p>
          ) : (
            <ul className="flex flex-col">
              {games.map((g) => (
                <li key={g.id}>
                  <GameRow game={g} />
                </li>
              ))}
            </ul>
          )}
        </section>

        <aside className="space-y-10">
          <div>
            <SectionTitle>WIN RATE · 胜率</SectionTitle>
            <div className="space-y-4">
              <WinBar label="好人方" value={goodPct} count={goodWins} color="candle" />
              <WinBar label="狼  方" value={wolfPct} count={wolfWins} color="blood" />
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 font-mono text-[11px]">
              <div className="bg-bg-card border border-line p-3">
                <div className="text-smoke tracking-[0.1em] uppercase text-[9px]">total games</div>
                <div className="text-ivory tabular text-2xl font-serif mt-1">{games.length}</div>
              </div>
              <div className="bg-bg-card border border-line p-3">
                <div className="text-smoke tracking-[0.1em] uppercase text-[9px]">avg rounds</div>
                <div className="text-ivory tabular text-2xl font-serif mt-1">
                  {games.length
                    ? (games.reduce((s, g) => s + g.rounds_played, 0) / games.length).toFixed(1)
                    : "—"}
                </div>
              </div>
            </div>
          </div>

          <div>
            <SectionTitle>GOD MODEL · 上帝模型出场</SectionTitle>
            <div className="space-y-3">
              {modelCounts.length === 0 ? (
                <p className="text-smoke-dim text-xs">—</p>
              ) : (
                modelCounts.map((m) => (
                  <div key={m.name} className="flex items-center gap-3">
                    <div className="font-mono text-[11px] text-ivory w-44 truncate">{m.name}</div>
                    <div className="flex-1 h-1.5 bg-line relative overflow-hidden">
                      <div
                        className="absolute inset-y-0 left-0 bg-moon"
                        style={{ width: `${(m.count / maxModel) * 100}%` }}
                      />
                    </div>
                    <div className="font-mono text-[11px] tabular text-smoke w-6 text-right">
                      {m.count}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-5">
      {children}
      <span className="flex-1 h-px bg-line-soft" />
    </div>
  );
}

const STATUS_TONE: Record<GameSummary["status"], string> = {
  pending: "text-smoke",
  running: "text-candle",
  ended: "text-ivory",
  aborted: "text-blood-dim",
};

function GameRow({ game }: { game: GameSummary }) {
  const dur =
    game.started_at && game.ended_at
      ? formatDuration(new Date(game.ended_at).getTime() - new Date(game.started_at).getTime())
      : game.status === "running"
        ? "—"
        : "0s";

  return (
    <Link
      to={`/games/${game.id}`}
      className="grid grid-cols-[48px_90px_90px_1fr_70px] gap-4 items-center
                 py-3.5 border-b border-line-soft hover:bg-bg-card transition-colors group px-2 -mx-2"
    >
      <div className="font-serif text-2xl font-light text-ivory tabular">#{game.id}</div>
      <div className={cn("font-mono text-[10px] tracking-[0.15em] uppercase", STATUS_TONE[game.status])}>
        {game.status}
      </div>
      <div className="font-mono text-[11px] uppercase tracking-[0.1em]">
        {game.winner === "good" && <span className="text-candle">good wins</span>}
        {game.winner === "wolf" && <span className="text-blood">wolf wins</span>}
        {!game.winner && <span className="text-smoke-dim">—</span>}
      </div>
      <div className="font-mono text-[11px] text-smoke">
        {game.rounds_played} rounds · {game.god_model.split("/").pop()}
      </div>
      <div className="font-mono text-[10px] text-smoke-dim tabular text-right">{dur}</div>
    </Link>
  );
}

function WinBar({
  label,
  value,
  count,
  color,
}: {
  label: string;
  value: number;
  count: number;
  color: "candle" | "blood";
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <span className="font-mono text-[11px] text-smoke tracking-[0.05em]">{label}</span>
        <span className="font-mono text-[11px] tabular">
          <span className="text-ivory">{count} 局</span>
          <span className="text-smoke-dim mx-1.5">·</span>
          <span className={color === "candle" ? "text-candle" : "text-blood"}>{value}%</span>
        </span>
      </div>
      <div className="h-1.5 bg-line relative overflow-hidden">
        <div
          className={cn("absolute inset-y-0 left-0", color === "candle" ? "bg-candle" : "bg-blood")}
          style={{ width: `${value}%` }}
        />
      </div>
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  const min = Math.floor(ms / 60_000);
  const sec = Math.round((ms % 60_000) / 1000);
  return `${min}m ${sec}s`;
}
