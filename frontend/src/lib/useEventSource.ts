import { useEffect, useRef } from "react";

import type { SseEvent } from "@/lib/types";

/**
 * 订阅 SSE; 每条事件回调 onEvent. URL 变化或卸载时自动关流.
 *
 * 后端 GET /api/games/{id}/stream 会先回放 SQLite 历史再接续 bus.
 * 已结束的局也能正常订阅 (回放完直接 stream_end), 收到 stream_end 后主动 close 不再重连.
 */
export function useEventSource(
  url: string | null,
  onEvent: (e: SseEvent) => void,
  onError?: (err: Event) => void,
) {
  const onEventRef = useRef(onEvent);
  const onErrorRef = useRef(onError);
  onEventRef.current = onEvent;
  onErrorRef.current = onError;

  useEffect(() => {
    if (!url) return;
    const es = new EventSource(url);

    es.onmessage = (msg) => {
      try {
        const parsed = JSON.parse(msg.data) as SseEvent;
        onEventRef.current(parsed);
        // 收到流终止信号 → 主动 close 不让浏览器自动重连
        if (parsed.kind === "stream_end") {
          es.close();
        }
      } catch (err) {
        console.warn("SSE parse failed:", err, msg.data);
      }
    };

    es.onerror = (err) => {
      onErrorRef.current?.(err);
      // EventSource 自带重连; 非 stream_end 路径就让它重连
    };

    return () => {
      es.close();
    };
  }, [url]);
}
