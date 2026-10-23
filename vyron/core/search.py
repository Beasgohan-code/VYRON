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
from pathlib import Path
import re
import shlex
import time
from dataclasses import dataclass, field
from urllib.parse import unquote
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


MIME_BY_EXT = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
    "wav": "audio/wav",
}


@dataclass
class StreamInfo:
    """Everything a proxy needs: the URL, the headers it was minted for, mime."""

    url: str
    is_live: bool = False
    expires_at: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    ext: str = ""
    mime: str = "audio/mp4"
    title: str = ""


def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def youtube_id(text: str) -> str | None:
    match = _YT_ID_RE.search(text or "")
    return match.group(1) if match else None


def _materialise_cookies(settings: Any) -> str:
    """Turn `YOUTUBE_COOKIES` (env text) into the cookie file yt-dlp wants.

    A datacenter IP is the usual reason YouTube answers "confirm you're not a
    bot"; the fix is an account's cookies. Uploading a file is awkward on
    Render, so pasting the Netscape-format text into an env var is supported and
    written to disk here (0600, outside the repo).
    """
    text = (getattr(settings, "cookies_text", "") or "").strip()
    path = getattr(settings, "cookies_file", "") or ""
    if not text:
        return path
    if path and Path(path).is_file():
        return path
    target = Path(path) if path else Path(getattr(settings, "data_dir", ".")) / "cookies.txt"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        literal = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
        target.write_text(literal if literal.endswith("\n") else literal + "\n", encoding="utf-8")
        target.chmod(0o600)
        settings.cookies_file = str(target)
        logger.info("wrote YOUTUBE_COOKIES to %s", target)
        return str(target)
    except Exception as exc:  # pragma: no cover - a bad cookie never blocks boot
        logger.warning("could not write the YouTube cookies: %s", exc)
        return path


