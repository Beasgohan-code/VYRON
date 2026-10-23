# ---------------------------------------------------------------------------
#  VYRON — direct-URL fallbacks when yt-dlp's YouTube clients all fail
# ---------------------------------------------------------------------------
# yt-dlp is the best extractor there is, but YouTube's anti-bot wall changes
# weekly and every deployment eventually meets a video it cannot resolve. The
# two community projects that solved *that* problem — **Invidious** and
# **Piped** — expose a plain, signed media URL over JSON with no API key, so a
# public instance is a genuinely useful last tier: if yt-dlp cannot resolve a
# track, we ask them before telling the user the song is unplayable.
#
#   Invidious  GET https://<host>/api/v1/videos/<id>
#                → adaptiveFormats[] {url, type, bitrate} · formatStreams[] {url, resolution}
#   Piped      GET https://<host>/streams/<id>
#                → audioStreams[] {url, bitrate, mimeType} · videoStreams[] {url, quality}
#
# Everything here is best-effort: short timeouts, no retries across a host
# twice, and a failure is a quiet ``None`` rather than an exception the caller
# has to catch.
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)

# Public instances that speak the documented JSON APIs. Order matters: the
# first healthy answer wins, so community mirrors with generous limits go
# first. Operators can override the whole list with STREAM_FALLBACK_HOSTS.
INVIDIOUS_HOSTS: tuple[str, ...] = (
    "inv.nadeko.net",
    "invidious.nerdvpn.de",
    "yewtu.be",
    "invidious.f5.si",
)
PIPED_HOSTS: tuple[str, ...] = (
    "pipedapi.kavin.rocks",
    "pipedapi.adminforge.de",
    "api.piped.private.coffee",
)

_UA = {"User-Agent": "Mozilla/5.0 (compatible; VYRON/1.0)"}
_HTTPS = re.compile(r"^https?://", re.I)


@dataclass
class DirectStream:
    """A media URL somebody else signed, plus what it is."""

    url: str
    source: str = ""
    kind: str = "audio"  # "audio" | "video"
    ext: str = "m4a"
    mime: str = "audio/mp4"
    bitrate: int = 0
    height: int = 0
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.kind == "video":
            return f"{self.height}p" if self.height else "video"
        return f"{round(self.bitrate / 1000)}k" if self.bitrate else "audio"


def _ext_from(url: str, mime: str, *, video: bool) -> str:
    if "webm" in mime:
        return "webm"
    if video:
        return "mp4"
    if "mp4" in mime or "m4a" in mime:
        return "m4a"
    match = re.search(r"mime=([a-z0-9]+)%2F|\.(m4a|mp4|webm|opus|mp3)(?:\?|$)", url, re.I)
    if match:
        token = match.group(1) or match.group(2) or ""
        return token.lower().lstrip("x-")
    return "mp4" if video else "m4a"


def parse_invidious(payload: dict, host: str) -> DirectStream | None:
    """Best audio stream from an Invidious ``/api/v1/videos`` document."""
    formats = [f for f in payload.get("adaptiveFormats") or [] if f.get("url")]
    audio = [f for f in formats if str(f.get("type", "")).startswith("audio/")]
    if not audio:
        return None
    best = max(audio, key=lambda f: int(f.get("bitrate") or 0))
    mime = str(best.get("type") or "audio/mp4").split(";")[0].strip() or "audio/mp4"
    return DirectStream(
        url=best["url"],
        source=f"invidious:{host}",
        kind="audio",
        ext=_ext_from(best["url"], mime, video=False),
        mime=mime,
        bitrate=int(best.get("bitrate") or 0),
        headers=dict(_UA),
    )


def parse_invidious_video(payload: dict, host: str, height: int) -> DirectStream | None:
    """Progressive (audio+video) stream at or below *height* — MP4 preferred."""
    progressive = [f for f in payload.get("formatStreams") or [] if f.get("url")]
    if not progressive:
        return None

    def video_height(item: dict) -> int:
        raw = str(item.get("resolution") or item.get("qualityLabel") or "")
        digits = re.sub(r"\D", "", raw)
        return int(digits) if digits else 0

    fits = [f for f in progressive if video_height(f) <= height] or progressive
    fits.sort(key=video_height, reverse=True)
    best = fits[0]
    return DirectStream(
        url=best["url"],
        source=f"invidious:{host}",
        kind="video",
        ext=_ext_from(best["url"], str(best.get("type") or ""), video=True),
        mime=str(best.get("type") or "video/mp4").split(";")[0].strip(),
        height=video_height(best),
        headers=dict(_UA),
    )


def parse_piped(payload: dict, host: str) -> DirectStream | None:
    streams = [s for s in payload.get("audioStreams") or [] if s.get("url")]
    if not streams:
        return None
    best = max(streams, key=lambda s: int(s.get("bitrate") or 0))
    mime = str(best.get("mimeType") or "audio/mp4")
    return DirectStream(
        url=best["url"],
        source=f"piped:{host}",
        kind="audio",
        ext=_ext_from(best["url"], mime, video=False),
        mime=mime,
        bitrate=int(best.get("bitrate") or 0),
        headers=dict(_UA),
    )


