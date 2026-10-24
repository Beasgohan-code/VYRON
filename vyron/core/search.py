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
from vyron.core import metasources, sources, ytmusic
from vyron.core.resolvers import HEALTH
from vyron.core.queue import Track
from vyron.ui.progress import parse_duration, truncate

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"^https?://", re.I)
_YT_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([\w-]{11})")
_LIST_RE = re.compile(r"[?&]list=([\w-]+)")


class _Capture:
    """A yt-dlp logger that remembers the last thing it complained about.

    One instance per extraction: this runs inside a worker thread and several
    resolves overlap, so the state must not be shared.
    """

    def __init__(self) -> None:
        self.last_error = ""
        self.verbose = False

    def _remember(self, message: Any, *args: Any) -> None:
        try:
            text = str(message) % args if args else str(message)
        except Exception:  # pragma: no cover - odd format strings
            text = f"{message} {args}"
        if text.startswith("[debug]"):
            return
        self.last_error = text.strip()[:400]

    def debug(self, message: Any, *args: Any) -> None:
        if self.verbose:
            logger.debug("yt-dlp: %s", message)

    def info(self, message: Any, *args: Any) -> None:
        if self.verbose:
            logger.debug("yt-dlp: %s", message)

    def warning(self, message: Any, *args: Any) -> None:
        self._remember(message, *args)

    def error(self, message: Any, *args: Any) -> None:
        self._remember(message, *args)


# The reasons worth explaining, most specific first: what YouTube (or the host)
# said → what it means → what actually fixes it. Anything unmatched keeps the
# original sentence, because a wrong explanation is worse than a raw one.
_WHY: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("confirm you're not a bot", "confirm you’re not a bot", "not a bot", "sign in to confirm"),
        "YouTube thinks this server is a bot",
        "install curl_cffi (browser impersonation, on by default), set COOKIES_FILE, "
        "or self-host Cobalt (COBALT_URLS)",
    ),
    (
        ("age-restricted", "age restricted", "confirm your age", "inappropriate for some users"),
        "this video is age-restricted",
        "set COOKIES_FILE with a signed-in browser's cookies — no mirror can bypass this one",
    ),
    (
        ("private video", "this video is private"),
        "the video is private",
        "ask the owner to make it public — no resolver can see it",
    ),
    (
        ("members-only", "join this channel", "members only"),
        "the video is members-only",
        "it needs a channel membership — play something else",
    ),
    (
        ("not available in your country", "geo", "blocked it in your country", "region"),
        "the video is geo-blocked for this server",
        "set PROXY to a server in an allowed country, or pick another upload",
    ),
    (
        ("video unavailable", "this video is unavailable", "has been removed", "no longer available"),
        "the video is gone",
        "pick another result — the uploader deleted or privated it",
    ),
    (
        ("requested format is not available",),
        "the format we asked for does not exist for this video",
        "that is a selector problem, not your IP — /sources shows which clients still offer audio",
    ),
    (
        ("http error 429", "too many requests", "rate limit"),
        "YouTube is rate-limiting this server",
        "wait a minute, or self-host Cobalt (COBALT_URLS) so public mirrors are not in the path",
    ),
    (
        ("http error 403", "403: forbidden"),
        "YouTube refused the request (403)",
        "browser impersonation is the usual fix; a self-hosted Cobalt is the reliable one",
    ),
    (
        ("unable to download api page", "tls/ssl", "connection reset", "timed out", "getaddrinfo"),
        "this server cannot reach YouTube",
        "check egress/DNS or set PROXY — nothing else in the bot can help until it can",
    ),
    (
        ("premieres in", "will begin", "live event"),
        "this is a premiere or a live event",
        "it cannot be streamed until it starts",
    ),
)


def explain(reason: str) -> tuple[str, str]:
    """(what it means, what to do) for a raw yt-dlp / mirror message."""
    text = (reason or "").lower()
    for needles, meaning, fix in _WHY:
        if any(needle in text for needle in needles):
            return meaning, fix
    return "", ""


