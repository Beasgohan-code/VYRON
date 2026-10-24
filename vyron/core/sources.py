# ---------------------------------------------------------------------------
#  VYRON — the source registry
# ---------------------------------------------------------------------------
# Every place a song can come from, in one list, with one order. Three kinds:
#
#   search     can find a song by text        (yt-dlp, YouTube Music)
#   catalogue  can read a foreign link        (Spotify, Deezer, Apple)
#   stream     can hand out real audio        (Audius, JioSaavn, SoundCloud, Bandcamp)
#
# YouTube (through the yt-dlp client ladder) is primary. The rest are fallbacks
# in a deliberate order: when the primary returns nothing, the next *stream*
# source is asked before the user ever sees "no results". Ordering lives here so
# /doctor, /v1/sources and the resolver cannot drift apart.
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from vyron.core.queue import Track

logger = logging.getLogger(__name__)

# Sources whose `Track.url` *is* the audio: no extraction, no YouTube.
DIRECT_SOURCES = frozenset({"audius", "jiosaavn"})
# Sources whose `Track.url` is a page yt-dlp extracts itself. Different from a
# direct stream (there is an extraction step) and from a catalogue (the audio
# really comes from that platform, not from a YouTube guess).
EXTRACT_SOURCES = frozenset({"soundcloud", "bandcamp"})
# Sources that only describe a song; audio always comes from a stream source.
CATALOGUE_SOURCES = frozenset({"spotify", "deezer", "apple"})


@dataclass
class Source:
    name: str
    label: str
    kind: str                       # search | catalogue | stream
    enabled: Callable[[], bool] | None = None
    search: Callable[[str, int], Awaitable[list[Track]]] | None = None
    resolve: Callable[[str], Awaitable[Track | None]] | None = None
    detail: str = ""
    _ok: bool | None = field(default=None, repr=False)
    _checked: float = field(default=0.0, repr=False)
    _fails: int = field(default=0, repr=False)

    def is_enabled(self) -> bool:
        try:
            return bool(self.enabled()) if self.enabled else True
        except Exception:  # pragma: no cover - defensive
            return True

    def available(self) -> bool:
        """Enabled *and* not in a cooldown after repeated failures."""
        if not self.is_enabled():
            return False
        if self._fails >= 2 and time.monotonic() - self._checked < 60:
            return False
        return True

    def record(self, ok: bool) -> None:
        self._ok = ok
        self._checked = time.monotonic()
        self._fails = 0 if ok else self._fails + 1

    def status(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "enabled": self.is_enabled(),
            "available": self.available(),
            "last_ok": self._ok,
            "failures": self._fails,
            "detail": self.detail,
        }


_OFF = {"off", "none", "0", "false", "no", ""}


def _enabled_list(settings) -> list[str]:
    raw = (getattr(settings, "music_sources", "") or "").strip().lower()
    return [chunk.strip() for chunk in raw.replace(";", ",").split(",") if chunk.strip()]


def _extras_on(settings) -> bool:
    """The master switch: `MUSIC_SOURCES=off` really does mean YouTube only."""
    return bool((getattr(settings, "music_sources", "") or "").strip().lower() not in _OFF)


def _catalogue_on(name: str, settings) -> bool:
    """A catalogue answers only if it is named in `MUSIC_SOURCES`."""
    return _extras_on(settings) and name in _enabled_list(settings)


