# ---------------------------------------------------------------------------
#  VYRON — the substitution tier: the same song, from an engine that works
# ---------------------------------------------------------------------------
# `Failed to extract any player response` on every client is not a bug in
# yt-dlp and it is not fixable with another player client: YouTube has decided
# this server's IP is not allowed to see the player page. Cookies and PO tokens
# solve it for a laptop, not for a free host.
#
# The song, however, is not YouTube-only. JioSaavn, Audius and SoundCloud hand
# out *audio files* over a plain JSON API with no key and no IP reputation, and
# one of them almost always has the track the listener asked for. So when the
# YouTube path is closed, VYRON matches the track against those catalogues and
# streams the best copy of the same song.
#
# The matching is deliberately conservative: a wrong song is worse than a clear
# error. A candidate has to share most of the title's meaningful words, and if
# BOTH durations are known and differ by more than a few seconds it is rejected
# outright (that is a different cut, a remix or a 30-second preview).
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from vyron.core.queue import Track
from vyron.core.sources import DIRECT_SOURCES

if TYPE_CHECKING:  # the search engine imports this module, so only for typing
    from vyron.core.search import StreamInfo

logger = logging.getLogger(__name__)

# Words that describe the upload, not the song: "[Official Video]", "Lyrics",
# "8K Remastered", "feat. X". Removing them is what lets a YouTube title match
# a catalogue title.
_NOISE_WORDS = frozenset(
    {
        "official", "video", "audio", "lyric", "lyrics", "full", "song", "songs",
        "hd", "hq", "4k", "8k", "remastered", "remaster", "version", "music",
        "visualizer", "visualiser", "explicit", "clean", "topic", "ft", "feat",
        "featuring", "prod", "the", "a", "an", "and", "of", "in", "on", "with",
        "from", "by", "for", "to", "is", "it", "me", "my", "original", "movie",
    }
)

# Variants nobody asked for unless the query itself asked for them.
_VARIANT_WORDS = (
    "lofi", "lo-fi", "slowed", "reverb", "remix", "cover", "karaoke",
    "instrumental", "8d", "nightcore", "sped", "speed",
)

_BRACKETS = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_TOPIC_SUFFIX = re.compile(r"[\-\u2013\u2014]\s*topic\s*$", re.I)
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# How good a match has to be before it is played instead of an error.
ACCEPT_SCORE = 0.65
# Nothing older than this is re-used; a catalogue URL can expire.
CACHE_TTL = 3600.0
# One source gets this long before it is skipped for this lookup.
SOURCE_TIMEOUT = 7.0

_CACHE: dict[str, tuple[float, Track | None]] = {}


# ── text ────────────────────────────────────────────────────────────────────
def _fold(text: str) -> str:
    """Strip accents so \"Kesariyā\" and \"Kesariya\" compare equal."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def clean_title(text: str) -> str:
    """A title with the upload's noise removed, still in its own words."""
    raw = _BRACKETS.sub(" ", str(text or ""))
    raw = _TOPIC_SUFFIX.sub("", raw)
    raw = raw.replace("|", " ").replace("\u2013", " ").replace("\u2014", " ")
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip(" -_\u2013\u2014.")


def _words(text: str) -> set[str]:
    """Meaningful, accent-free words: what the two titles have to share."""
    return {
        word
        for word in _WORD_RE.findall(_fold(clean_title(text)))
        if len(word) > 1 and word not in _NOISE_WORDS
    }


def similarity(wanted: set[str], found: set[str]) -> float:
    """Share of *wanted* words present in *found* (0…1).

    Directional on purpose: a catalogue title that adds "From \"Brahmastra\""
    is still the same song, while a candidate missing half the query is not.
    """
    if not wanted or not found:
        return 0.0
    return len(wanted & found) / len(wanted)


def score(wanted: Track, candidate: Track) -> float:
    """How confident we are that *candidate* is the song in *wanted* (0…1.5)."""
    want_title = _words(wanted.title)
    cand_title = _words(candidate.title)
    if not want_title or not cand_title:
        return 0.0
    overlap = similarity(want_title, cand_title)
    if overlap < 0.5:
        return 0.0

    total = overlap
    if wanted.uploader and candidate.uploader:
        if _words(wanted.uploader) & _words(candidate.uploader):
            total += 0.2

    if wanted.duration and candidate.duration:
        difference = abs(int(wanted.duration) - int(candidate.duration))
        if difference <= 5:
            total += 0.3
        elif difference <= 12:
            total += 0.15
        elif difference > 40:
            return 0.0  # a different cut — never substitute silently

    low = _fold(candidate.title)
    wanted_low = _fold(wanted.title)
    for variant in _VARIANT_WORDS:
        if variant in low and variant not in wanted_low:
            total -= 0.5
    return max(0.0, total)


