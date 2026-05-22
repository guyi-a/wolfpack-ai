import { useState } from "react";
import { Link } from "react-router";
import useSWR, { useSWRConfig } from "swr";
import { Settings, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { deleteGame, listGames, getStats, type GameStats } from "@/lib/api";
import { MOCK_GAMES_LIST } from "@/lib/mock";
import { cn } from "@/lib/cn";
import type { GameSummary } from "@/lib/types";

const ROLE_CN: Record<GameStats["by_role"][number]["role"], string> = {
  wolf: "狼人",
  seer: "预言家",
  witch: "女巫",
  villager: "村民",
};

const ROLE_TONE: Record<GameStats["by_role"][number]["role"], string> = {
  wolf: "text-blood",
  seer: "text-candle",
  witch: "text-moon",
  villager: "text-ivory",
};

export default function HomePage() {
  const { mutate } = useSWRConfig();
  const { data, error, isLoading } = useSWR<GameSummary[]>("games-list", () => listGames(50), {
    refreshInterval: 5000,
  });
  const { data: stats } = useSWR<GameStats>("games-stats", getStats, {
    refreshInterval: 5000,
  });

  // 后端没起或没数据时, fallback 到 mock (开发期保留视觉)
  const games = data ?? (error ? MOCK_GAMES_LIST : []);

  const handleDelete = async (id: number) => {
    try {
      await deleteGame(id);
      toast.success(`#${id} 已删除`);
      await Promise.all([mutate("games-list"), mutate("games-stats")]);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error(`删除失败: ${msg}`);
    }
  };

  // 胜率: 后端 stats 优先, 没有时用客户端聚合 (fallback)
  const ended = games.filter((g) => g.status === "ended");
  const goodWins = stats?.good_wins ?? ended.filter((g) => g.winner === "good").length;
  const wolfWins = stats?.wolf_wins ?? ended.filter((g) => g.winner === "wolf").length;
  const endedCount = stats?.ended_games ?? ended.length;
  const goodPct = endedCount ? Math.round((goodWins / endedCount) * 100) : 0;
  const wolfPct = endedCount ? 100 - goodPct : 0;
  const avgRounds =
    stats?.avg_rounds ??
    (games.length ? games.reduce((s, g) => s + g.rounds_played, 0) / games.length : 0);

  return (
    <div className="min-h-screen px-10 pt-3 pb-8">
      <header className="drag-region flex items-center gap-6 pb-5 border-b border-line pl-20">
        <h1 className="font-serif text-2xl font-extrabold tracking-[0.06em] leading-none flex items-baseline gap-3">
          <span>
            WOLFPACK<span className="text-blood">.</span>
          </span>
          <span className="font-mono text-[10px] tracking-[0.25em] uppercase text-smoke font-normal">
            AI 狼人杀观测台
          </span>
        </h1>
        <span className="flex-1" />
        {error && (
          <span className="font-mono text-[10px] text-blood-dim tracking-[0.1em]">
            ⚠ 后端未连通, 显示 mock 数据
          </span>
        )}
        <Link
          to="/settings"
          title="设置"
          className="h-9 w-9 inline-flex items-center justify-center border border-line text-smoke
                     hover:text-candle hover:border-candle/60 transition-colors"
        >
          <Settings className="w-4 h-4" strokeWidth={1.5} />
        </Link>
        <Link
          to="/lobby"
          className="h-9 inline-flex items-center px-5 border border-candle text-candle font-mono
                     text-[11px] tracking-[0.25em] uppercase hover:bg-candle hover:text-bg transition-colors"
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
                  <GameRow game={g} onDelete={handleDelete} />
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
                <div className="text-ivory tabular text-2xl font-serif mt-1">
                  {stats?.total_games ?? games.length}
                </div>
              </div>
              <div className="bg-bg-card border border-line p-3">
                <div className="text-smoke tracking-[0.1em] uppercase text-[9px]">avg rounds</div>
                <div className="text-ivory tabular text-2xl font-serif mt-1">
                  {endedCount ? avgRounds.toFixed(1) : "—"}
                </div>
              </div>
            </div>
          </div>

          <div>
            <SectionTitle>BY ROLE · 角色胜率</SectionTitle>
            {!stats || stats.by_role.length === 0 ? (
              <p className="text-smoke-dim text-xs">—</p>
            ) : (
              <div className="space-y-3">
                {stats.by_role.map((r) => {
                  const pct = r.total ? Math.round((r.wins / r.total) * 100) : 0;
                  return (
                    <div key={r.role} className="flex items-center gap-3">
                      <div
                        className={cn(
                          "font-mono text-[11px] w-16 truncate",
                          ROLE_TONE[r.role],
                        )}
                      >
                        {ROLE_CN[r.role]}
                      </div>
                      <div className="flex-1 h-1.5 bg-line relative overflow-hidden">
                        <div
                          className={cn(
                            "absolute inset-y-0 left-0",
                            r.role === "wolf" ? "bg-blood" : "bg-candle",
                          )}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <div className="font-mono text-[11px] tabular text-smoke w-24 text-right">
                        <span className="text-ivory">{pct}%</span>
                        <span className="text-smoke-dim ml-1.5">{r.wins}/{r.total}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </aside>
      </div>

      {stats && stats.by_model_role.length > 0 && (
        <section className="mt-12">
          <SectionTitle>MODEL × ROLE · 模型在每个角色的胜率</SectionTitle>
          <ModelRoleMatrix stats={stats} />
        </section>
      )}
    </div>
  );
}

interface MatrixCell {
  total: number;
  wins: number;
}

function ModelRoleMatrix({ stats }: { stats: GameStats }) {
  const roles: GameStats["by_role"][number]["role"][] = ["wolf", "seer", "witch", "villager"];

  // 按模型构建 row, 每行有 4 个角色的 cell + 总计
  const byModel = new Map<string, { cells: Record<string, MatrixCell>; total: number; wins: number }>();
  for (const row of stats.by_model_role) {
    if (!byModel.has(row.model)) {
      byModel.set(row.model, { cells: {}, total: 0, wins: 0 });
    }
    const entry = byModel.get(row.model)!;
    entry.cells[row.role] = { total: row.total, wins: row.wins };
    entry.total += row.total;
    entry.wins += row.wins;
  }

  const rows = [...byModel.entries()].sort((a, b) => b[1].total - a[1].total);

  return (
    <div className="overflow-x-auto border border-line">
      <table className="w-full font-mono text-[11px]">
        <thead>
          <tr className="border-b border-line bg-bg-soft">
            <th className="text-left px-4 py-2.5 text-smoke tracking-[0.15em] uppercase text-[10px] font-normal">
              模型
            </th>
            {roles.map((r) => (
              <th
                key={r}
                className={cn(
                  "text-center px-3 py-2.5 tracking-[0.15em] uppercase text-[10px] font-normal",
                  ROLE_TONE[r],
                )}
              >
                {ROLE_CN[r]}
              </th>
            ))}
            <th className="text-right px-4 py-2.5 text-smoke tracking-[0.15em] uppercase text-[10px] font-normal">
              总计
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([model, row]) => {
            const totalPct = row.total ? Math.round((row.wins / row.total) * 100) : 0;
            return (
              <tr key={model} className="border-b border-line-soft hover:bg-bg-card transition-colors">
                <td className="px-4 py-2.5 text-ivory truncate max-w-[280px]">{model}</td>
                {roles.map((r) => {
                  const cell = row.cells[r];
                  if (!cell || cell.total === 0) {
                    return (
                      <td key={r} className="text-center px-3 py-2.5 text-smoke-dim">
                        —
                      </td>
                    );
                  }
                  const pct = Math.round((cell.wins / cell.total) * 100);
                  return (
                    <td key={r} className="text-center px-3 py-2.5">
                      <span className={cn("tabular", pctTone(pct))}>{pct}%</span>
                      <span className="text-smoke-dim ml-1.5 tabular text-[10px]">
                        {cell.wins}/{cell.total}
                      </span>
                    </td>
                  );
                })}
                <td className="text-right px-4 py-2.5">
                  <span className={cn("tabular", pctTone(totalPct))}>{totalPct}%</span>
                  <span className="text-smoke-dim ml-1.5 tabular text-[10px]">
                    {row.wins}/{row.total}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function pctTone(pct: number): string {
  if (pct >= 60) return "text-candle";
  if (pct >= 40) return "text-ivory";
  return "text-blood-dim";
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

function GameRow({
  game,
  onDelete,
}: {
  game: GameSummary;
  onDelete: (id: number) => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const dur =
    game.started_at && game.ended_at
      ? formatDuration(new Date(game.ended_at).getTime() - new Date(game.started_at).getTime())
      : game.status === "running"
        ? "—"
        : "0s";

  const handleClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (deleting) return;
    if (!confirming) {
      setConfirming(true);
      setTimeout(() => setConfirming(false), 2500);
      return;
    }
    setDeleting(true);
    onDelete(game.id).finally(() => {
      setDeleting(false);
      setConfirming(false);
    });
  };

  return (
    <Link
      to={`/games/${game.id}`}
      className="grid grid-cols-[48px_90px_90px_1fr_70px_auto] gap-4 items-center
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
      <button
        type="button"
        onClick={handleClick}
        title={game.status === "running" ? "运行中, 无法删除" : confirming ? "再点一次确认删除" : "删除此局"}
        disabled={game.status === "running" || deleting}
        className={cn(
          "h-7 inline-flex items-center justify-center gap-1.5 border font-mono text-[10px] tracking-[0.15em] uppercase",
          "transition-all whitespace-nowrap",
          confirming || deleting
            ? "opacity-100 px-2.5 border-blood text-ivory bg-blood/80"
            : "w-7 opacity-0 group-hover:opacity-100 focus:opacity-100 border-line text-smoke hover:text-blood hover:border-blood",
          game.status === "running" && "cursor-not-allowed text-smoke-dim border-line hover:text-smoke-dim hover:border-line",
        )}
      >
        {deleting ? (
          <span>删除中…</span>
        ) : confirming ? (
          <>
            <Trash2 className="w-3 h-3" strokeWidth={2} />
            <span>确认删除</span>
          </>
        ) : (
          <Trash2 className="w-3.5 h-3.5" strokeWidth={1.5} />
        )}
      </button>
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
