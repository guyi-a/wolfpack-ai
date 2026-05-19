import { cn } from "@/lib/cn";
import { DotPulse } from "@/components/atoms/DotPulse";
import { ROLE_LABEL } from "@/lib/mock";
import type { Player, PlayerState } from "@/lib/types";

interface PlayerCardProps {
  player: Player;
  state: PlayerState;
  toolName?: string;
  active?: boolean;
  onClick?: () => void;
}

const STATE_STYLES = {
  thinking:     { ring: "border-candle shadow-[0_0_0_1px_rgba(217,162,76,0.15),0_0_24px_-10px_rgba(217,162,76,0.4)]", text: "text-candle" },
  tool_calling: { ring: "border-moon shadow-[0_0_0_1px_rgba(92,127,143,0.15),0_0_24px_-10px_rgba(92,127,143,0.5)]",   text: "text-moon"   },
  speaking:     { ring: "border-ivory",  text: "text-ivory" },
  idle:         { ring: "border-line",   text: "text-smoke" },
} as const;

export function PlayerCard({ player, state, toolName, active, onClick }: PlayerCardProps) {
  const role = ROLE_LABEL[player.role];
  const dead = !player.alive;
  const style = dead ? STATE_STYLES.idle : STATE_STYLES[state];

  const stateLabel = (() => {
    if (dead) return `DEAD · r${player.died_at_round ?? "?"} ${player.death_cause ?? ""}`;
    if (state === "thinking")     return "THINKING";
    if (state === "tool_calling") return (toolName ?? "TOOL").toUpperCase();
    if (state === "speaking")     return "SPEAKING";
    return "— idle";
  })();

  const stateColor = dead ? "text-blood" : style.text;

  return (
    <button
      onClick={onClick}
      className={cn(
        "group relative w-full text-left",
        "grid grid-cols-[48px_1fr_auto] gap-4 items-center",
        "border bg-bg-deep",
        "px-5 py-5",
        "transition-all duration-200",
        "hover:border-smoke",
        dead && "bg-bg-deep/60 border-dashed",
        active
          ? "border-ivory bg-bg-soft"
          : dead
            ? "border-blood/30"
            : style.ring,
      )}
    >
      <div className={cn(
        "font-serif text-[42px] font-light leading-none text-center",
        dead ? "text-smoke line-through" : "text-ivory",
      )}>
        {player.player_id}
      </div>

      <div className="flex flex-col gap-1 min-w-0">
        <div className="font-mono text-[13px] tracking-[0.18em] uppercase text-ivory font-medium">
          {role.upper}
        </div>
        <div className="font-mono text-[11px] text-smoke truncate">
          {player.model.split("/").pop()}
        </div>
        <div className={cn(
          "mt-1 flex items-center gap-1.5 font-mono text-[11px] tracking-[0.1em] uppercase",
          stateColor,
        )}>
          {stateLabel}
          {!dead && (state === "thinking" || state === "tool_calling") && (
            <DotPulse />
          )}
        </div>
      </div>

      <span className="text-xl opacity-85 group-[.active]:opacity-100">
        {role.icon}
      </span>
    </button>
  );
}