def parse_piped_video(payload: dict, host: str, height: int) -> DirectStream | None:
    streams = [
        s
        for s in payload.get("videoStreams") or []
        if s.get("url") and not s.get("videoOnly")
    ]
    if not streams:
        return None

    def stream_height(item: dict) -> int:
        digits = re.sub(r"\D", "", str(item.get("quality") or ""))
        return int(digits) if digits else 0

    fits = [s for s in streams if stream_height(s) <= height] or streams
    fits.sort(key=stream_height, reverse=True)
    best = fits[0]
    return DirectStream(
        url=best["url"],
        source=f"piped:{host}",
        kind="video",
        ext=_ext_from(best["url"], str(best.get("mimeType") or ""), video=True),
        mime=str(best.get("mimeType") or "video/mp4").split(";")[0].strip(),
        height=stream_height(best),
        headers=dict(_UA),
    )


class PublicStreams:
    """Ask Invidious, then Piped, for a URL yt-dlp could not produce."""

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.invidious: tuple[str, ...] = INVIDIOUS_HOSTS
        self.piped: tuple[str, ...] = PIPED_HOSTS
        self.timeout = 9.0
        raw = getattr(settings, "stream_fallback_hosts", "") or ""
        if raw.strip():
            self.invidious = tuple(h.strip() for h in raw.split(",") if h.strip())
            self.piped = self.invidious
        timeout = getattr(settings, "stream_fallback_timeout", 0) or 0
        if timeout:
            self.timeout = float(timeout)

    # ── transport ──────────────────────────────────────────────────────────
    async def _json(self, url: str) -> dict | None:
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout, headers=_UA) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.debug("fallback %s → HTTP %s", url, response.status)
                        return None
                    payload = await response.json(content_type=None)
                    return payload if isinstance(payload, dict) else None
        except Exception as exc:
            logger.debug("fallback %s failed: %s", url, exc)
            return None

    @staticmethod
    def _is_instance(payload: dict, kind: str) -> bool:
        if kind == "invidious":
            return bool(payload.get("adaptiveFormats") or payload.get("formatStreams"))
        return bool(payload.get("audioStreams") or payload.get("videoStreams"))

    # ── public API ─────────────────────────────────────────────────────────
    async def resolve(self, video_id: str, *, height: int = 0) -> DirectStream | None:
        """Audio (``height=0``) or a progressive video stream, or ``None``."""
        target = (video_id or "").strip()
        if not re.fullmatch(r"[\w-]{6,24}", target):
            # A pasted URL is fine too — pull the id out of it.
            from vyron.core.search import youtube_id

            target = youtube_id(target) or ""
            if not target:
                return None

        video = height > 0
        requests: list[asyncio.Task] = []

        async def ask(kind: str, host: str, url: str):
            payload = await self._json(url)
            return kind, host, payload

        for host in self.invidious:
            requests.append(
                asyncio.create_task(ask("invidious", host, f"https://{host}/api/v1/videos/{target}"))
            )
        for host in self.piped:
            requests.append(
                asyncio.create_task(ask("piped", host, f"https://{host}/streams/{target}"))
            )

        try:
            # ``as_completed`` hands back the first host that answers: a mirror
            # with a cold cache is ~10 s slower than its neighbour and the user
            # is waiting on playback, so the fastest healthy answer wins.
            for finished in asyncio.as_completed(requests):
                kind, host, payload = await finished
                if not payload or not self._is_instance(payload, kind):
                    continue
                if kind == "invidious":
                    stream = (
                        parse_invidious_video(payload, host, height)
                        if video
                        else parse_invidious(payload, host)
                    )
                else:
                    stream = (
                        parse_piped_video(payload, host, height)
                        if video
                        else parse_piped(payload, host)
                    )
                if stream:
                    logger.info("resolved %s via %s (%s)", target, stream.source, stream.label)
                    return stream
        finally:
            for task in requests:
                if not task.done():
                    task.cancel()
        return None

    async def audio(self, video_id: str) -> DirectStream | None:
        return await self.resolve(video_id, height=0)

    async def video(self, video_id: str, height: int = 720) -> DirectStream | None:
        return await self.resolve(video_id, height=height)


_shared: PublicStreams | None = None


def get_public_streams(settings=None) -> PublicStreams:
    global _shared
    if _shared is None:
        _shared = PublicStreams(settings)
    return _shared


def reset_public_streams() -> None:
    """Tests swap settings; the singleton has to forget the old ones."""
    global _shared
    _shared = None


__all__ = [
    "DirectStream",
    "INVIDIOUS_HOSTS",
    "PIPED_HOSTS",
    "PublicStreams",
    "get_public_streams",
    "parse_invidious",
    "parse_invidious_video",
    "parse_piped",
    "parse_piped_video",
    "reset_public_streams",
]