# ── sources ─────────────────────────────────────────────────────────────────
def source_order(settings=None) -> list[str]:
    """Which engines to ask, in order. `ALTERNATE_SOURCES=off` disables the tier."""
    if settings is None:
        from vyron.config import settings as settings  # type: ignore[no-redef]

    raw = (getattr(settings, "alternate_sources", "") or "").strip().lower()
    if raw in {"off", "none", "0", "false", "no"}:
        return []
    names = [chunk.strip() for chunk in raw.replace(";", ",").split(",") if chunk.strip()]
    return names or ["jiosaavn", "audius", "soundcloud"]


async def _from_source(name: str, query: str, limit: int) -> list[Track]:
    """One engine's search, never raising and never hanging."""
    try:
        if name == "jiosaavn":
            from vyron.core import jiosaavn

            return await asyncio.wait_for(jiosaavn.search(query, limit), timeout=SOURCE_TIMEOUT)
        if name == "audius":
            from vyron.core import audius

            return await asyncio.wait_for(audius.search(query, limit), timeout=SOURCE_TIMEOUT)
        if name == "soundcloud":
            from vyron.core import extract

            return await asyncio.wait_for(
                extract.search_soundcloud(query, limit), timeout=SOURCE_TIMEOUT
            )
        logger.debug("unknown alternate source %r", name)
        return []
    except asyncio.TimeoutError:
        logger.info("alternate source %s timed out for %r", name, query)
        return []
    except Exception as exc:  # pragma: no cover - network variance
        logger.info("alternate source %s failed for %r: %s", name, query, exc)
        return []


async def search_all(
    query: str,
    limit: int = 6,
    *,
    settings=None,
    order: list[str] | None = None,
) -> list[Track]:
    """Search every configured engine at once and return what is playable."""
    query = (query or "").strip()
    if not query:
        return []
    names = order if order is not None else source_order(settings)
    if not names:
        return []
    pages = await asyncio.gather(*(_from_source(name, query, limit) for name in names))
    found: list[Track] = []
    seen: set[str] = set()
    for page in pages:
        for track in page:
            if not track or not track.url:
                continue
            key = f"{track.source}:{track.id}"
            if key in seen:
                continue
            seen.add(key)
            found.append(track)
    return found[:limit]


async def find(track: Track, *, settings=None, fresh: bool = False) -> Track | None:
    """The same song on a source that will actually play, or ``None``.

    Results are cached for an hour: the web app retries a failed stream a few
    times, and each retry should not cost another catalogue round-trip.
    """
    if track is None or track.is_live:
        return None
    if track.source in DIRECT_SOURCES:
        return track
    key = f"{track.source}:{track.id}"
    cached = _CACHE.get(key)
    if cached and not fresh and cached[0] > time.time():
        return cached[1]

    order = source_order(settings)
    found: Track | None = None
    if order:
        title = clean_title(track.title) or track.title
        queries = [f"{title} {track.uploader}".strip(), title]
        for query in dict.fromkeys(q for q in queries if q):
            candidates = await search_all(query, 8, settings=settings, order=order)
            best: tuple[float, Track] | None = None
            for candidate in candidates:
                value = score(track, candidate)
                if value < ACCEPT_SCORE:
                    continue
                if best is None or value > best[0]:
                    best = (value, candidate)
            if best is not None:
                found = best[1]
                logger.info(
                    "substituting %r (%s) with %s %r (%s) · match %.2f",
                    track.title,
                    track.id,
                    found.source,
                    found.title,
                    found.id,
                    best[0],
                )
                break

    _CACHE[key] = (time.time() + CACHE_TTL, found)
    return found


def info_for(track: Track) -> StreamInfo | None:
    """A ``StreamInfo`` pointing straight at a direct-audio track."""
    from vyron.core.search import MIME_BY_EXT, StreamInfo

    url = (track.url or "").strip()
    if not url.startswith("http"):
        return None
    suffix = urlsplit(url).path.rsplit(".", 1)[-1].lower()
    ext = suffix if suffix in MIME_BY_EXT else "mp3"
    return StreamInfo(
        url=url,
        expires_at=time.time() + CACHE_TTL,
        headers={},
        ext=ext,
        mime=MIME_BY_EXT.get(ext, "audio/mpeg"),
        title=track.title,
        source=track.source,
    )


async def stream_info(track: Track, *, settings=None, fresh: bool = False) -> StreamInfo | None:
    """``StreamInfo`` for the YouTube track, served by whatever source works."""
    if track is None:
        return None
    if track.source in DIRECT_SOURCES and track.url:
        return info_for(track)
    found = await find(track, settings=settings, fresh=fresh)
    return info_for(found) if found is not None else None


def describe(settings=None) -> str:
    order = source_order(settings)
    return " → ".join(order) if order else "off"


def reset_cache() -> None:
    _CACHE.clear()


__all__ = [
    "ACCEPT_SCORE",
    "clean_title",
    "describe",
    "find",
    "info_for",
    "reset_cache",
    "score",
    "search_all",
    "similarity",
    "source_order",
    "stream_info",
]
