# ---------------------------------------------------------------------------
#  VYRON — streaming budget
#
#  `/api/stream` proxies bytes: every listener costs the deployment real
#  bandwidth, and a signed-in browser can ask for as many tracks as it likes.
#  Two cheap guards keep that from becoming somebody else's CDN:
#
#      · a per-identity sliding window on *new* streams (seeks reuse the same
#        one, so this never interrupts normal listening), and
#      · a hard cap on streams in flight, per identity and overall, so one
#        phone on a bad connection cannot pin every worker slot.
#
#  Both counters live in this process and reset on deploy — they are a guard
#  rail, not billing. Nothing here is persisted, and nothing here can fail a
#  request that would otherwise have worked.
# ---------------------------------------------------------------------------
from __future__ import annotations

import time

#: How many tracks one browser may *start* per minute. A player asks for one
#: at a time; a person skipping quickly is well under this.
PER_MINUTE = 30
#: …and per hour, which is what actually bounds bandwidth abuse.
PER_HOUR = 240
#: Streams in flight. Two is enough for a player plus a preloaded next track.
PARALLEL_PER_USER = 3
PARALLEL_TOTAL = 10

_WINDOW_MINUTE = 60.0
_WINDOW_HOUR = 3600.0
#: The same track asked for again this soon is the *same* stream, not a new
#: one: a browser re-requests it after a seek, a toggle, a lock-screen change
#: or a retry. Counting those was the production bug — one listener sat at 30
#: "starts" a minute while listening to two songs, was refused with a 429, and
#: the retry that followed counted again.
REPEAT_WINDOW = 900.0
#: A ceiling on the repeat table so a long uptime cannot grow it forever.
_SEEN_MAX = 4096


class BudgetExceeded(RuntimeError):
    """Raised when an identity has no stream slot left."""

    def __init__(self, reason: str, retry_after: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = max(1, int(retry_after))


class Budget:
    """Sliding-window rate limit + parallel-stream slots, per identity."""

    def __init__(
        self,
        *,
        per_minute: int = PER_MINUTE,
        per_hour: int = PER_HOUR,
        per_user: int = PARALLEL_PER_USER,
        total: int = PARALLEL_TOTAL,
    ) -> None:
        self.per_minute = per_minute
        self.per_hour = per_hour
        self.per_user = per_user
        self.total = total
        self._starts: dict[str, list[float]] = {}
        self._active: dict[str, int] = {}
        # (identity, media) → when it was last counted as a start
        self._seen: dict[tuple[str, str], float] = {}

    # ── window ────────────────────────────────────────────────────────────
    def _recent(self, key: str, now: float) -> list[float]:
        history = [stamp for stamp in self._starts.get(key, []) if now - stamp < _WINDOW_HOUR]
        if history:
            self._starts[key] = history
        else:
            self._starts.pop(key, None)
        return history

    def _repeat(self, key: str, media: str, now: float) -> bool:
        """Was this exact track already counted for *key* a moment ago?"""
        if not media:
            return False
        stamp = self._seen.get((key, media))
        return stamp is not None and now - stamp < REPEAT_WINDOW

    def check(self, key: str, now: float | None = None, *, media: str = "") -> None:
        """Raise :class:`BudgetExceeded` if *key* may not start another stream.

        A repeat of a track that has already been counted is always allowed:
        the listener is not opening a new stream, they are rewinding the one
        they already have.
        """
        now = time.monotonic() if now is None else now
        if self._repeat(key, media, now):
            return
        history = self._recent(key, now)
        minute = [stamp for stamp in history if now - stamp < _WINDOW_MINUTE]
        if len(minute) >= self.per_minute:
            oldest = min(minute)
            raise BudgetExceeded("too many tracks started this minute", _WINDOW_MINUTE - (now - oldest))
        if len(history) >= self.per_hour:
            oldest = min(history)
            raise BudgetExceeded("hourly streaming limit reached", _WINDOW_HOUR - (now - oldest))

    def start(self, key: str, now: float | None = None, *, media: str = "") -> None:
        """Count one new stream for *key* (call after :meth:`check`)."""
        now = time.monotonic() if now is None else now
        self._recent(key, now)
        if media:
            repeat = self._repeat(key, media, now)
            self._seen[(key, media)] = now
            if len(self._seen) > _SEEN_MAX:
                self._prune_seen(now)
            if repeat:
                return          # the same track, still playing: not a new start
        self._starts.setdefault(key, []).append(now)

    def _prune_seen(self, now: float) -> None:
        for pair, stamp in list(self._seen.items()):
            if now - stamp >= REPEAT_WINDOW:
                self._seen.pop(pair, None)

    # ── slots ─────────────────────────────────────────────────────────────
    def take_slot(self, key: str) -> None:
        if self._active.get(key, 0) >= self.per_user:
            raise BudgetExceeded("too many tracks streaming at once", 5)
        if sum(self._active.values()) >= self.total:
            raise BudgetExceeded("the server is at its streaming capacity", 5)
        self._active[key] = self._active.get(key, 0) + 1

    def drop_slot(self, key: str) -> None:
        remaining = self._active.get(key, 0) - 1
        if remaining > 0:
            self._active[key] = remaining
        else:
            self._active.pop(key, None)

    # ── introspection ─────────────────────────────────────────────────────
    def snapshot(self) -> dict[str, int]:
        return {
            "active": sum(self._active.values()),
            "identities": len(self._active),
            "per_minute": self.per_minute,
            "per_hour": self.per_hour,
            "parallel": self.total,
        }

    def reset(self) -> None:
        self._starts.clear()
        self._active.clear()
        self._seen.clear()


BUDGET = Budget()


def identity_key(user_id: int, remote: str | None) -> str:
    """One bucket per signed-in person; anonymous traffic shares its address."""
    return f"u{user_id}" if user_id else f"ip{remote or 'unknown'}"


__all__ = [
    "BUDGET",
    "Budget",
    "BudgetExceeded",
    "PARALLEL_PER_USER",
    "PARALLEL_TOTAL",
    "PER_HOUR",
    "PER_MINUTE",
    "REPEAT_WINDOW",
    "identity_key",
]
