# ---------------------------------------------------------------------------
#  VYRON — short-lived UI state (search pickers, download choices)
# ---------------------------------------------------------------------------
from __future__ import annotations

import time
from dataclasses import dataclass, field

from vyron.core.queue import Track


@dataclass
class PendingSearch:
    chat_id: int
    message_id: int
    user_id: int
    query: str
    tracks: list[Track] = field(default_factory=list)
    mode: str = "play"        # "play" | "download"
    video: bool = False
    created: float = field(default_factory=time.time)


_CACHE: dict[tuple[int, int], PendingSearch] = {}
_TTL = 900  # 15 minutes


def put(
    chat_id: int,
    message_id: int,
    user_id: int,
    query: str,
    tracks: list[Track],
    *,
    mode: str = "play",
    video: bool = False,
) -> PendingSearch:
    entry = PendingSearch(
        int(chat_id), int(message_id), int(user_id), query, tracks, mode=mode, video=video
    )
    _CACHE[(int(chat_id), int(message_id))] = entry
    purge()
    return entry


def get(chat_id: int, message_id: int) -> PendingSearch | None:
    entry = _CACHE.get((int(chat_id), int(message_id)))
    if entry and time.time() - entry.created < _TTL:
        return entry
    return None


def take(chat_id: int, message_id: int) -> PendingSearch | None:
    return _CACHE.pop((int(chat_id), int(message_id)), None)


def purge() -> int:
    cutoff = time.time() - _TTL
    stale = [key for key, entry in _CACHE.items() if entry.created < cutoff]
    for key in stale:
        _CACHE.pop(key, None)
    return len(stale)


__all__ = ["PendingSearch", "get", "purge", "put", "take"]
