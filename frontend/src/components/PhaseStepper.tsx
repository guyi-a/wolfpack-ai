import { cn } from "@/lib/cn";
import { PHASE_ORDER } from "@/lib/mock";

interface PhaseStepperProps {
  currentPhase: string;
  pinnedPlayerId?: string | null;
  followMode: boolean;
}

const PHASE_LABEL: Record<string, string> = {
  wolf_night: "wolf",
  seer_night: "seer",
  witch_night: "witch",
  night_announce: "announce",
  day_speech: "speech",
  day_vote: "vote",
};

export function PhaseStepper({ currentPhase, pinnedPlayerId, followMode }: PhaseStepperProps) {
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
      <div
        className={cn(
          "font-mono text-[10px] tracking-[0.25em] uppercase",
          followMode ? "text-smoke-dim" : "text-candle",
        )}
      >
        {followMode ? "↻ AUTO FOLLOW" : `📌 PINNED · ${pinnedPlayerId}号`}
      </div>
    </div>
  );
}
