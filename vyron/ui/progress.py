# ---------------------------------------------------------------------------
#  VYRON — progress bars, durations and human formatting
#  Pure functions only: everything here is unit-tested in tests/.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

import math
import re
import time

# The bar is a line of music, not a load meter: solid blocks for what has
# already played, light dashes for what is left, and a ring as the playhead.
# It is the shape people already read in every music bot — it survives being
# half a centimetre tall on a phone, which a thin line does not.
# Box drawing, not blocks: "█"/"▬" render as a solid highlight and a hairline
# on iOS, which is what made the progress bar look like a stray character and a
# long rule. Heavy-vs-light strokes read as a bar on every client.
BAR_FULL = "━"
BAR_EMPTY = "─"
KNOB = "●"

def parse_duration(value: str | int | float | None) -> int:
    """Parse ``1:02:03``, ``3:45``, ``95`` or ``'95'`` into seconds."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))
    text = str(value).strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    parts = text.split(":")
    if len(parts) > 3 or not parts:
        return 0
    if not all(part.strip().isdigit() for part in parts):
        return 0
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return max(0, total)


def fmt_duration(seconds: int | float | None, *, pad_hours: bool = False) -> str:
    """Seconds → ``h:mm:ss`` / ``m:ss`` (never negative)."""
    total = max(0, int(seconds or 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours or pad_hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def length_label(track: Any) -> str:
    """How long *track* is, in human terms — live streams have no length."""
    if getattr(track, "is_live", False):
        return "live"
    seconds = int(getattr(track, "duration", 0) or 0)
    return fmt_duration(seconds) if seconds else "—"


def progress_bar(
    elapsed: float,
    total: float,
    *,
    length: int = 13,
    knob: str = KNOB,
    full: str = BAR_FULL,
    empty: str = BAR_EMPTY,
) -> str:
    """Render ``━━━━━♡─────`` for a track position."""
    length = max(5, int(length))
    total = float(total or 0)
    elapsed = max(0.0, float(elapsed or 0))
    if total <= 0:
        pct = 0.0
    else:
        pct = min(1.0, elapsed / total)
    filled = min(length - 1, int(math.floor(pct * (length - 1))))
    return f"{full * filled}{knob}{empty * (length - 1 - filled)}"


def percentage(elapsed: float, total: float) -> int:
    if not total:
        return 0
    return min(100, max(0, int(round(elapsed / total * 100))))


def human_time(seconds: float | int) -> str:
    """Compact 4d 3h / 2h 5m / 45s."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def human_clock(seconds: float | int) -> str:
    """`3d 8h 40m 34s` — every unit, for a status line.

    `human_time` answers "how long, roughly" and stops at two units (right for a
    track length); a welcome card that says `3d 8h` next to an uptime label
    reads like a rounding error. This one is exact to the second, and drops the
    leading units that are zero so a fresh process shows `42s`, not `0d 0h 0m`.
    """
    total = int(max(0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if days or hours:
        parts.append(f"{hours}h")
    if days or hours or minutes:
        parts.append(f"{minutes}m")
    parts.append(f"{secs:02d}s" if parts else f"{secs}s")
    return " ".join(parts)


def human_size(num_bytes: float | int) -> str:
    size = float(max(0, num_bytes or 0))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def compact_number(value: int | float) -> str:
    value = float(value or 0)
    for limit, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if value >= limit:
            trimmed = value / limit
            return f"{trimmed:.1f}{suffix}".replace(".0", "")
    return str(int(value))


def truncate(text: str, limit: int = 42, suffix: str = "…") -> str:
    if not text:
        return ""
    clean = " ".join(str(text).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - len(suffix))].rstrip() + suffix


def now() -> float:
    return time.monotonic()


def escape_markdown(text: str) -> str:
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!])", r"\\\1", str(text or ""))


__all__ = [
    "compact_number",
    "escape_markdown",
    "fmt_duration",
    "human_clock",
    "human_size",
    "human_time",
    "now",
    "parse_duration",
    "percentage",
    "progress_bar",
    "truncate",
]
