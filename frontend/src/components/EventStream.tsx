import { useEffect, useRef } from "react";

import { EventItem } from "@/components/EventItem";
import type { ChannelEvent } from "@/lib/types";

interface EventStreamProps {
  events: ChannelEvent[];
  currentRound: number;
}

/** 按 round 分组的事件流, 新事件来时若用户已在底部则自动滚到底, 否则不打扰 */
export function EventStream({ events, currentRound }: EventStreamProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);

  // 监听滚动, 判断用户是否在底部
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const slack = 40;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= slack;
  };

  // 事件更新后, 若用户原本在底部 → 跟随; 否则保持当前位置
  useEffect(() => {
    if (atBottomRef.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length]);

  // 按 round 分组
  const grouped = events.reduce<Map<number, ChannelEvent[]>>((acc, ev) => {
    if (!acc.has(ev.round)) acc.set(ev.round, []);
    acc.get(ev.round)!.push(ev);
    return acc;
  }, new Map());

  const rounds = Array.from(grouped.keys()).sort((a, b) => a - b);

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      className="h-full overflow-y-auto px-7 py-8 bg-gradient-to-b from-bg to-[#0A0A0C]"
    >
      <div className="font-mono text-[10px] tracking-[0.3em] uppercase text-smoke flex items-center gap-3 mb-5">
        EVENT STREAM
        <span className="flex-1 h-px bg-line-soft" />
      </div>

      <div>
        {rounds.map((round) => {
          const evts = grouped.get(round)!;
          const isCurrent = round === currentRound;
          const isNight = evts.some((e) => e.kind === "phase_change" && (e.payload.phase === "night_start" || e.payload.phase === "wolf_night"));
          return (
            <div key={round} className="mb-6">
              <div className={`flex items-baseline gap-3 pb-2 mb-3 border-b border-line-soft font-serif text-[18px] font-semibold tracking-[0.04em] ${isNight ? "text-moon" : "text-candle"}`}>
                ROUND {round} · {isNight ? "🌙" : "☀️"}
                {isCurrent && (
                  <span className="font-mono text-[10px] tracking-[0.1em] text-smoke font-normal">live</span>
                )}
              </div>
              {evts.map((ev, i) => (
                <EventItem
                  key={ev.seq}
                  event={ev}
                  isLatest={isCurrent && i === evts.length - 1 && (ev.kind === "speech" || ev.kind === "last_words")}
                />
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}
