import { cn } from "@/lib/cn";
import { PHASE_ORDER } from "@/lib/mock";

interface PhaseStepperProps {
  currentPhase: string;
  pinnedPlayerId?: string | null;
  followMode: boolean;
  /** PINNED 时点击 → 切回 AUTO; followMode 时禁用 */
  onResetFollow?: () => void;
}

const PHASE_LABEL: Record<string, string> = {
  wolf_night: "wolf",
  seer_night: "seer",
  witch_night: "witch",
  night_announce: "announce",
  day_speech: "speech",
  day_vote: "vote",
};

export function PhaseStepper({ currentPhase, pinnedPlayerId, followMode, onResetFollow }: PhaseStepperProps) {
  const idx = PHASE_ORDER.findIndex((p) => p === currentPhase);

  return (
    <div className="border-t border-line px-10 py-4 bg-bg-soft flex items-center gap-7">
      <span className="font-mono text-[10px] tracking-[0.25em] uppercase text-smoke">PHASE</span>
      <div className="flex items-center gap-[18px] flex-1 flex-wrap">
        {PHASE_ORDER.map((p, i) => {
          const done = i < idx;
          const now = i === idx;
          return (
            <div
              key={p}
              className={cn(
                "flex items-center gap-2 font-mono text-[11px] tracking-[0.1em]",
                done && "text-smoke",
                now && "text-candle",
                !done && !now && "text-smoke-dim",
              )}
            >
              <span
                className={cn(
                  "w-2 h-2 rounded-full border",
                  done && "bg-smoke border-smoke",
                  now && "bg-candle border-candle shadow-[0_0_12px_var(--color-candle)]",
                  !done && !now && "bg-line border-smoke-dim",
                )}
              />
              {PHASE_LABEL[p]}
            </div>
          );
        })}
      </div>
      {followMode ? (
        <div className="font-mono text-[10px] tracking-[0.25em] uppercase text-smoke-dim">
          ↻ AUTO FOLLOW
        </div>
      ) : (
        <button
          onClick={onResetFollow}
          title="点击恢复自动跟随活跃 player"
          className="group font-mono text-[10px] tracking-[0.25em] uppercase text-candle
                     px-2.5 py-1 border border-candle/40 hover:border-candle hover:bg-candle/10
                     transition-colors cursor-pointer"
        >
          <span className="group-hover:hidden">📌 PINNED · {pinnedPlayerId}号</span>
          <span className="hidden group-hover:inline">↻ 恢复 AUTO</span>
        </button>
      )}
    </div>
  );
}