class YouTube:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        _materialise_cookies(settings)
        self._stream_cache: dict[str, StreamInfo] = {}
        # the player client that last produced a playable URL (None = yt-dlp default)
        self._client_hint: str | None = None

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
            opts.update(self._parse_ytdlp_args(self.settings.ytdlp_args))
        # `extra` always wins, but extractor_args are merged key-by-key so a
        # client passed by the ladder does not silently drop the operator's
        # own extractor tuning (and vice versa).
        for key, value in extra.items():
            if key == "extractor_args" and isinstance(opts.get(key), dict):
                merged = {name: dict(args) for name, args in opts[key].items()}
                for name, args in value.items():
                    bucket = merged.setdefault(name, {})
                    for flag, setting in args.items():
                        if flag == "player_client":
                            # the ladder's client goes first, then whatever the
                            # operator configured, de-duplicated
                            first = setting if isinstance(setting, list) else [setting]
                            rest = bucket.get(flag) or []
                            rest = rest if isinstance(rest, list) else [rest]
                            bucket[flag] = list(dict.fromkeys([*first, *rest]))
                        else:
                            bucket[flag] = setting
                opts[key] = merged
            else:
                opts[key] = value
        return opts

    @staticmethod
    def _parse_ytdlp_args(raw: str) -> dict[str, Any]:
        """Turn ``YTDLP_ARGS`` into yt-dlp Python options.

        `--extractor-args youtube:player_client=android` is the important one
        for streaming, and it has to become a nested dict — the CLI string form
        is not understood by ``YoutubeDL`` when passed through `params`.
        """
        try:
            tokens = shlex.split(raw)
        except ValueError:
            return {}
        parsed: dict[str, Any] = {}
        index = 0
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if not token.startswith("--"):
                continue
            name, inline = token[2:], None
            if "=" in name:
                name, inline = name.split("=", 1)
            value = inline
            if value is None and index < len(tokens) and not tokens[index].startswith("--"):
                value = tokens[index]
                index += 1
            key = name.strip().replace("-", "_")
            if key == "extractor_args" and value:
                for chunk in value.split(";"):
                    if ":" not in chunk:
                        continue
                    extractor, args = chunk.split(":", 1)
                    bucket = parsed.setdefault("extractor_args", {}).setdefault(
                        extractor.strip(), {}
                    )
                    for pair in args.split(";"):
                        if "=" not in pair:
                            continue
                        flag, setting = pair.split("=", 1)
                        bucket.setdefault(flag.strip(), []).extend(
                            part for part in setting.split(",") if part
                        )
            elif value is not None:
                parsed[key] = value
        return parsed

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
            is_live=bool(entry.get("is_live")) or entry.get("live_status") == "is_live",
            source=str(entry.get("extractor_key") or entry.get("ie_key") or "youtube").lower(),
            requested_by=requester[0],
            requested_name=requester[1],
            filesize=int(entry.get("filesize") or entry.get("filesize_approx") or 0),
            views=int(entry.get("view_count") or 0),
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
        # Over-fetch so dedupe/filtering still leaves a full page of results.
        fetch = count if count <= 2 else min(40, count * 2)
        info = await self._async_extract(f"ytsearch{fetch}:{query}", extract_flat="in_playlist")
        entries = info.get("entries") or []
        tracks: list[Track] = []
        for entry in entries:
            track = self._track_from_entry(entry, requester=requester)
            if track:
                tracks.append(track)
        if not tracks:
            raise MediaError("No results found for that query.")
        return self.rank(query, tracks)[:count]

    # ── ranking ────────────────────────────────────────────────────────────
    @staticmethod
    def _words(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 1}

    def rank(self, query: str, tracks: list[Track]) -> list[Track]:
        """Order results the way a person would: relevance, then playability, then reach.

        YouTube's own order is good enough for the top hit and noisy afterwards —
        duplicate uploads, 20-second Shorts and hour-long "1 hour loop" edits all
        creep in. This keeps the top hit honest and pushes the junk down.
        """
        wanted = self._words(query)
        seen_ids: set[str] = set()
        seen_titles: set[str] = set()
        scored: list[tuple[float, int, Track]] = []

        for position, track in enumerate(tracks):
            key = f"{track.source}:{track.id}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            normalised = " ".join(sorted(self._words(track.title)))
            if normalised and normalised in seen_titles:
                continue
            seen_titles.add(normalised)

            score = 0.0
            if wanted:
                overlap = len(wanted & self._words(track.title)) / len(wanted)
                score += overlap * 4.0
                if track.uploader and wanted & self._words(track.uploader):
                    score += 0.8

            # Playable-length preference: skip 20s Shorts, demote 2h "loops".
            if 40 <= track.duration <= 3600:
                score += 0.9
            elif track.duration and track.duration < 40:
                score -= 1.6
            elif track.duration > 5400:
                score -= 0.7
            if not track.duration:
                score -= 0.3

            title_low = track.title.lower()
            for noise in ("slowed + reverb", "1 hour", "10 hours", "nightcore", "8d audio"):
                if noise in title_low and noise not in query.lower():
                    score -= 0.6
            if track.views:
                score += min(1.4, (track.views / 2_000_000) ** 0.5)

            # Tiny nudge so a clean tie keeps YouTube's ordering.
            score -= position * 0.01
            scored.append((score, position, track))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [track for _, _, track in scored]

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
        return (await self.stream_info(track, video=video)).url

    async def stream_info(
        self, track: Track, *, video: bool = False, refresh: bool = False
    ) -> StreamInfo:
        """Resolve a direct media URL *and* the headers it must be fetched with.

        YouTube answers different clients differently: `web` is the most
        accurate but the first to demand a PO token, `android_vr`/`ios`/`tv`
        often still hand out a playable URL when `web` returns 403. So the
        resolve walks a client ladder and remembers which one worked — the
        difference between "the web player plays" and "the web player spins".
        """
        key = f"{track.id}:{'v' if video else 'a'}"
        cached = self._stream_cache.get(key)
        if cached and not refresh and cached.expires_at > time.time():
            return cached

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

        last_error: Exception | None = None
        for client in self._client_ladder():
            try:
                info = await self._async_extract(target, format=selector, **self._client_opts(client))
                result = self._stream_from_info(info, track, video=video, target=target)
            except Exception as exc:  # MediaError, DownloadError, KeyError…
                last_error = exc
                logger.info("resolve via %s failed for %s: %s", client, track.id, exc)
                continue
            self._remember_client(client)
            self._stream_cache[key] = result
            return result

        self._stream_cache.pop(key, None)
        raise MediaError(
            f"no playable stream for this track ({type(last_error).__name__}: {last_error})"
            if last_error
            else "no playable stream for this track"
        )

    # ── stream plumbing ────────────────────────────────────────────────────
    @staticmethod
    def _client_opts(client: str | None) -> dict[str, Any]:
        if not client:
            return {}
        return {"extractor_args": {"youtube": {"player_client": [client]}}}

    def _client_ladder(self) -> list[str | None]:
        """Player clients to try, best-known-first for this deployment."""
        hint = self._client_hint
        ladder: list[str | None] = [None, "android_vr", "ios", "tv", "web_safari", "mweb"]
        if hint:
            ladder = [hint] + [client for client in ladder if client != hint]
        return ladder

    def _remember_client(self, client: str | None) -> None:
        if client:
            self._client_hint = client

    def _stream_from_info(
        self, info: dict[str, Any] | None, track: Track, *, video: bool, target: str
    ) -> StreamInfo:
        if not info:
            raise MediaError("Could not resolve a stream for that track.")

        chosen: dict[str, Any] | None = info if info.get("url") else None
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
            chosen = candidates[0]
            url = chosen["url"]

        ext = str((chosen or info).get("ext") or "").lower()
        # googlevideo URLs carry their own mime; trust it over a guessed default
        # so HEAD probes and <audio> get a Content-Type the browser accepts.
        mime = MIME_BY_EXT.get(ext, "")
        if not mime:
            found = re.search(r"[?&]mime=([^&]+)", url or "")
            if found:
                candidate = unquote(found.group(1)).lower()
                if candidate.startswith(("audio/", "video/")):
                    mime = candidate

        headers = {
            str(name): str(value)
            for name, value in ((chosen or info).get("http_headers") or {}).items()
            if str(name).lower() not in {"host", "content-length", "accept-encoding"}
        }
        return StreamInfo(
            url=url,
            is_live=bool(info.get("is_live")),
            expires_at=time.time() + self.settings.stream_cache_ttl,
            headers=headers,
            ext=ext,
            mime=mime or ("video/mp4" if video else "audio/mp4"),
            title=str(info.get("title") or track.title),
        )

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
