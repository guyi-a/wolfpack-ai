/** 闪烁打字光标 */
export function TypingCursor() {
  return (
    <span
      className="inline-block w-[6px] h-[13px] bg-ivory align-[-2px] ml-[2px] animate-[wolfpack-blink_1s_steps(1)_infinite]"
    >
      <style>{`
        @keyframes wolfpack-blink { 50% { opacity: 0; } }
      `}</style>
    </span>
  );
}
