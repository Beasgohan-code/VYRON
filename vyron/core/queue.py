# ---------------------------------------------------------------------------
#  VYRON — queue model
#  Pure data structures: no Telegram, no network.  Unit-tested in tests/.
# ---------------------------------------------------------------------------
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class LoopMode(str, Enum):
    OFF = "off"
    ONE = "one"
    ALL = "all"

    @classmethod
    def parse(cls, value: str | "LoopMode" | None) -> "LoopMode":
        if isinstance(value, LoopMode):
            return value
        try:
            return cls(str(value).lower())
        except Exception:
            return cls.OFF

    @property
    def label(self) -> str:
        return {"off": "Off", "one": "Track", "all": "Queue"}[self.value]

    def next(self) -> "LoopMode":
        order = [LoopMode.OFF, LoopMode.ONE, LoopMode.ALL]
        return order[(order.index(self) + 1) % len(order)]


@dataclass
class Track:
    id: str
    title: str
    duration: int = 0
    url: str = ""
    uploader: str = ""
    thumbnail: str | None = None
    is_video: bool = False
    source: str = "youtube"
    requested_by: int = 0
    requested_name: str = ""
    stream_url: str | None = None
    filesize: int = 0
    views: int = 0

    # ── display ────────────────────────────────────────────────────────────
    @property
    def short(self) -> str:
        from vyron.ui.progress import fmt_duration, truncate

        return f"{truncate(self.title, 46)} · {fmt_duration(self.duration)}"

    @property
    def watch_url(self) -> str:
        if self.source == "youtube" and self.id:
            return f"https://youtu.be/{self.id}"
        return self.url or ""

    def __hash__(self) -> int:  # pragma: no cover
        return hash((self.source, self.id))

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, Track)
            and other.source == self.source
            and other.id == self.id
        )

    # ── (de)serialisation ──────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "duration": self.duration,
            "url": self.url,
            "uploader": self.uploader,
            "thumbnail": self.thumbnail,
            "is_video": self.is_video,
            "source": self.source,
            "requested_by": self.requested_by,
            "requested_name": self.requested_name,
            "filesize": self.filesize,
            "views": self.views,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Track":
        return cls(
            id=str(data.get("id", "")),
            title=str(data.get("title", "Unknown")),
            duration=int(data.get("duration") or 0),
            url=str(data.get("url", "")),
            uploader=str(data.get("uploader") or ""),
            thumbnail=data.get("thumbnail"),
            is_video=bool(data.get("is_video")),
            source=str(data.get("source") or "youtube"),
            requested_by=int(data.get("requested_by") or 0),
            requested_name=str(data.get("requested_name") or ""),
            filesize=int(data.get("filesize") or 0),
            views=int(data.get("views") or 0),
        )


@dataclass
class ChatState:
    chat_id: int
    queue: list[Track] = field(default_factory=list)
    current: Track | None = None
    history: list[Track] = field(default_factory=list)
    loop: LoopMode = LoopMode.OFF
    autoplay: bool = True
    shuffle: bool = False
    volume: int = 100
    paused: bool = False
    playing: bool = False
    is_video: bool = False
    always_on: bool = False
    effects: list[str] = field(default_factory=list)

    # timing (monotonic clock; see vyron.ui.progress.now)
    started_at: float = 0.0
    offset: float = 0.0          # played duration before the current stream start
    paused_at: float | None = None

    # UI handles
    np_message_id: int | None = None
    last_activity: float = field(default_factory=time.monotonic)
    total_played: int = 0

    # ── maths ──────────────────────────────────────────────────────────────
    def elapsed(self, clock: float | None = None) -> float:
        if not self.playing or not self.current:
            return self.offset
        if self.paused and self.paused_at is not None:
            return self.offset
        if not self.started_at:
            return self.offset
        reference = clock if clock is not None else time.monotonic()
        return self.offset + max(0.0, reference - self.started_at)

    def remaining(self, clock: float | None = None) -> float:
        if not self.current or not self.current.duration:
            return 0.0
        return max(0.0, self.current.duration - self.elapsed(clock))

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def reset_stream(self) -> None:
        self.playing = False
        self.paused = False
        self.started_at = 0.0
        self.offset = 0.0
        self.paused_at = None


