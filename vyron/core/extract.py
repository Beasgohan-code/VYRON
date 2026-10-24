# ---------------------------------------------------------------------------
#  VYRON — platforms yt-dlp can read directly (SoundCloud, Bandcamp)
# ---------------------------------------------------------------------------
# A SoundCloud or Bandcamp link used to be *metadata only*: the title was read
# and then guessed at on YouTube, which is why a rare remix played the wrong
# song. Both platforms serve their audio to yt-dlp without a key or a login, so
# they belong in the same tier as Audius and JioSaavn — a link becomes *that*
# upload, and a search on them is a genuine fallback when YouTube is throttling
# the deployment's IP.
#
# Everything here is yt-dlp work, which is blocking, so each call is pushed into
# a thread. Failures raise; the registry decides what that means.
from __future__ import annotations

import asyncio
import logging
from typing import Any

import yt_dlp

from vyron.core.queue import Track

logger = logging.getLogger(__name__)

# Sources whose `Track.url` is a *page* that yt-dlp extracts (never a raw file).
EXTRACT_SOURCES = frozenset({"soundcloud", "bandcamp"})

HOSTS: dict[str, tuple[str, ...]] = {
    "soundcloud": ("soundcloud.com", "snd.sc", "on.soundcloud.com"),
    "bandcamp": ("bandcamp.com",),
}


def _host(url: str) -> str:
    text = (url or "").strip().lower()
    for scheme in ("https://", "http://"):
        if text.startswith(scheme):
            text = text[len(scheme) :]
    return text.split("/", 1)[0].split("?", 1)[0]


def is_soundcloud(url: str) -> bool:
    host = _host(url)
    return any(host == name or host.endswith("." + name) for name in HOSTS["soundcloud"])


def is_bandcamp(url: str) -> bool:
    host = _host(url)
    return any(host == name or host.endswith("." + name) for name in HOSTS["bandcamp"])


def service_of(url: str) -> str:
    """`"soundcloud"`, `"bandcamp"` or `""`."""
    if is_soundcloud(url):
        return "soundcloud"
    if is_bandcamp(url):
        return "bandcamp"
    return ""


def _opts(**extra: Any) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "nocheckcertificate": True,
        "socket_timeout": 15,
        "extract_flat": False,
        "skip_download": True,
        "cachedir": False,
    }
    opts.update(extra)
    return opts


def _pick_thumbnail(info: dict[str, Any]) -> str:
    thumbs = [item for item in (info.get("thumbnails") or []) if item.get("url")]
    if thumbs:
        return max(thumbs, key=lambda item: (item.get("width") or 0) * (item.get("height") or 0))["url"]
    return str(info.get("thumbnail") or "")


def _track_from_entry(entry: dict[str, Any], source: str) -> Track | None:
    url = str(entry.get("webpage_url") or entry.get("url") or "")
    ident = str(entry.get("id") or "")
    title = str(entry.get("title") or "").strip()
    if not (url and title):
        return None
    return Track(
        id=ident or url.rsplit("/", 1)[-1],
        title=title,
        duration=int(entry.get("duration") or 0),
        uploader=str(entry.get("uploader") or entry.get("channel") or source.title()),
        thumbnail=_pick_thumbnail(entry),
        url=url,
        source=source,
    )


def _search_blocking(query: str, limit: int, source: str) -> list[Track]:
    prefix = "scsearch" if source == "soundcloud" else "bcsearch"
    with yt_dlp.YoutubeDL(_opts(extract_flat="in_playlist")) as ydl:
        info = ydl.extract_info(f"{prefix}{max(1, limit)}:{query}", download=False)
    tracks: list[Track] = []
    for entry in (info or {}).get("entries") or []:
        if not entry:
            continue
        track = _track_from_entry(entry, source)
        if track:
            tracks.append(track)
    return tracks


def _info_blocking(url: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(_opts()) as ydl:
        return ydl.extract_info(url, download=False) or {}


async def search(query: str, limit: int = 5, *, source: str = "soundcloud") -> list[Track]:
    """Search SoundCloud (yt-dlp `scsearch`) — no API key, no account."""
    query = (query or "").strip()
    if not query:
        return []
    try:
        return await asyncio.to_thread(_search_blocking, query, limit, source)
    except Exception as exc:
        logger.info("%s search failed: %s", source, exc)
        raise


async def resolve(url: str) -> Track | None:
    """Turn a SoundCloud/Bandcamp page URL into a playable track."""
    source = service_of(url)
    if not source:
        return None
    info = await asyncio.to_thread(_info_blocking, url)
    track = _track_from_entry({**info, "webpage_url": info.get("webpage_url") or url}, source)
    if track is None:
        return None
    track.url = str(info.get("webpage_url") or url)
    return track


async def stream_url(track: Track) -> str:
    """The best audio-only URL for a page source (used when play_from_disk=off)."""
    info = await asyncio.to_thread(_info_blocking, track.url)
    formats = [item for item in info.get("formats") or [] if item.get("url")]
    audio = [item for item in formats if item.get("acodec") not in (None, "none") and item.get("vcodec") in (None, "none")]
    pool = audio or formats
    if not pool:
        raise RuntimeError("no playable format was offered")

    def score(item: dict[str, Any]) -> tuple[int, float]:
        return (int(item.get("abr") or item.get("tbr") or 0), float(item.get("filesize") or 0))

    best = max(pool, key=score)
    return str(best["url"])


async def search_soundcloud(query: str, limit: int = 5) -> list[Track]:
    return await search(query, limit, source="soundcloud")


async def resolve_soundcloud(url: str) -> Track | None:
    return await resolve(url) if is_soundcloud(url) else None


async def resolve_bandcamp(url: str) -> Track | None:
    return await resolve(url) if is_bandcamp(url) else None


def describe() -> str:
    return "yt-dlp · no key · streams the original upload"


__all__ = [
    "EXTRACT_SOURCES",
    "describe",
    "is_bandcamp",
    "is_soundcloud",
    "resolve",
    "resolve_bandcamp",
    "resolve_soundcloud",
    "search",
    "search_soundcloud",
    "service_of",
    "stream_url",
]
