import { cn } from "@/lib/cn";

/** 跳动的 N 个点, 颜色继承自 currentColor */
export function DotPulse({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-[3px]", className)}>
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1 w-1 rounded-full bg-current animate-[wolfpack-pulse_1.2s_ease-in-out_infinite]"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
      <style>{`
        @keyframes wolfpack-pulse {
          0%, 100% { opacity: 0.25; transform: scale(0.8); }
          50%      { opacity: 1;    transform: scale(1.2); }
        }
      `}</style>
    </span>
  );
}