def _explain(reason: str, *, target: str = "") -> str:
    """A failure sentence a person can act on, built from yt-dlp's own words."""
    raw = (reason or "").strip()
    if raw.startswith("ERROR:"):
        raw = raw[len("ERROR:"):].strip()
    if raw.startswith("[youtube]"):
        raw = raw[len("[youtube]"):].strip()
    meaning, fix = explain(raw)
    if not raw:
        return (
            "YouTube returned no information for this link. That is usually this "
            "server's IP being refused — see /sources."
        )
    if meaning:
        return f"{meaning}: {raw[:160]} → {fix}"
    # Unrecognised wording still gets somewhere to go: /sources names the tier
    # that refused and the reason, which is what a screenshot cannot do.
    return f"{raw[:200]} → run /sources to see which resolver is refusing, and why"


_SLOT: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None


def _extract_slot(limit: int = 2) -> asyncio.Semaphore:
    """A process-wide semaphore bound to the loop that is running now."""
    global _SLOT
    loop = asyncio.get_running_loop()
    if _SLOT is None or _SLOT[0] is not loop or _SLOT[1]._value > max(1, limit):
        _SLOT = (loop, asyncio.Semaphore(max(1, limit)))
    return _SLOT[1]


def _client_source(client: str | None) -> str:
    """Scoreboard key for a yt-dlp player client."""
    return f"yt-dlp:{client or 'default'}"


class MediaError(RuntimeError):
    """Raised when a search / extraction fails in a user-presentable way."""


