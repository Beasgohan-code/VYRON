# ---------------------------------------------------------------------------
#  VYRON — sleep timers
#
#  `/timer 30` stops playback and leaves the voice chat half an hour later, so
#  nobody has to wake up to `/stop`. Timers are per chat, in memory, and can be
#  inspected or cancelled at any time.
# ---------------------------------------------------------------------------
from __future__ import annotations

import re
from dataclasses import dataclass, field

MAX_MINUTES = 24 * 60

_UNIT = {"s": 1 / 60, "m": 1, "h": 60}
_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(h|m|s)?", re.I)


def parse_duration(raw: str | int | float | None) -> int | None:
    """``"30"``, ``"10m"``, ``"1h30m"``, ``"off"`` → minutes (or None = off).

    Bare numbers are minutes. Returns ``None`` for "off", ``0`` for nonsense —
    callers complain about the zero.
    """
    if raw is None:
        return 0
    text = str(raw).strip().lower()
    if not text:
        return 0
    if text in {"off", "stop", "cancel", "none", "0"}:
        return None
    if text.startswith("-"):
        return 0
    if text.isdigit():
        return min(MAX_MINUTES, int(text))

    total = 0.0
    matched = False
    for value, unit in _PART.findall(text):
        matched = True
        total += float(value) * _UNIT.get((unit or "m").lower(), 1)
    if not matched or total <= 0:
        return 0
    return max(1, min(MAX_MINUTES, round(total)))


def humanise(minutes: int) -> str:
    if minutes >= 60:
        hours, rest = divmod(minutes, 60)
        return f"{hours}h" + (f" {rest}m" if rest else "")
    return f"{minutes}m"


@dataclass
class TimerEntry:
    chat_id: int
    minutes: int
    task: object = None
    due: float = 0.0
    meta: dict = field(default_factory=dict)


class TimerBoard:
    """In-memory registry — one timer per chat."""

    def __init__(self) -> None:
        self._items: dict[int, TimerEntry] = {}

    def get(self, chat_id: int) -> TimerEntry | None:
        return self._items.get(int(chat_id))

    def set(self, chat_id: int, minutes: int, *, due: float, task=None) -> TimerEntry:
        self.cancel(chat_id)  # a new timer replaces (and stops) the old one
        entry = TimerEntry(chat_id=int(chat_id), minutes=int(minutes), task=task, due=float(due))
        self._items[int(chat_id)] = entry
        return entry

    def cancel(self, chat_id: int, *, kill: bool = True) -> bool:
        entry = self._items.pop(int(chat_id), None)
        if entry is None:
            return False
        task = entry.task
        if kill and task is not None and hasattr(task, "cancel") and not task.done():
            task.cancel()
        return True

    def clear(self) -> None:
        for chat_id in list(self._items):
            self.cancel(chat_id)

    def remaining(self, chat_id: int, now: float) -> int:
        entry = self._items.get(int(chat_id))
        if entry is None:
            return 0
        return max(0, int(round(entry.due - now)))

    def __len__(self) -> int:  # pragma: no cover - convenience
        return len(self._items)


__all__ = ["MAX_MINUTES", "TimerBoard", "TimerEntry", "humanise", "parse_duration"]
