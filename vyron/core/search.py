# ---------------------------------------------------------------------------
#  VYRON — YouTube / media search & stream resolution
#
#  All yt-dlp work happens in a worker thread (``asyncio.to_thread``) so the
#  event loop — and therefore playback — never blocks.  Direct stream URLs are
#  cached with a TTL because YouTube links expire.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import time
from dataclasses import dataclass
from typing import Any

import yt_dlp

from vyron.config import Settings
from vyron.core.queue import Track
from vyron.ui.progress import parse_duration, truncate

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://", re.I)
_YT_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([\w-]{11})")
_LIST_RE = re.compile(r"[?&]list=([\w-]+)")


class MediaError(RuntimeError):
    """Raised when a search / extraction fails in a user-presentable way."""


@dataclass
class StreamInfo:
    url: str
    is_live: bool = False
    expires_at: float = 0.0


def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def youtube_id(text: str) -> str | None:
    match = _YT_ID_RE.search(text or "")
    return match.group(1) if match else None


class YouTube:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._stream_cache: dict[str, StreamInfo] = {}

    # ── yt-dlp plumbing ────────────────────────────────────────────────────
    def _opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "geo_bypass": True,
            "nocheckcertificate": True,
            "ignoreerrors": True,
            "extractor_retries": 2,
            "socket_timeout": 15,
            "retries": 2,
        }
        if self.settings.cookies_file:
            opts["cookiefile"] = self.settings.cookies_file
        if self.settings.proxy:
            opts["proxy"] = self.settings.proxy
        if self.settings.ytdlp_args:
            try:
                extra_args = shlex.split(self.settings.ytdlp_args)
            except ValueError:
                extra_args = []
            # e.g. YTDLP_ARGS="--extractor-args youtube:player_client=android"
            for index, token in enumerate(extra_args):
                if token.startswith("--") and index + 1 < len(extra_args):
                    opts[token.lstrip("-").replace("-", "_")] = extra_args[index + 1]
        opts.update(extra)
        return opts

    def _extract(self, target: str, **extra: Any) -> dict[str, Any]:
        with yt_dlp.YoutubeDL(self._opts(**extra)) as ydl:
            info = ydl.extract_info(target, download=False)
        if not info:
            raise MediaError("Nothing could be extracted from that link.")
        return info

    async def _async_extract(self, target: str, **extra: Any) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(self._extract, target, **extra)
        except MediaError:
            raise
        except Exception as exc:  # yt-dlp raises a zoo of exception types
            logger.info("extract failed for %s: %s", target, exc)
            raise MediaError(str(exc)) from exc

    # ── mapping ────────────────────────────────────────────────────────────
    def _track_from_entry(self, entry: dict[str, Any], *, requester: tuple[int, str] = (0, "")) -> Track | None:
        if not entry:
            return None
        vid = str(entry.get("id") or "")
        if not vid:
            return None
        thumb = entry.get("thumbnail")
        if not thumb:
            thumbs = entry.get("thumbnails") or []
            if thumbs:
                thumb = thumbs[-1].get("url")
        if not thumb and _YT_ID_RE.match(f"v={vid}"):
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        return Track(
            id=vid,
            title=str(entry.get("title") or "Unknown title"),
            duration=parse_duration(entry.get("duration")),
            url=entry.get("webpage_url") or entry.get("url") or f"https://youtu.be/{vid}",
            uploader=str(entry.get("uploader") or entry.get("channel") or ""),
            thumbnail=thumb,
            is_video=bool(entry.get("is_video", False)),
            source=str(entry.get("extractor_key") or entry.get("ie_key") or "youtube").lower(),
            requested_by=requester[0],
            requested_name=requester[1],
            filesize=int(entry.get("filesize") or entry.get("filesize_approx") or 0),
        )

    # ── public API ─────────────────────────────────────────────────────────
    async def search(
        self,
        query: str,
        limit: int | None = None,
        requester: tuple[int, str] = (0, ""),
    ) -> list[Track]:
        """Search YouTube and return up to *limit* playable tracks."""
        query = (query or "").strip()
        if not query:
            return []
        count = limit or self.settings.search_results
        info = await self._async_extract(f"ytsearch{count}:{query}", extract_flat="in_playlist")
        entries = info.get("entries") or []
        tracks: list[Track] = []
        for entry in entries:
            track = self._track_from_entry(entry, requester=requester)
            if track:
                tracks.append(track)
        if not tracks:
            raise MediaError("No results found for that query.")
        return tracks

    async def resolve(self, query: str, requester: tuple[int, str] = (0, "")) -> Track:
        """Turn a URL *or* a free-text query into a single playable track."""
        query = (query or "").strip()
        if not query:
            raise MediaError("Give me a song name, a link or reply to an audio file.")

        if looks_like_url(query):
            info = await self._async_extract(query)
            if info.get("_type") == "playlist" and info.get("entries"):
                entries = [e for e in info["entries"] if e]
                if not entries:
                    raise MediaError("That playlist is empty or private.")
                info = entries[0]
            track = self._track_from_entry(info, requester=requester)
            if not track:
                raise MediaError("That link did not resolve to a playable track.")
            return track

        results = await self.search(query, limit=1, requester=requester)
        return results[0]

    async def playlist(self, url: str, limit: int = 50) -> tuple[str, list[Track]]:
        """Load a YouTube playlist / mix.  Returns (title, tracks)."""
        info = await self._async_extract(url, extract_flat=True, noplaylist=False)
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise MediaError("That playlist is empty or private.")
        tracks = [t for t in (self._track_from_entry(e) for e in entries[:limit]) if t]
        if not tracks:
            raise MediaError("No playable items in that playlist.")
        return str(info.get("title") or "Playlist"), tracks

    async def related(self, track: Track, limit: int = 8) -> list[Track]:
        """Autoplay source: an official YouTube mix seeded by the track id."""
        if track.source.startswith("youtube") and track.id and len(track.id) == 11:
            mix_url = f"https://www.youtube.com/watch?v={track.id}&list=RD{track.id}"
            try:
                _, tracks = await self.playlist(mix_url, limit=limit + 1)
                filtered = [t for t in tracks if t.id != track.id]
                if filtered:
                    return filtered[:limit]
            except MediaError:
                pass
        query = f"{track.title} {track.uploader}".strip()
        try:
            results = await self.search(query, limit=limit + 1)
        except MediaError:
            return []
        return [t for t in results if t.id != track.id][:limit]

    async def stream_url(self, track: Track, *, video: bool = False) -> str:
        """Resolve a direct media URL suitable for ntgcalls/ffmpeg."""
        key = f"{track.id}:{'v' if video else 'a'}"
        cached = self._stream_cache.get(key)
        if cached and cached.expires_at > time.time():
            return cached.url

        target = track.url or track.watch_url
        if not target:
            raise MediaError("Track has no URL to stream.")

        if video:
            height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
                self.settings.video_quality, 720
            )
            selector = (
                f"best[height<={height}][ext=mp4]/best[height<={height}]/bestvideo[height<={height}]+bestaudio/best"
            )
        else:
            selector = "bestaudio[ext=m4a]/bestaudio[acodec!=none]/best"

        info = await self._async_extract(target, format=selector)
        if not info:
            raise MediaError("Could not resolve a stream for that track.")

        url = info.get("url")
        if not url:
            candidates = [f for f in (info.get("formats") or []) if f.get("url")]
            if video:
                candidates.sort(key=lambda f: (f.get("height") or 0), reverse=True)
                progressive = [f for f in candidates if f.get("vcodec") not in (None, "none")]
                candidates = progressive or candidates
            else:
                candidates.sort(key=lambda f: (f.get("abr") or f.get("tbr") or 0), reverse=True)
                audio_only = [f for f in candidates if f.get("acodec") not in (None, "none")]
                candidates = audio_only or candidates
            if not candidates:
                raise MediaError("No downloadable formats available.")
            url = candidates[0]["url"]

        ttl = self.settings.stream_cache_ttl
        self._stream_cache[key] = StreamInfo(
            url=url,
            is_live=bool(info.get("is_live")),
            expires_at=time.time() + ttl,
        )
        return url

    def invalidate(self, track: Track) -> None:
        self._stream_cache.pop(f"{track.id}:a", None)
        self._stream_cache.pop(f"{track.id}:v", None)

    # ── helpers used by cards ──────────────────────────────────────────────
    async def suggestions(self, seed: str, limit: int = 5) -> list[str]:
        try:
            tracks = await self.search(seed, limit=limit)
        except MediaError:
            return []
        return [truncate(t.title, 34) for t in tracks]

    def dump(self, data: dict) -> str:  # pragma: no cover - debugging helper
        return json.dumps(data, indent=2, default=str)[:2000]


__all__ = ["MediaError", "StreamInfo", "YouTube", "looks_like_url", "youtube_id"]
