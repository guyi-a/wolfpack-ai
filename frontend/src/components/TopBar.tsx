import { Link } from "react-router";

import { apiUrl } from "@/lib/api";

interface TopBarProps {
  gameId: number;
  round: number;
  phase: string;
  streaming: boolean;
  /** 显示导出按钮 (仅复盘模式开放) */
  showExport?: boolean;
}

const PHASE_ICON: Record<string, string> = {
  night_start: "🌙",
  wolf_night: "🌙",
  seer_night: "🌙",
  witch_night: "🌙",
  night_announce: "🌑",
  day_start: "☀️",
  day_speech: "☀️",
  day_vote: "🗳️",
  last_words_voted: "⚰️",
};

export function TopBar({ gameId, round, phase, streaming, showExport }: TopBarProps) {
  return (
    <div className="drag-region flex items-center gap-6 pl-32 pr-10 pt-3 pb-5 border-b border-line bg-gradient-to-b from-[#18181F] to-bg">
      <Link
        to="/"
        className="group inline-flex -m-2 p-2 rounded transition-colors hover:bg-[#1a1a22]"
        title="返回首页"
      >
        <h1 className="font-serif text-2xl font-extrabold tracking-[0.06em] text-ivory leading-none flex items-baseline gap-3">
          <span>
            WOLFPACK<span className="text-blood">.</span>
          </span>
          <span className="font-mono text-[10px] tracking-[0.25em] uppercase text-smoke font-normal group-hover:text-candle transition-colors">
            <span className="group-hover:hidden">AI 狼人杀观测台</span>
            <span className="hidden group-hover:inline">← 返回首页</span>
          </span>
        </h1>
      </Link>
      <span className="flex-1" />
      <div className="flex items-center gap-6 font-mono text-[11px] tracking-[0.1em] uppercase text-smoke">
        <div className="text-smoke tracking-[0.1em]">GAME #{gameId}</div>
        <div className="font-serif text-[14px] font-semibold text-ivory tracking-[0.05em] normal-case">
          <span className="text-moon mr-1.5">{PHASE_ICON[phase] ?? "•"}</span>
          ROUND {round} <span className="text-smoke font-normal ml-1.5">/ {phase}</span>
        </div>
        <div className={streaming ? "text-candle" : ""}>↻ <b className="font-medium">{streaming ? "STREAMING" : "IDLE"}</b></div>
        {showExport && <ExportMenu gameId={gameId} />}
      </div>
    </div>
  );
}

function ExportMenu({ gameId }: { gameId: number }) {
  const download = (format: "json" | "markdown") => {
    // 浏览器直接走 anchor; 后端已设 Content-Disposition attachment
    const a = document.createElement("a");
    a.href = apiUrl(`/games/${gameId}/export?format=${format}`);
    a.download = "";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <div className="flex items-center gap-1">
      <span className="text-smoke-dim tracking-[0.15em]">导出</span>
      <button
        onClick={() => download("markdown")}
        className="px-2 py-1 border border-line text-smoke hover:text-ivory hover:border-smoke cursor-pointer transition-colors"
      >
        MD
      </button>
      <button
        onClick={() => download("json")}
        className="px-2 py-1 border border-line text-smoke hover:text-ivory hover:border-smoke cursor-pointer transition-colors"
      >
        JSON
      </button>
    </div>
  );
}
