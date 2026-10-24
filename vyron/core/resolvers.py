# ---------------------------------------------------------------------------
#  VYRON — resolver health
# ---------------------------------------------------------------------------
# One small, honest scoreboard for every way this process can turn a video id
# into playable bytes: yt-dlp and each of its player clients, Invidious, Piped
# and Cobalt. Two jobs:
#
#   1. stop asking a source that just failed (a dead mirror otherwise costs the
#      user the full timeout on *every* track)
#   2. tell the truth in /health, /doctor and /sources — "which tier works from
#      this server, right now, and how fast"
#
# Nothing here holds a secret: source names, counters, latencies and a short
# error string only.
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field


@dataclass
class SourceStat:
    tries: int = 0
    wins: int = 0
    failures: int = 0
    latency_ms: float = 0.0  # last successful round-trip
    last_ok: float = 0.0
    last_fail: float = 0.0
    last_error: str = ""
    cooldown_until: float = 0.0
    streak: int = 0  # consecutive failures

    def to_dict(self) -> dict:
        data = asdict(self)
        data["ok"] = self.wins > 0 and (self.last_ok >= self.last_fail)
        data["cooling"] = max(0, round(self.cooldown_until - time.time(), 1))
        data["last_error"] = self.last_error[:160]
        for key in ("last_ok", "last_fail", "cooldown_until"):
            data[key] = round(data[key], 1)
        data["latency_ms"] = round(data["latency_ms"])
        return data


@dataclass
class Health:
    """Thread-safe scoreboard; the ladder runs in worker threads."""

    cooldown_base: float = 45.0  # first failure
    cooldown_max: float = 600.0  # a host that keeps failing is left alone
    _stats: dict[str, SourceStat] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _stat(self, source: str) -> SourceStat:
        return self._stats.setdefault(source, SourceStat())

    # ── writes ─────────────────────────────────────────────────────────────
    def record(
        self,
        source: str,
        ok: bool,
        *,
        ms: float = 0.0,
        error: str = "",
    ) -> SourceStat:
        with self._lock:
            stat = self._stat(source)
            stat.tries += 1
            if ok:
                stat.wins += 1
                stat.streak = 0
                stat.last_ok = time.time()
                stat.latency_ms = ms
                stat.cooldown_until = 0.0
            else:
                stat.failures += 1
                stat.streak += 1
                stat.last_fail = time.time()
                stat.last_error = (error or "failed")[:200]
                # exponential, capped: 45 s, 90 s, 180 s … 10 min
                wait = min(self.cooldown_max, self.cooldown_base * (2 ** (stat.streak - 1)))
                stat.cooldown_until = time.time() + wait
            return stat

    def cool(self, source: str, seconds: float) -> None:
        with self._lock:
            self._stat(source).cooldown_until = time.time() + max(0.0, seconds)

    def reset(self) -> None:
        with self._lock:
            self._stats.clear()

    # ── reads ──────────────────────────────────────────────────────────────
    def cooling(self, source: str) -> float:
        with self._lock:
            stat = self._stats.get(source)
            if stat is None:
                return 0.0
            return max(0.0, stat.cooldown_until - time.time())

    def available(self, source: str) -> bool:
        return self.cooling(source) <= 0

    def stat(self, source: str) -> dict:
        with self._lock:
            stat = self._stats.get(source)
            return stat.to_dict() if stat else SourceStat().to_dict()

    def stats(self) -> dict[str, dict]:
        with self._lock:
            snapshot = {name: stat.to_dict() for name, stat in self._stats.items()}
        return dict(sorted(snapshot.items()))

    def summary(self) -> dict:
        """The shape /health exposes: counts per family, not per host."""
        families: dict[str, dict[str, int]] = {}
        for name, stat in self.stats().items():
            family = name.split(":", 1)[0]
            bucket = families.setdefault(family, {"sources": 0, "wins": 0, "failures": 0, "cooling": 0})
            bucket["sources"] += 1
            bucket["wins"] += stat["wins"]
            bucket["failures"] += stat["failures"]
            if stat["cooling"]:
                bucket["cooling"] += 1
        best = max(
            ((name, stat) for name, stat in self.stats().items() if stat["wins"]),
            key=lambda item: (item[1]["wins"], -item[1]["latency_ms"]),
            default=None,
        )
        return {
            "families": families,
            "best": {"source": best[0], "latency_ms": best[1]["latency_ms"]} if best else None,
        }


# The process-wide scoreboard. `search` and `public_streams` share it.
HEALTH = Health()


def reset() -> None:
    """Tests swap deployments; the scoreboard has to forget the old one."""
    HEALTH.reset()


__all__ = ["HEALTH", "Health", "SourceStat", "reset"]
