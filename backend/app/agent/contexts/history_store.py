"""HistoryStore 协议 + 内存实现.

按 player_id 存取一条会话历史 (list[HistoryEntry]).
Redis 实现后续按同接口补一个 RedisHistoryStore.
"""

from typing import Protocol

from app.agent.contexts.history import HistoryEntry


class HistoryStore(Protocol):
    """会话历史存取协议."""

    def load(self, player_id: str) -> list[HistoryEntry]: ...

    def append(self, player_id: str, entry: HistoryEntry) -> None: ...

    def append_many(self, player_id: str, entries: list[HistoryEntry]) -> None: ...

    def clear(self, player_id: str) -> None: ...


class InMemoryHistoryStore:
    """内存实现 — 进程内 dict, 仅供单进程测试与 demo 使用."""

    def __init__(self) -> None:
        self._data: dict[str, list[HistoryEntry]] = {}

    def load(self, player_id: str) -> list[HistoryEntry]:
        return list(self._data.get(player_id, []))

    def append(self, player_id: str, entry: HistoryEntry) -> None:
        self._data.setdefault(player_id, []).append(entry)

    def append_many(self, player_id: str, entries: list[HistoryEntry]) -> None:
        if not entries:
            return
        self._data.setdefault(player_id, []).extend(entries)

    def clear(self, player_id: str) -> None:
        self._data.pop(player_id, None)