def registry(settings=None) -> list[Source]:
    """The sources this deployment can use, primary first."""
    from vyron.config import settings as default_settings

    settings = settings or default_settings
    items: list[Source] = []

    def _extra_enabled() -> bool:
        return _extras_on(settings)

    # ── search ────────────────────────────────────────────────────────────
    try:
        from vyron.core import ytmusic

        items.append(
            Source(
                "ytmusic",
                "YouTube Music",
                "search",
                enabled=lambda: bool(getattr(settings, "ytmusic_search", True)) and ytmusic.available(),
                search=ytmusic.search,
                detail=ytmusic.describe(),
            )
        )
    except Exception:  # pragma: no cover
        pass

    items.append(
        Source(
            "ytdlp",
            "YouTube (yt-dlp)",
            "search",
            detail="client ladder: default → tv_simply → web_embedded → android_vr → ios → tv",
        )
    )

    try:
        from vyron.core import audius

        items.append(
            Source(
                "audius",
                "Audius",
                "stream",
                enabled=_extra_enabled,
                search=audius.search,
                resolve=audius.resolve,
                detail=audius.describe(),
            )
        )
    except Exception:  # pragma: no cover
        pass

    try:
        from vyron.core import jiosaavn

        items.append(
            Source(
                "jiosaavn",
                "JioSaavn",
                "stream",
                enabled=_extra_enabled,
                search=jiosaavn.search,
                resolve=jiosaavn.resolve,
                detail=jiosaavn.describe(),
            )
        )
    except Exception:  # pragma: no cover
        pass

    try:
        from vyron.core import extract

        items.append(
            Source(
                "soundcloud",
                "SoundCloud",
                "stream",
                enabled=_extra_enabled,
                search=extract.search_soundcloud,
                resolve=extract.resolve_soundcloud,
                detail=extract.describe(),
            )
        )
        items.append(
            Source(
                "bandcamp",
                "Bandcamp",
                "stream",
                enabled=_extra_enabled,
                resolve=extract.resolve_bandcamp,
                detail="yt-dlp · the artist's own page · no key",
            )
        )
    except Exception:  # pragma: no cover
        pass

    # ── catalogue readers ─────────────────────────────────────────────────
    for name, label, detail in (
        ("spotify", "Spotify", "oEmbed + public embed page"),
        ("deezer", "Deezer", "open API (track/album/playlist)"),
        ("apple", "Apple Music", "iTunes lookup API"),
    ):
        items.append(
            Source(
                name,
                label,
                "catalogue",
                enabled=lambda name=name: _catalogue_on(name, settings),
                detail=detail,
            )
        )
    return items


def search_sources(settings=None) -> list[Source]:
    return [item for item in registry(settings) if item.kind in {"search", "stream"} and item.search]


def stream_sources(settings=None) -> list[Source]:
    return [item for item in registry(settings) if item.kind == "stream"]


async def fallback_search(query: str, limit: int, *, settings=None) -> list[Track]:
    """Ask every extra source in order until one answers.

    YouTube has already failed (or returned fewer than asked); this is the
    "never show an empty screen" tier. Failures are remembered per source so a
    dead API costs one timeout, not one per command.
    """
    results: list[Track] = []
    for source in search_sources(settings):
        if source.kind != "stream":      # ytmusic/ytdlp are handled by the caller
            continue
        if not source.available():
            continue
        started = time.perf_counter()
        try:
            found = await source.search(query, limit)
        except Exception as exc:
            source.record(False)
            logger.info("%s search failed: %s", source.name, exc)
            continue
        took = (time.perf_counter() - started) * 1000
        source.record(bool(found))
        if found:
            logger.info(
                "%s answered %r with %d track(s) in %.0f ms",
                source.name,
                query,
                len(found),
                took,
            )
            results.extend(found)
            if len(results) >= limit:
                break
    return results[:limit]


async def resolve_direct(url: str, *, settings=None) -> Track | None:
    """Try every stream source for a link (Audius, JioSaavn, SoundCloud, Bandcamp)."""
    for source in stream_sources(settings):
        if not source.resolve or not source.available():
            continue
        try:
            track = await source.resolve(url)
        except Exception as exc:  # pragma: no cover - defensive
            source.record(False)
            logger.info("%s link resolve failed: %s", source.name, exc)
            continue
        source.record(track is not None)
        if track is not None:
            return track
    return None


def status(settings=None) -> list[dict]:
    """Rows for /doctor and `/v1/sources`."""
    return [item.status() for item in registry(settings)]


def names(settings=None) -> list[str]:
    return [item.name for item in registry(settings)]


def describe(settings=None) -> str:
    """`ytmusic · ytdlp → audius → jiosaavn` — the fallback order, one line."""
    stream = [item.name for item in stream_sources(settings) if item.available()]
    return "ytmusic · ytdlp" + (" → " + " → ".join(stream) if stream else "")


__all__ = [
    "CATALOGUE_SOURCES",
    "DIRECT_SOURCES",
    "EXTRACT_SOURCES",
    "Source",
    "describe",
    "fallback_search",
    "names",
    "registry",
    "resolve_direct",
    "search_sources",
    "status",
    "stream_sources",
]
