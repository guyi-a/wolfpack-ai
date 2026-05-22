import { useMemo } from "react";

import { cn } from "@/lib/cn";

interface ReplayScrubberProps {
  /** 已发生的所有 round 编号 (升序) */
  rounds: number[];
  /** 当前游标; null = 看到最新 */
  cursor: number | null;
  onChange: (round: number | null) => void;
  /** 胜负 (复盘时显示) */
  winner: "good" | "wolf" | null;
}

/** 复盘时间轴: round 级颗粒度. 点击 round 滑块跳到该 round 末. */
export function ReplayScrubber({ rounds, cursor, onChange, winner }: ReplayScrubberProps) {
  const maxRound = rounds.length ? rounds[rounds.length - 1] : 0;
  const isLatest = cursor === null || cursor === maxRound;

  // 当前激活的 round (用于 UI 高亮)
  const activeRound = useMemo(() => cursor ?? maxRound, [cursor, maxRound]);

  return (
    <div className="border-t border-line px-10 py-4 bg-bg-soft flex items-center gap-7">
      <span className="font-mono text-[10px] tracking-[0.25em] uppercase text-smoke">
        REPLAY
      </span>

      <div className="flex items-center gap-2 flex-1">
        {rounds.map((r, i) => {
          const active = r === activeRound;
          const passed = r < activeRound;
          return (
            <div key={r} className="flex items-center gap-2">
              <button
                onClick={() => onChange(r === maxRound ? null : r)}
                className={cn(
                  "font-mono text-[11px] tracking-[0.1em] flex items-center gap-2 cursor-pointer transition-colors",
                  active && "text-candle",
                  passed && "text-smoke hover:text-ivory",
                  !active && !passed && "text-smoke-dim hover:text-smoke",
                )}
              >
                <span
                  className={cn(
                    "w-2 h-2 rounded-full border transition-all",
                    active && "bg-candle border-candle shadow-[0_0_12px_var(--color-candle)]",
                    passed && "bg-smoke border-smoke",
                    !active && !passed && "bg-line border-smoke-dim",
                  )}
                />
                R{r}
              </button>
              {i < rounds.length - 1 && (
                <span
                  className={cn(
                    "w-8 h-px",
                    r < activeRound ? "bg-smoke" : "bg-line",
                  )}
                />
              )}
            </div>
          );
        })}

        {winner && isLatest && (
          <span
            className={cn(
              "ml-3 font-mono text-[10px] tracking-[0.2em] uppercase",
              winner === "good" ? "text-candle" : "text-blood",
            )}
          >
            · {winner} wins
          </span>
        )}
      </div>

      <button
        onClick={() => onChange(null)}
        disabled={isLatest}
        className={cn(
          "font-mono text-[10px] tracking-[0.2em] uppercase transition-colors",
          isLatest
            ? "text-smoke-dim cursor-default"
            : "text-candle hover:text-ivory cursor-pointer",
        )}
      >
        ↻ 回到最新
      </button>
    </div>
  );
}
