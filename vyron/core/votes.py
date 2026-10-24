# ---------------------------------------------------------------------------
#  VYRON — group vote-skip
#
#  Pure bookkeeping: how many votes a chat needs, who has voted for the track
#  currently playing, and when the threshold is reached.  No Telegram, no
#  storage — the module in `vyron/modules/power.py` persists the threshold and
#  talks to the player, which keeps this file unit-testable.
# ---------------------------------------------------------------------------
from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_VOTES = 3
MAX_VOTES = 50


def clamp_votes(value: int | str | None) -> int:
    """Coerce a user-supplied threshold into ``0…MAX_VOTES`` (0 = disabled)."""
    try:
        number = int(str(value).strip()) if value is not None else DEFAULT_VOTES
    except (TypeError, ValueError):
        return DEFAULT_VOTES
    return max(0, min(MAX_VOTES, number))


@dataclass
class VoteTally:
    """Votes for **one** track.  Reset whenever the track changes."""

    track_key: str = ""
    needed: int = DEFAULT_VOTES
    voters: set[int] = field(default_factory=set)

    # ── state ──────────────────────────────────────────────────────────────
    def bind(self, track_key: str, needed: int) -> None:
        """Point the tally at a track, clearing stale votes."""
        needed = clamp_votes(needed)
        if track_key != self.track_key or needed != self.needed:
            self.track_key = track_key
            self.needed = needed
            self.voters.clear()

    @property
    def enabled(self) -> bool:
        return self.needed > 0

    @property
    def count(self) -> int:
        return len(self.voters)

    @property
    def remaining(self) -> int:
        return max(0, self.needed - len(self.voters)) if self.enabled else 0

    # ── voting ─────────────────────────────────────────────────────────────
    def cast(self, user_id: int) -> str:
        """Register a vote.

        Returns ``"voted"``, ``"duplicate"``, ``"disabled"`` or ``"passed"``
        (threshold reached — the caller should skip and :meth:`reset`).
        """
        if not self.enabled:
            return "disabled"
        if int(user_id) in self.voters:
            return "duplicate"
        self.voters.add(int(user_id))
        if len(self.voters) >= self.needed:
            return "passed"
        return "voted"

    def reset(self) -> None:
        self.voters.clear()


class VoteBoard:
    """One :class:`VoteTally` per chat."""

    def __init__(self) -> None:
        self._tallies: dict[int, VoteTally] = {}

    def get(self, chat_id: int) -> VoteTally:
        return self._tallies.setdefault(int(chat_id), VoteTally())

    def drop(self, chat_id: int) -> None:
        self._tallies.pop(int(chat_id), None)


__all__ = ["DEFAULT_VOTES", "MAX_VOTES", "VoteBoard", "VoteTally", "clamp_votes"]