# Shown when YouTube refuses this server rather than this video. It is the one
# failure an operator can fix in a minute, so it says what to do.
FAILURE_HINT = (
    "YouTube is refusing this server's IP — set COOKIES_FILE (a cookies.txt from a "
    "logged-in browser) or keep STREAM_FALLBACK=on, then try again"
)


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
        # One resolve per track at a time: the app asks for a stream and starts
        # playback at the same moment, and doing the whole client ladder twice
        # is how a 12-second failure became a 45-second one.
        self._inflight: dict[str, asyncio.Task[StreamInfo]] = {}
        # A track that just failed will fail again for a while. Remember it, so
        # the next tap answers instantly instead of grinding the ladder again.
        self._failures: dict[str, float] = {}
        # …and what to say about it: the classified reason beats a generic hint
        self._failure_reasons: dict[str, str] = {}
        # the player client that last produced a playable URL (None = yt-dlp default)
        self._client_hint: str | None = None
        self._warned_impersonate = False

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
        # The single most effective no-cookie fix for a datacenter IP: make the
        # HTTP client *look* like Chrome (TLS/JA3 fingerprint, header order and
        # HTTP/2 settings). yt-dlp does this through curl_cffi, which is why it
        # is in requirements.txt; without the module the option is skipped
        # instead of failing the download.
        target = self._impersonate_target()
        if target:
            opts.setdefault("impersonate", target)
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
        """One yt-dlp extraction, with the *reason* kept when it fails.

        `ignoreerrors` is on (a playlist with one dead video must still yield
        the rest), which means a failure returns ``None`` instead of raising —
        and the reason only exists as a log line. Handing yt-dlp our own logger
        recovers it, so the user is told "Sign in to confirm you're not a bot"
        instead of "nothing could be extracted".
        """
        capture = _Capture()
        options = {"logger": capture}
        options.update(self._opts(**extra))
        capture.verbose = bool(options.get("verbose"))
        with yt_dlp.YoutubeDL(options) as ydl:
            try:
                info = ydl.extract_info(target, download=False)
            except Exception as exc:  # a real raise (network, parse) is better than None
                raise MediaError(_explain(f"{type(exc).__name__}: {exc}", target=target)) from exc
        if not info:
            raise MediaError(_explain(capture.last_error, target=target))
        return info

    async def _async_extract(self, target: str, **extra: Any) -> dict[str, Any]:
        # yt-dlp is CPU-bound Python: on a small host, ten "parallel" searches
        # starve the event loop and every web request in the same second looks
        # slow. Two extractions at a time keeps the bot responsive.
        try:
            async with _extract_slot(getattr(self.settings, "extract_concurrency", 2)):
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
            # Auto-detect the media kind. Almost every YouTube item has a video
            # stream *and* an audio stream, so "has video" is not the question:
            # what matters is whether there is anything to listen to. A source
            # is treated as video only when it has no audio at all (a silent
            # clip, a video-only format, a raw .mp4 link) or the extractor says
            # so outright. Flat search rows carry neither field and stay audio.
            is_video=bool(
                entry.get("is_video", False)
                or (
                    str(entry.get("vcodec") or "none") not in {"none", "None"}
                    and str(entry.get("acodec") or "none") in {"none", "None"}
                )
            ),
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

        # Tier 0: YouTube Music, when the optional package is installed and the
        # operator has not turned it off. It returns songs (artist + album)
        # rather than "Official Video [4K]" uploads, so the top hit is usually
        # simply correct — and its video id streams through the same ladder.
        tracks: list[Track] = []
        meta = await self._ytmusic_search(query, fetch)
        for entry in meta:
            track = self._track_from_entry(entry, requester=requester)
            if track:
                tracks.append(track)
        if len(tracks) < count:
            info = await self._async_extract(f"ytsearch{fetch}:{query}", extract_flat="in_playlist")
            entries = info.get("entries") or []
            for entry in entries:
                track = self._track_from_entry(entry, requester=requester)
                if track:
                    tracks.append(track)
        if not tracks:
            # YouTube said no. Ask the other streaming sources in the
            # registry's order (Audius → JioSaavn → SoundCloud → Bandcamp)
            # before giving up: those hand out real audio, so the request can
            # still succeed.
            for track in await sources.fallback_search(query, count, settings=self.settings):
                track.requested_by, track.requested_name = requester
                tracks.append(track)
        if not tracks:
            raise MediaError("No results found for that query.")
        return self.rank(query, tracks)[:count]

    def _catalogue_enabled(self) -> bool:
        """`MUSIC_SOURCES=off` keeps everything on YouTube-only behaviour."""
        raw = (getattr(self.settings, "music_sources", "") or "").strip().lower()
        return raw not in {"off", "none", "0", "false", "no"}

    async def _ytmusic_search(self, query: str, limit: int) -> list[dict]:
        """YouTube Music results, or ``[]`` when disabled/unavailable."""
        if not getattr(self.settings, "ytmusic_search", True):
            return []
        if not ytmusic.available():
            return []
        return await ytmusic.search(query, limit=limit)

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
        if query.lower().startswith(("http://", "https://")):
            from vyron.core.urlguard import BlockedURL, check_user_url

            try:
                query = await check_user_url(query, settings=self.settings)
            except BlockedURL as exc:
                raise MediaError(f"That link cannot be used: {exc}.") from exc

        # Direct-stream sources first (Audius, JioSaavn, SoundCloud, Bandcamp):
        # they hand out the audio themselves, so these links play without YouTube
        # being involved. The registry decides which of them are on.
        if looks_like_url(query):
            direct = await sources.resolve_direct(query, settings=self.settings)
            if direct is not None:
                direct.requested_by, direct.requested_name = requester
                return direct

        # A Spotify / Deezer / Apple Music link is metadata, not audio: read the
        # catalogue entry, then let the normal ladder find the song. The
        # catalogue's artwork is usually the best-looking cover, so it wins over
        # the YouTube thumbnail when we have it. (SoundCloud and Bandcamp are
        # handled above: yt-dlp extracts *those* uploads directly.)
        if self._catalogue_enabled() and metasources.is_catalogue_link(query):
            found = await self._from_catalogue(query, requester=requester)
            if found is not None:
                return found

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

    async def _from_catalogue(
        self, url: str, *, requester: tuple[int, str] = (0, "")
    ) -> Track | None:
        """Spotify/Deezer/Apple link → the best YouTube match (or a stream)."""
        meta = await metasources.lookup(url)
        if isinstance(meta, metasources.MetaCollection):
            meta = meta.tracks[0] if meta.tracks else None
        if not isinstance(meta, metasources.MetaTrack) or not meta.title:
            return None
        try:
            results = await self.search(meta.query, limit=2, requester=requester)
        except MediaError:
            results = []
        if not results:
            # A catalogue entry we could not match on YouTube: try to stream the
            # same song from a direct source instead of failing the link.
            for track in await sources.fallback_search(
                meta.query, 1, settings=self.settings
            ):
                track.requested_by, track.requested_name = requester
                return track
            return None
        chosen = results[0]
        # Keep the catalogue's identity where it is better than YouTube's.
        if meta.artwork:
            chosen.thumbnail = meta.artwork
        if meta.artist and not chosen.uploader:
            chosen.uploader = meta.artist
        chosen.source = f"{meta.service}·youtube"
        return chosen

    async def resolve_collection(
        self,
        url: str,
        *,
        limit: int = 25,
        requester: tuple[int, str] = (0, ""),
    ) -> tuple[str, list[Track]] | None:
        """A catalogue album/playlist link → ``(title, tracks)``.

        Every entry is matched against YouTube with a bounded number of
        concurrent searches; entries that cannot be matched are skipped rather
        than failing the whole album.
        """
        if not self._catalogue_enabled():
            return None
        meta = await metasources.lookup(url)
        if not isinstance(meta, metasources.MetaCollection) or not meta.tracks:
            return None
        wanted = meta.tracks[:limit]
        semaphore = asyncio.Semaphore(3)

        async def _one(item: metasources.MetaTrack) -> Track | None:
            async with semaphore:
                try:
                    results = await self.search(item.query, limit=1, requester=requester)
                except MediaError:
                    return None
            if not results:
                return None
            track = results[0]
            if item.artwork:
                track.thumbnail = item.artwork
            track.source = f"{meta.service}·youtube"
            return track

        found = await asyncio.gather(*(_one(item) for item in wanted))
        tracks = [track for track in found if track]
        if not tracks:
            return None
        return (meta.title or meta.service.title()), tracks

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

        if not refresh:
            blocked_until = self._failures.get(key, 0.0)
            if blocked_until > time.time():
                raise MediaError(self._failure_reasons.get(key) or FAILURE_HINT)
            running = self._inflight.get(key)
            if running is not None:
                # Share the answer instead of running the ladder again.
                return await asyncio.shield(running)

        task = asyncio.ensure_future(self._resolve_stream(track, video=video, refresh=refresh))
        if not refresh:
            self._inflight[key] = task
        try:
            return await asyncio.shield(task)
        except MediaError as exc:
            ttl = max(5, int(getattr(self.settings, "stream_failure_ttl", 60)))
            self._failures[key] = time.time() + ttl
            self._failure_reasons[key] = str(exc)
            raise
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _resolve_stream(
        self, track: Track, *, video: bool = False, refresh: bool = False
    ) -> StreamInfo:
        """The actual work: cached URL → client ladder → public mirror."""
        key = f"{track.id}:{'v' if video else 'a'}"
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
        same_error = 0
        for client in self._client_ladder():
            source = _client_source(client)
            started = time.perf_counter()
            try:
                info = await self._async_extract(target, format=selector, **self._client_opts(client))
                result = self._stream_from_info(info, track, video=video, target=target)
            except Exception as exc:  # MediaError, DownloadError, KeyError…
                message = str(exc)
                HEALTH.record(source, False, error=message)
                # Two identical answers mean the client ladder is not the
                # problem (a dead video, a blocked IP). Stopping there turns a
                # six-client, 24-second stall into a two-client, 4-second one.
                same_error = same_error + 1 if last_error is not None and str(last_error) == message else 1
                last_error = exc
                logger.info("resolve via %s failed for %s: %s", client, track.id, exc)
                if same_error >= 2:
                    logger.info("resolve for %s is deterministic, stopping the ladder", track.id)
                    break
                continue
            HEALTH.record(source, True, ms=(time.perf_counter() - started) * 1000)
            self._remember_client(client)
            self._stream_cache[key] = result
            self._failures.pop(key, None)
            self._failure_reasons.pop(key, None)
            return result

        # Last tier: a public Invidious/Piped mirror. yt-dlp failing is a
        # YouTube-side problem (PO token, 403, "confirm you're not a bot"), not
        # usually a track-side one, so somebody else's resolver often still has
        # a signed URL for the same video.
        fallback = await self._public_fallback(track, video=video)
        if fallback:
            self._stream_cache[key] = fallback
            return fallback

        self._stream_cache.pop(key, None)
        raw = str(last_error) if last_error else ""
        # `_explain` maps yt-dlp's own sentence onto what it means and what
        # fixes it, so the toast in the app is actionable instead of cryptic.
        raise MediaError(_explain(raw, target=track.id))

    async def _public_fallback(self, track: Track, *, video: bool = False) -> StreamInfo | None:
        """Direct URL from Invidious/Piped, or ``None`` when not configured."""
        if not getattr(self.settings, "stream_fallback", True):
            return None
        try:
            from vyron.core.public_streams import get_public_streams

            height = 0
            if video:
                height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
                    self.settings.video_quality, 720
                )
            direct = await get_public_streams(self.settings).resolve(track.id, height=height)
        except Exception as exc:  # pragma: no cover - never break a resolve
            logger.info("public stream fallback failed for %s: %s", track.id, exc)
            return None
        if not direct:
            return None
        logger.info("stream for %s came from %s", track.id, direct.source)
        from vyron.core.resolvers import HEALTH

        HEALTH.record(direct.source, True, ms=0)
        return StreamInfo(
            url=direct.url,
            expires_at=time.time() + self.settings.stream_cache_ttl,
            headers=dict(direct.headers),
            ext=direct.ext,
            mime=direct.mime or ("video/mp4" if video else "audio/mp4"),
            title=track.title,
        )

    # ── stream plumbing ────────────────────────────────────────────────────
    def _impersonate_target(self):
        """A ready ``ImpersonateTarget``, or ``""`` when unavailable.

        yt-dlp wants the *object*, not the string (the CLI parses it for you).
        Requires curl_cffi — without it the option is skipped, never fatal.
        """
        requested = (getattr(self.settings, "impersonate", "") or "").strip()
        if requested.lower() in {"", "off", "none", "0", "false"}:
            return ""
        try:
            import curl_cffi  # noqa: F401  (yt-dlp needs the module, not the API)
            from yt_dlp.networking.impersonate import ImpersonateTarget
        except Exception:
            if not self._warned_impersonate:
                self._warned_impersonate = True
                logger.info(
                    "browser impersonation is off: `pip install curl_cffi` enables it "
                    "(it is the best no-cookie fix for a datacenter IP)"
                )
            return ""
        try:
            return ImpersonateTarget.from_str(requested or "chrome")
        except Exception as exc:  # an unknown target must not break playback
            logger.info("ignoring IMPERSONATE=%s (%s)", requested, exc)
            return ""

    @staticmethod
    def _client_opts(client: str | None) -> dict[str, Any]:
        if not client:
            return {}
        return {"extractor_args": {"youtube": {"player_client": [client]}}}

    def _client_ladder(self) -> list[str | None]:
        """Player clients to try, best-known-first for this deployment.

        Order is experience, not documentation: `tv_simply` and `web_embedded`
        are the clients that still hand out a signed URL to an IP YouTube does
        not like, `android_vr`/`ios` cover the ones that need a mobile header
        set, and plain `web` is last because it is the first to demand a PO
        token. Clients in a cooldown (they failed twice in a row) are skipped
        instead of costing every track another timeout.
        """
        hint = self._client_hint
        ladder: list[str | None] = [
            None,
            "tv_simply",
            "web_embedded",
            "android_vr",
            "ios",
            "tv",
            "web_safari",
            "mweb",
        ]
        if hint:
            ladder = [hint] + [client for client in ladder if client != hint]
        return [client for client in ladder if HEALTH.available(_client_source(client))]

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
