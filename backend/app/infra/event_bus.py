"""EventBus — 进程内 pub/sub.

纯 asyncio.Queue + 订阅者列表, 不依赖任何外部服务.

用途:
  - 后端业务侧 (Channel.append, Phase 跑完一段) publish(...) 一条事件
  - SSE 端点 subscribe() 拿到 queue, async for 读出每条事件推给前端

EventBus 不缓存历史 (订阅者只看到 subscribe 之后的事件). 如果需要 "断线重连
后从头回放", 由调用方自己存历史 (e.g. 从 SQLite/Channel 里读出过去事件 +
继续订阅新事件 = 完整回放).

支持多个独立的 bus (按 key 隔离, e.g. 每局一个 bus):
    bus = get_bus(game_id)
    bus.publish(event)
    queue = bus.subscribe()
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, AsyncIterator, Optional


# ---------------------------------------------------------------------------
# 单个 EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """一个频道的 pub/sub. 多个订阅者 fan-out, 一个 publish 推所有 queue."""

    def __init__(self, name: str = "") -> None:
        self.name = name
        self._subscribers: list[asyncio.Queue[Any]] = []
        self._closed = False

    def publish(self, event: Any) -> None:
        """同步发布 (非 async). 给所有订阅者 put_nowait."""
        if self._closed:
            return
        for queue in self._subscribers:
            queue.put_nowait(event)

    def subscribe(self) -> asyncio.Queue[Any]:
        """注册一个新订阅者, 返回它独占的 queue."""
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Any]) -> None:
        """取消订阅 (SSE 客户端断开时调用)."""
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def close(self) -> None:
        """关闭 bus, 唤醒所有 subscriber 让它们退出 (put None 作 sentinel)."""
        self._closed = True
        for queue in self._subscribers:
            queue.put_nowait(None)
        self._subscribers.clear()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    async def stream(self) -> AsyncIterator[Any]:
        """便捷写法: 自动注册 + 迭代 + 退出时反注册."""
        queue = self.subscribe()
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield event
        finally:
            self.unsubscribe(queue)


# ---------------------------------------------------------------------------
# 多 bus 管理 (e.g. 每个 game_id 一个 bus)
# ---------------------------------------------------------------------------


_buses: dict[str, EventBus] = defaultdict(lambda: EventBus())


def get_bus(key: str = "global") -> EventBus:
    """按 key 拿 / 创建 bus. 默认全局共用 'global'."""
    if key not in _buses:
        _buses[key] = EventBus(name=key)
    return _buses[key]


def drop_bus(key: str) -> Optional[EventBus]:
    """关闭并删除指定 bus (对局结束时调用)."""
    bus = _buses.pop(key, None)
    if bus is not None:
        bus.close()
    return bus
