# ---------------------------------------------------------------------------
#  VYRON — YouTube Music as a search source
# ---------------------------------------------------------------------------
# ytmusicapi talks to the same catalogue the YouTube Music app uses. It is a
# better *search* than `ytsearch` for music: results are songs with an artist,
# an album and artwork instead of "Some Song (Official Video) [4K]" uploads,
# and a track object carries the YouTube video id we need to stream.
#
# It is optional. No key, no login (the anonymous client is enough for search),
# and if the package is missing or the call fails we simply fall through to the
# yt-dlp ladder — `available()` is the switch, everything else is best-effort.
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_client = None
_unavailable = False


def available() -> bool:
    global _unavailable
    if _unavailable:
        return False
    try:
        import ytmusicapi  # noqa: F401
    except Exception:
        _unavailable = True
        return False
    return True


def _get_client():
    global _client, _unavailable
    if _client is not None:
        return _client
    try:
        from ytmusicapi import YTMusic

        _client = YTMusic()
        return _client
    except Exception as exc:  # pragma: no cover - import/network dependent
        logger.info("ytmusicapi unavailable: %s", exc)
        _unavailable = True
        return None


def _best_thumb(thumbnails) -> str | None:
    if not thumbnails:
        return None
    try:
        return max(thumbnails, key=lambda item: (item.get("width") or 0)).get("url")
    except Exception:
        return None


def _duration_seconds(value) -> int:
    if isinstance(value, int):
        return value
    if not value:
        return 0
    try:
        parts = [int(part) for part in str(value).split(":")]
    except (TypeError, ValueError):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def parse_entry(item: dict) -> dict | None:
    """Map one ytmusicapi result to the shape the rest of VYRON uses."""
    if not isinstance(item, dict):
        return None
    video_id = item.get("videoId") or (item.get("video") or {}).get("videoId")
    if not video_id:
        return None
    artists = item.get("artists") or []
    if isinstance(artists, list):
        artist = ", ".join(
            str(entry.get("name") if isinstance(entry, dict) else entry).strip()
            for entry in artists
            if entry
        )
    else:
        artist = str(artists)
    if not artist:
        artist = str(item.get("author") or "")
    album = item.get("album")
    album_name = album.get("name") if isinstance(album, dict) else (str(album) if album else "")
    duration = item.get("duration_seconds") or _duration_seconds(item.get("duration"))
    return {
        "id": str(video_id),
        "title": str(item.get("title") or "Unknown title"),
        "uploader": artist.strip(),
        "duration": int(duration or 0),
        # an album search hit carries the album cover, a song its own artwork
        "thumbnail": _best_thumb(item.get("thumbnails")) or _best_thumb(item.get("thumbnail")),
        "album": album_name or "",
        "is_video": False,
        "source": "ytmusic",
    }


def _search_sync(query: str, limit: int, filter_: str | None) -> list[dict]:
    client = _get_client()
    if client is None:
        return []
    kwargs = {"limit": max(1, min(40, limit))}
    if filter_:
        kwargs["filter"] = filter_
    try:
        raw = client.search(query, **kwargs)
    except Exception as exc:
        logger.info("ytmusic search failed for %r: %s", query, exc)
        return []
    entries = [parse_entry(item) for item in raw or []]
    return [entry for entry in entries if entry]


async def search(query: str, limit: int = 8, *, filter_: str | None = "songs") -> list[dict]:
    """Search YouTube Music. Never raises; an empty list means "use yt-dlp"."""
    if not available() or not (query or "").strip():
        return []
    return await asyncio.to_thread(_search_sync, query, limit, filter_)


def _album_sync(browse_id: str, limit: int) -> tuple[str, list[dict]]:
    client = _get_client()
    if client is None:
        return "", []
    try:
        album = client.get_album(browse_id)
    except Exception as exc:
        logger.info("ytmusic album failed for %s: %s", browse_id, exc)
        return "", []
    entries: list[dict] = []
    for item in (album.get("tracks") or [])[:limit]:
        parsed = parse_entry(item)
        if parsed:
            entries.append(parsed)
    return str(album.get("title") or ""), entries


async def album(browse_id: str, limit: int = 50) -> tuple[str, list[dict]]:
    """An album (``MPREb_…`` browse id) as ``(title, tracks)``."""
    if not available() or not browse_id:
        return "", []
    return await asyncio.to_thread(_album_sync, browse_id, limit)


def describe() -> str:
    return "ytmusicapi ready" if available() else "ytmusicapi not installed (yt-dlp search only)"


__all__ = ["album", "available", "describe", "parse_entry", "search"]