class QueueManager:
    """Owns one :class:`ChatState` per chat."""

    def __init__(self, default_volume: int = 100, autoplay: bool = True) -> None:
        self._states: dict[int, ChatState] = {}
        self.default_volume = max(1, min(200, int(default_volume)))
        self.autoplay_default = bool(autoplay)

    # ── state access ───────────────────────────────────────────────────────
    def get(self, chat_id: int) -> ChatState:
        state = self._states.get(int(chat_id))
        if state is None:
            state = ChatState(
                chat_id=int(chat_id),
                volume=self.default_volume,
                autoplay=self.autoplay_default,
            )
            self._states[int(chat_id)] = state
        return state

    def exists(self, chat_id: int) -> bool:
        return int(chat_id) in self._states

    def all(self) -> Iterable[ChatState]:
        return list(self._states.values())

    def drop(self, chat_id: int) -> None:
        self._states.pop(int(chat_id), None)

    # ── queue mutation ─────────────────────────────────────────────────────
    def add(self, chat_id: int, track: Track, *, index: int | None = None, max_size: int = 0) -> int:
        """Queue *track*.  Returns its 1-based position (0 if rejected)."""
        state = self.get(chat_id)
        if track in state.queue or (state.current and track == state.current):
            return -1
        if max_size and len(state.queue) >= max_size:
            return 0
        if index is None:
            state.queue.append(track)
            return len(state.queue)
        index = max(0, min(len(state.queue), index))
        state.queue.insert(index, track)
        return index + 1

    def pop_next(self) -> Track | None:
        raise NotImplementedError  # replaced by pop_next_for()

    def pop_next_for(self, chat_id: int) -> Track | None:
        state = self.get(chat_id)
        if not state.queue:
            return None
        if state.shuffle:
            return state.queue.pop(random.randrange(len(state.queue)))
        return state.queue.pop(0)

    def peek(self, chat_id: int, limit: int = 10) -> list[Track]:
        state = self.get(chat_id)
        return state.queue[: max(0, limit)]

    def remove(self, chat_id: int, position: int) -> Track | None:
        """Remove by 1-based position."""
        state = self.get(chat_id)
        if position <= 0 or position > len(state.queue):
            return None
        return state.queue.pop(position - 1)

    def move(self, chat_id: int, source: int, target: int) -> bool:
        state = self.get(chat_id)
        if not (1 <= source <= len(state.queue) and 1 <= target <= len(state.queue)):
            return False
        track = state.queue.pop(source - 1)
        state.queue.insert(target - 1, track)
        return True

    def clear(self, chat_id: int, *, keep_current: bool = True) -> int:
        state = self.get(chat_id)
        removed = len(state.queue)
        state.queue.clear()
        if not keep_current:
            state.current = None
        return removed

    def rotate_current_to_end(self, chat_id: int) -> None:
        """Loop-all: push the finished track to the back of the queue."""
        state = self.get(chat_id)
        if state.current:
            state.queue.append(state.current)

    def shuffle(self, chat_id: int) -> int:
        state = self.get(chat_id)
        random.shuffle(state.queue)
        return len(state.queue)

    def size(self, chat_id: int) -> int:
        return len(self.get(chat_id).queue)

    def is_idle(self, chat_id: int) -> bool:
        state = self.get(chat_id)
        return not state.playing and state.current is None and not state.queue

    def snapshot(self) -> dict[int, dict]:
        return {
            chat_id: {
                "queue": [t.to_dict() for t in state.queue],
                "current": state.current.to_dict() if state.current else None,
                "loop": state.loop.value,
                "autoplay": state.autoplay,
                "shuffle": state.shuffle,
                "volume": state.volume,
                "always_on": state.always_on,
                "effects": list(state.effects),
            }
            for chat_id, state in self._states.items()
        }


__all__ = ["ChatState", "LoopMode", "QueueManager", "Track"]
