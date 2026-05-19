import { cn } from "@/lib/cn";
import { TypingCursor } from "@/components/atoms/TypingCursor";
import type { ChannelEvent } from "@/lib/types";

interface EventItemProps {
  event: ChannelEvent;
  isLatest?: boolean;
}

/** 给某一条事件配 actor badge 颜色 */
const ACTOR_TONE = {
  wolf:  "text-blood    border-blood/35",
  seer:  "text-candle   border-candle/35",
  witch: "text-candle   border-candle/35",
  default: "text-ivory  border-line",
} as const;

function ActorBadge({ tone = "default", children }: { tone?: keyof typeof ACTOR_TONE; children: React.ReactNode }) {
  return (
    <span className={cn(
      "inline-block font-mono text-[10px] px-1.5 py-px mr-2 tracking-[0.08em]",
      "bg-bg-card border",
      ACTOR_TONE[tone],
    )}>
      {children}
    </span>
  );
}

/** 顶部"— 第 1 夜 / 第 1 天"分隔条 */
function SectionMarker({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 py-3 pb-2 text-[10px] tracking-[0.15em] uppercase text-smoke">
      <span className="flex-1 h-px bg-line-soft" />
      <span>— {children} —</span>
      <span className="flex-1 h-px bg-line-soft" />
    </div>
  );
}

export function EventItem({ event, isLatest }: EventItemProps) {
  const p = event.payload as Record<string, string>;
  const ts = ""; // 暂时不显示时间戳, 后续 SSE 接进来再加

  // === phase_change ===
  if (event.kind === "phase_change") {
    const phase = String(p.phase ?? "");
    const labels: Record<string, string> = {
      night_start: "第 N 夜",
      day_start: "第 N 天",
      wolf_night: "🐺 狼人睁眼",
      seer_night: "🔮 预言家睁眼",
      witch_night: "🧪 女巫睁眼",
      night_announce: "📢 夜结算",
      day_speech: "💬 自由发言",
      day_vote: "🗳️ 投票阶段",
      last_words_voted: "⚰️ 出局者遗言",
    };
    if (phase === "night_start" || phase === "day_start") {
      const label = phase === "night_start" ? `第 ${event.round} 夜 🌙` : `第 ${event.round} 天 ☀️`;
      return <SectionMarker>{label}</SectionMarker>;
    }
    return (
      <div className="grid grid-cols-[50px_1fr] gap-2.5 py-1 font-mono text-[12px]">
        <div className="text-smoke-dim text-[10px] pt-0.5">{ts}</div>
        <div className="text-smoke">
          <em className="not-italic">{labels[phase] ?? phase}</em>
        </div>
      </div>
    );
  }

  // === speech / last_words ===
  if (event.kind === "speech" || event.kind === "last_words") {
    const speaker = p.speaker;
    const isWolfChat = event.channel === "wolf_chat";
    const isLast = event.kind === "last_words";
    const tone: keyof typeof ACTOR_TONE = isWolfChat ? "wolf" : "default";

    return (
      <div className="grid grid-cols-[50px_1fr] gap-2.5 py-1.5 font-mono text-[12px] leading-[1.55]">
        <div className="text-smoke-dim text-[10px] pt-0.5">{ts}</div>
        <div className="text-ivory">
          <ActorBadge tone={tone}>
            {speaker}号{isWolfChat ? " WOLF" : ""}{isLast ? " 遗言" : ""}
          </ActorBadge>
          <span>{isLast ? <em className="text-smoke not-italic italic">「{p.text}」</em> : `「${p.text}」`}</span>
          {isLatest && <TypingCursor />}
        </div>
      </div>
    );
  }

  // === vote ===
  if (event.kind === "vote") {
    return (
      <div className="grid grid-cols-[50px_1fr] gap-2.5 py-1 font-mono text-[12px]">
        <div className="text-smoke-dim text-[10px] pt-0.5">{ts}</div>
        <div className="text-smoke">
          <ActorBadge>🗳️ {p.voter}号</ActorBadge>
          → <span className="text-ivory">{p.target}号</span>
        </div>
      </div>
    );
  }

  // === night_result ===
  if (event.kind === "night_result") {
    const deaths = (event.payload.deaths as string[]) ?? [];
    return (
      <div className="my-3 px-4 py-3.5 bg-bg-card border-l-2 border-blood font-serif text-[15px] leading-[1.5] text-ivory">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-smoke mb-1">
          NIGHT RESULT
        </div>
        {deaths.length === 0 ? "平安夜,无人死亡" : `${deaths.map((d) => `${d}号`).join("、")} 死亡`}
      </div>
    );
  }

  // === vote_result ===
  if (event.kind === "vote_result") {
    const loser = p.loser as unknown as string | null;
    const tally = event.payload.tally as Record<string, number>;
    const sortedTally = Object.entries(tally).sort((a, b) => b[1] - a[1]);
    const maxVotes = Math.max(...Object.values(tally), 1);

    return (
      <div className={cn(
        "my-3 px-4 py-3.5 bg-bg-card border-l-2 font-serif text-[14px] leading-[1.5] text-ivory",
        loser ? "border-blood" : "border-candle",
      )}>
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-smoke mb-1.5">
          VOTE RESULT {loser ? `— ${loser} 号 出局` : "— 平票, 无人出局"}
        </div>
        <div className="mt-2 grid grid-cols-[auto_1fr_auto] gap-x-3.5 gap-y-1.5 items-center">
          {sortedTally.map(([pid, n]) => (
            <FragmentRow key={pid} pid={pid} n={n} max={maxVotes} dim={pid !== loser} />
          ))}
        </div>
      </div>
    );
  }

  // === game_end ===
  if (event.kind === "game_end") {
    return (
      <div className="my-4 px-4 py-4 bg-bg-card border-l-2 border-candle font-serif text-[16px] text-ivory">
        <div className="font-mono text-[10px] tracking-[0.2em] uppercase text-smoke mb-1">
          GAME END
        </div>
        🏁 胜利方: <span className="text-candle">{String(p.winner)}</span>
      </div>
    );
  }

  return null;
}

function FragmentRow({ pid, n, max, dim }: { pid: string; n: number; max: number; dim: boolean }) {
  return (
    <>
      <span className={cn("font-mono text-[12px] tracking-[0.05em]", dim && "text-smoke")}>
        {pid} 号
      </span>
      <span className="h-1 bg-line relative overflow-hidden">
        <span
          className={cn("absolute inset-y-0 left-0", dim ? "bg-smoke" : "bg-blood")}
          style={{ width: `${(n / max) * 100}%` }}
        />
      </span>
      <span className={cn("font-mono text-[12px] tabular", dim ? "text-smoke" : "text-ivory")}>
        {n}
      </span>
    </>
  );
}
