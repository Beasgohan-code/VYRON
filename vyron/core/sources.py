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
    _tries: int = field(default=0, repr=False)
    _wins: int = field(default=0, repr=False)
    _total_ms: float = field(default=0.0, repr=False)
    _last_ms: float = field(default=0.0, repr=False)
    _last_error: str = field(default="", repr=False)

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

    def record(self, ok: bool, ms: float | None = None, error: str = "") -> None:
        self._ok = ok
        self._checked = time.monotonic()
        self._fails = 0 if ok else self._fails + 1
        self._tries += 1
        if ok:
            self._wins += 1
        if ms is not None:
            self._last_ms = float(ms)
            self._total_ms += float(ms)
        self._last_error = "" if ok else (error or "failed")[:160]
        _mark_dirty()

    def status(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "enabled": self.is_enabled(),
            "available": self.available(),
            "last_ok": self._ok,
            "failures": self._fails,
            "tries": self._tries,
            "success_rate": round(self._wins / self._tries, 3) if self._tries else None,
            "avg_ms": round(self._total_ms / self._tries, 1) if self._tries else None,
            "last_ms": round(self._last_ms, 1) if self._last_ms else None,
            "last_error": self._last_error,
            "detail": self.detail,
        }

    # ── persistence ────────────────────────────────────────────────────────
    def health(self) -> dict:
        return {
            "tries": self._tries,
            "wins": self._wins,
            "fails": self._fails,
            "total_ms": self._total_ms,
            "last_ms": self._last_ms,
            "last_ok": self._ok,
            "last_error": self._last_error,
            "checked": self._checked,
        }

    def restore(self, data: dict) -> None:
        """Take back counters saved by a previous process."""
        if not isinstance(data, dict):
            return
        self._tries = int(data.get("tries") or 0)
        self._wins = int(data.get("wins") or 0)
        self._fails = int(data.get("fails") or 0)
        self._total_ms = float(data.get("total_ms") or 0.0)
        self._last_ms = float(data.get("last_ms") or 0.0)
        self._last_ok = data.get("last_ok")
        self._last_error = str(data.get("last_error") or "")
        self._checked = float(data.get("checked") or 0.0)


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
    if _extras_on(settings):
        items.append(
            Source(
                "odesli",
                "song.link",
                "catalogue",
                enabled=lambda: _extras_on(settings),
                detail="cross-platform matcher · exact YouTube id, no guessing",
            )
        )
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


# ── health persistence ──────────────────────────────────────────────────────
# A restart used to erase everything VYRON had learned about a source. The
# counters live in the same store as the rest of the bot's state, so /doctor
# and /v1/sources can answer "has Audius actually been working this week?"
_PERSIST = {"dirty": False, "last_save": 0.0, "task": None}
_META_KEY = "source_health"
_SAVE_EVERY = 45.0


def _mark_dirty() -> None:
    _PERSIST["dirty"] = True
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # no loop: a sync caller, nothing to schedule
        return
    if time.monotonic() - _PERSIST["last_save"] < _SAVE_EVERY:
        return
    task = _PERSIST["task"]
    if task is None or task.done():
        _PERSIST["task"] = loop.create_task(save())


async def save(storage=None, *, force: bool = False) -> bool:
    """Write the health snapshot; debounced unless *force* is set."""
    if not force and not _PERSIST["dirty"]:
        return False
    if not force and time.monotonic() - _PERSIST["last_save"] < _SAVE_EVERY:
        return False
    if storage is None:
        try:
            from vyron.runtime import runtime

            storage = runtime.storage
        except Exception:  # pragma: no cover
            storage = None
    if storage is None:
        return False
    snapshot = {item.name: item.health() for item in registry()}
    try:
        await storage.set_meta(_META_KEY, snapshot)
    except Exception as exc:  # pragma: no cover - storage oddities
        logger.debug("could not persist source health: %s", exc)
        return False
    _PERSIST["dirty"] = False
    _PERSIST["last_save"] = time.monotonic()
    return True


async def load(storage=None) -> int:
    """Restore counters saved by a previous process. Returns rows restored."""
    if storage is None:
        try:
            from vyron.runtime import runtime

            storage = runtime.storage
        except Exception:  # pragma: no cover
            storage = None
    if storage is None:
        return 0
    try:
        snapshot = await storage.get_meta(_META_KEY, {}) or {}
    except Exception:  # pragma: no cover
        return 0
    restored = 0
    for item in registry():
        if isinstance(snapshot, dict) and item.name in snapshot:
            item.restore(snapshot[item.name])
            restored += 1
    if restored:
        logger.info("restored health for %d source(s)", restored)
    return restored


async def probe(settings=None, *, timeout: float = 8.0, query: str = "kesariya") -> list[dict]:
    """Ask every stream source for one track and time the answer.

    Flags say "not in cooldown"; this says "responded in 840 ms with 1 result".
    """
    import asyncio

    rows: list[dict] = []
    for source in stream_sources(settings):
        if not source.search:
            rows.append({**source.status(), "probe": {"ok": False, "error": "no search"}})
            continue
        started = time.perf_counter()
        try:
            found = await asyncio.wait_for(source.search(query, 1), timeout=timeout)
            ms = (time.perf_counter() - started) * 1000
            source.record(bool(found), ms=ms)
            rows.append(
                {
                    **source.status(),
                    "probe": {"ok": bool(found), "ms": round(ms, 1), "results": len(found or [])},
                }
            )
        except Exception as exc:
            ms = (time.perf_counter() - started) * 1000
            source.record(False, ms=ms, error=str(exc))
            rows.append(
                {
                    **source.status(),
                    "probe": {"ok": False, "ms": round(ms, 1), "error": str(exc)[:160]},
                }
            )
    await save(force=True)
    return rows


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
            source.record(False, error=str(exc))
            logger.info("%s search failed: %s", source.name, exc)
            continue
        took = (time.perf_counter() - started) * 1000
        source.record(bool(found), ms=took)
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
        started = time.perf_counter()
        try:
            track = await source.resolve(url)
        except Exception as exc:  # pragma: no cover - defensive
            source.record(False, error=str(exc))
            logger.info("%s link resolve failed: %s", source.name, exc)
            continue
        source.record(track is not None, ms=(time.perf_counter() - started) * 1000)
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
    "load",
    "probe",
    "save",
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
