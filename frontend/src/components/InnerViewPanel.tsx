import { useEffect, useMemo, useState } from "react";

import { cn } from "@/lib/cn";
import { DotPulse } from "@/components/atoms/DotPulse";
import { TypingCursor } from "@/components/atoms/TypingCursor";
import { ROLE_LABEL } from "@/lib/mock";
import type { InnerView, Player } from "@/lib/types";

interface InnerViewPanelProps {
  player: Player;
  /** 该 player 的全部历史 act (按 act 顺序) */
  views: InnerView[];
  /** 当前正在跑的 act (live tokens 累积), 没有时传 null */
  liveView: InnerView | null;
  pinned: boolean;
  onTogglePin: () => void;
}

export function InnerViewPanel({
  player,
  views,
  liveView,
  pinned,
  onTogglePin,
}: InnerViewPanelProps) {
  const role = ROLE_LABEL[player.role];

  // 全部 round 集合 (含 liveView)
  const rounds = useMemo(() => {
    const set = new Set<number>();
    for (const v of views) set.add(v.round);
    if (liveView) set.add(liveView.round);
    return [...set].sort((a, b) => a - b);
  }, [views, liveView]);

  const maxRound = rounds.length ? rounds[rounds.length - 1] : 0;

  // 选中的 round (null = 跟随最新)
  const [selectedRound, setSelectedRound] = useState<number | null>(null);

  // 切 player 时重置
  useEffect(() => {
    setSelectedRound(null);
  }, [player.player_id]);

  const effectiveRound = selectedRound ?? maxRound;

  // 当前 round 内所有 view (按顺序), 含 liveView 如果在这一 round
  const roundViews = useMemo(() => {
    const list = views.filter((v) => v.round === effectiveRound);
    if (liveView && liveView.round === effectiveRound) list.push(liveView);
    return list;
  }, [views, liveView, effectiveRound]);

  const isFollowingLatest = selectedRound === null || selectedRound === maxRound;

  return (
    <div className="h-full flex flex-col bg-bg-active">
      {/* header */}
      <div className="px-7 pt-7 pb-3 border-b border-line">
        <div className="flex items-baseline gap-3">
          <div className="font-serif text-[30px] font-light text-ivory leading-none">
            {player.player_id}
          </div>
          <div>
            <div className="font-mono text-[11px] tracking-[0.2em] uppercase text-candle">
              {role.upper} · {role.cn}
            </div>
            <div className="font-mono text-[10px] text-smoke mt-0.5 tracking-[0.05em]">
              {rounds.length ? `${roundViews.length} act · round ${effectiveRound}` : "no act yet"}
            </div>
          </div>
          <span className="flex-1" />
          <div className="font-mono text-[10px] text-smoke truncate max-w-[180px]">{player.model}</div>
          <button
            onClick={onTogglePin}
            className={cn(
              "font-mono text-[9px] tracking-[0.15em] uppercase",
              "px-2 py-1 border bg-transparent cursor-pointer ml-2",
              pinned
                ? "text-candle border-candle"
                : "text-smoke border-line hover:text-ivory",
            )}
          >
            {pinned ? "📌 PINNED" : "FOLLOW"}
          </button>
        </div>

        {/* round tabs */}
        {rounds.length > 0 && (
          <div className="flex items-center gap-1.5 mt-4 flex-wrap">
            {rounds.map((r) => {
              const active = r === effectiveRound;
              const isLive = liveView && liveView.round === r;
              return (
                <button
                  key={r}
                  onClick={() => setSelectedRound(r === maxRound ? null : r)}
                  className={cn(
                    "font-mono text-[10px] tracking-[0.15em] uppercase px-2.5 py-1 border transition-colors cursor-pointer",
                    active
                      ? "border-candle text-candle bg-candle/10"
                      : "border-line text-smoke hover:text-ivory hover:border-smoke",
                  )}
                >
                  R{r}
                  {isLive && (
                    <span className="ml-1.5 text-blood text-[8px]">● LIVE</span>
                  )}
                </button>
              );
            })}
            {!isFollowingLatest && (
              <button
                onClick={() => setSelectedRound(null)}
                className="ml-2 font-mono text-[9px] tracking-[0.15em] uppercase text-smoke-dim hover:text-ivory cursor-pointer"
              >
                ← 回到最新
              </button>
            )}
          </div>
        )}
      </div>

      {/* body */}
      <div className="flex-1 overflow-y-auto px-7 py-5">
        {roundViews.length === 0 ? (
          <p className="font-mono text-[11px] text-smoke-dim py-12 text-center tracking-[0.05em]">
            (尚未发声)
          </p>
        ) : (
          roundViews.map((v, i) => (
            <ActBlock
              key={i}
              view={v}
              actIndex={i + 1}
              total={roundViews.length}
              isLive={liveView !== null && v === liveView}
            />
          ))
        )}
      </div>
    </div>
  );
}

interface ActBlockProps {
  view: InnerView;
  actIndex: number;
  total: number;
  isLive: boolean;
}

function ActBlock({ view, actIndex, total, isLive }: ActBlockProps) {
  const streaming = view.state !== "idle";

  return (
    <div className={cn("pb-5 mb-5", actIndex < total && "border-b border-line")}>
      {/* act 头 */}
      <div className="flex items-center gap-2 mb-3">
        <span className="font-mono text-[9px] tracking-[0.2em] uppercase text-smoke-dim">
          ACT {actIndex} / {total}
        </span>
        {isLive && (
          <span className="flex items-center gap-1.5 font-mono text-[9px] tracking-[0.2em] uppercase text-candle">
            {labelOfState(view.state, view.tool_name)}
            <DotPulse />
          </span>
        )}
        <span className="flex-1 h-px bg-line-soft" />
      </div>

      {view.thinking && (
        <div className="py-2.5 border-b border-dashed border-line-soft">
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-candle mb-2">
            💭 THINKING
          </div>
          <div className="font-serif text-[13.5px] leading-[1.65] text-ivory whitespace-pre-wrap">
            {view.thinking}
            {streaming && view.state === "thinking" && <TypingCursor />}
          </div>
        </div>
      )}

      {view.tool_calls.map((tc, i) => (
        <div key={i} className="py-2.5 border-b border-dashed border-line-soft">
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-moon mb-2">
            🔧 TOOL · {tc.name}
          </div>
          <div className="font-mono text-[12px] text-ivory">
            {tc.name}(
            {Object.entries(tc.args).map(([k, v], j) => (
              <span key={k}>
                {j > 0 && ", "}
                <span className="text-candle">{k}=</span>
                <span className="text-ivory">"{String(v)}"</span>
              </span>
            ))}
            )
            {tc.result !== null && (
              <>
                <span className="text-moon mx-2">→</span>
                <span className="text-blood font-semibold">{tc.result}</span>
              </>
            )}
          </div>
        </div>
      ))}

      {view.text && (
        <div className="py-2.5">
          <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-ivory mb-2">
            💬 SPEECH
          </div>
          <div className="font-serif text-[13.5px] leading-[1.65] text-ivory whitespace-pre-wrap">
            {view.text}
            {streaming && view.state === "speaking" && <TypingCursor />}
          </div>
        </div>
      )}
    </div>
  );
}

function labelOfState(state: InnerView["state"], toolName?: string) {
  if (state === "thinking") return "THINKING";
  if (state === "tool_calling") return (toolName ?? "TOOL CALLING").toUpperCase();
  if (state === "speaking") return "SPEAKING";
  return "IDLE";
}
