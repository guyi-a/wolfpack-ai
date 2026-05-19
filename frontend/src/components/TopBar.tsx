interface TopBarProps {
  gameId: number;
  round: number;
  phase: string;
  streaming: boolean;
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

export function TopBar({ gameId, round, phase, streaming }: TopBarProps) {
  return (
    <div className="flex items-baseline gap-6 px-10 pt-6 pb-5 border-b border-line bg-gradient-to-b from-[#18181F] to-bg">
      <div>
        <h1 className="font-serif font-extrabold text-[28px] tracking-[0.06em] text-ivory">
          WOLFPACK<span className="text-blood">.</span>
        </h1>
        <p className="font-mono text-[11px] tracking-[0.2em] uppercase text-smoke">
          AI 狼人杀观测台
        </p>
      </div>
      <span className="flex-1" />
      <div className="flex items-center gap-6 font-mono text-[11px] tracking-[0.1em] uppercase text-smoke">
        <div className="text-smoke tracking-[0.1em]">GAME #{gameId}</div>
        <div className="font-serif text-[14px] font-semibold text-ivory tracking-[0.05em] normal-case">
          <span className="text-moon mr-1.5">{PHASE_ICON[phase] ?? "•"}</span>
          ROUND {round} <span className="text-smoke font-normal ml-1.5">/ {phase}</span>
        </div>
        <div className={streaming ? "text-candle" : ""}>↻ <b className="font-medium">{streaming ? "STREAMING" : "IDLE"}</b></div>
      </div>
    </div>
  );
}
