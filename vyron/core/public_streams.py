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
#   Cobalt     POST https://<host>/  {"url": …, "downloadMode": "audio"}
#                → {status: "tunnel"|"redirect", url}   (github.com/imputnet/cobalt)
#
# Cobalt is the newest of the three and the only one that is *meant* to be
# self-hosted: one docker run gives you a private resolver that does not share
# a public instance's rate limit. Set COBALT_URL to point at it.
#
# Everything here is best-effort: short timeouts, no retries across a host
# twice, and a failure is a quiet ``None`` rather than an exception the caller
# has to catch. Every answer is scored in ``core.resolvers.HEALTH``, so a dead
# mirror is skipped instead of costing every listener a timeout, and /sources
# can show which tier actually works from this server.
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import aiohttp

from vyron.core.resolvers import HEALTH

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
# Cobalt only accepts a POST and answers with a redirect/tunnel URL. Public
# instances come and go — COBALT_URL (a self-hosted one) is the reliable path,
# the list below is a best effort.
COBALT_HOSTS: tuple[str, ...] = (
    "cobalt-api.kwiatekmiki.com",
    "cobalt-api.ayo.tf",
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


@dataclass
class VideoMeta:
    """Just enough about a video to build a Track: title, artist, length, art."""

    title: str
    uploader: str = ""
    duration: int = 0
    thumbnail: str | None = None


def parse_meta(kind: str, payload: dict) -> VideoMeta | None:
    """Title/artist/length from an Invidious or Piped video document."""
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title") or "").strip()
    if not title:
        return None
    uploader = str(
        payload.get("author")
        or payload.get("uploader")
        or payload.get("authorId")
        or ""
    ).strip()
    length = payload.get("lengthSeconds")
    if length is None:
        length = payload.get("duration")
    try:
        duration = int(length or 0)
    except (TypeError, ValueError):
        duration = 0
    thumbnail = None
    thumbs = payload.get("videoThumbnails") or []
    if isinstance(thumbs, list) and thumbs:
        best = max(
            (item for item in thumbs if isinstance(item, dict) and item.get("url")),
            key=lambda item: int(item.get("width") or 0),
            default=None,
        )
        if best:
            thumbnail = best["url"]
    if not thumbnail:
        candidate = payload.get("thumbnail")
        if isinstance(candidate, str) and candidate.startswith("http"):
            thumbnail = candidate
        elif isinstance(candidate, dict) and candidate.get("url"):
            thumbnail = str(candidate["url"])
    return VideoMeta(title=title, uploader=uploader, duration=duration, thumbnail=thumbnail)


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


def parse_cobalt(payload: dict, host: str, *, height: int = 0) -> DirectStream | None:
    """A Cobalt v10 answer (``tunnel`` or ``redirect``) → a DirectStream.

    Cobalt returns either the file itself (``tunnel``) or a link to it
    (``redirect``); both are a plain ``url``. A ``picker`` answer means the
    instance wants an explicit format — it carries the candidates in
    ``picker[].url``.
    """
    status = str(payload.get("status") or "").lower()
    if status == "error":
        return None
    url = str(payload.get("url") or "").strip()
    if not url and isinstance(payload.get("picker"), list):
        urls = [str(item.get("url") or "") for item in payload["picker"] if item.get("url")]
        url = urls[0] if urls else ""
    if not url.startswith("http"):
        return None
    kind = "video" if height > 0 else "audio"
    mime = "video/mp4" if kind == "video" else "audio/mp3"
    filename = str(payload.get("filename") or "")
    return DirectStream(
        url=url,
        source=f"cobalt:{host}",
        kind=kind,
        ext=_ext_from(filename or url, mime, video=kind == "video"),
        mime=mime,
        height=height,
        headers=dict(_UA),
    )


class PublicStreams:
    """Ask Invidious, Piped and Cobalt for a URL yt-dlp could not produce."""

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self.invidious: tuple[str, ...] = INVIDIOUS_HOSTS
        self.piped: tuple[str, ...] = PIPED_HOSTS
        self.cobalt: tuple[str, ...] = COBALT_HOSTS
        self.timeout = 9.0

        def _hosts(raw: str) -> tuple[str, ...]:
            return tuple(
                h.strip().replace("https://", "").replace("http://", "").strip("/")
                for h in raw.split(",")
                if h.strip()
            )

        raw = getattr(settings, "stream_fallback_hosts", "") or ""
        if raw.strip():
            self.invidious = _hosts(raw)
            self.piped = self.invidious
        cobalt = (getattr(settings, "cobalt_urls", "") or "").strip()
        if cobalt.lower() in {"off", "none", "0", "false"} or getattr(
            settings, "disable_cobalt", False
        ):
            self.cobalt = ()
        elif cobalt:
            self.cobalt = _hosts(cobalt)
        timeout = getattr(settings, "stream_fallback_timeout", 0) or 0
        if timeout:
            self.timeout = float(timeout)

    # ── transport ──────────────────────────────────────────────────────────
    async def _fetch(self, url: str, *, body: dict | None = None) -> dict | None:
        timeout = aiohttp.ClientTimeout(total=self.timeout)
        headers = dict(_UA)
        if body is not None:
            headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            if body is None:
                call = session.get(url)
            else:
                call = session.post(url, json=body)
            async with call as response:
                if response.status != 200:
                    logger.debug("fallback %s → HTTP %s", url, response.status)
                    return None
                payload = await response.json(content_type=None)
                return payload if isinstance(payload, dict) else None

    async def _json(self, url: str) -> dict | None:
        try:
            return await self._fetch(url)
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

        attempts = self._plan(target, height=height)
        if not attempts:
            return None
        requests: list[asyncio.Task] = [
            asyncio.create_task(self._ask(kind, host, payload)) for kind, host, payload in attempts
        ]

        try:
            # ``as_completed`` hands back the first host that answers: a mirror
            # with a cold cache is ~10 s slower than its neighbour and the user
            # is waiting on playback, so the fastest healthy answer wins.
            for finished in asyncio.as_completed(requests):
                try:
                    kind, host, payload = await finished
                except Exception as exc:  # a host that timed out is not fatal
                    logger.debug("fallback task failed: %s", exc)
                    continue
                stream = self._parse(kind, host, payload, height=height) if payload else None
                if stream:
                    logger.info("resolved %s via %s (%s)", target, stream.source, stream.label)
                    return stream
        finally:
            for task in requests:
                if not task.done():
                    task.cancel()
        return None

    # ── plan / parse / score ───────────────────────────────────────────────
    def _plan(self, target: str, *, height: int) -> list[tuple[str, str, object]]:
        """The requests to make, skipping hosts that are cooling down."""
        attempts: list[tuple[str, str, object]] = []
        for host in self.invidious:
            if HEALTH.available(f"invidious:{host}"):
                attempts.append(("invidious", host, f"https://{host}/api/v1/videos/{target}"))
        for host in self.piped:
            if HEALTH.available(f"piped:{host}"):
                attempts.append(("piped", host, f"https://{host}/streams/{target}"))
        for host in self.cobalt:
            if HEALTH.available(f"cobalt:{host}"):
                body = {
                    "url": f"https://www.youtube.com/watch?v={target}",
                    "downloadMode": "audio" if height == 0 else "auto",
                    "audioFormat": "mp3",
                    "filenameStyle": "basic",
                }
                if height:
                    body["videoQuality"] = str(height)
                attempts.append(("cobalt", host, ("https://%s/" % host, body)))
        return attempts

    async def _ask(self, kind: str, host: str, payload) -> tuple[str, str, dict | None]:
        started = time.perf_counter()
        try:
            if isinstance(payload, tuple):
                url, body = payload
                answer = await self._fetch(url, body=body)
            else:
                answer = await self._json(payload)
        except Exception as exc:
            HEALTH.record(f"{kind}:{host}", False, error=str(exc))
            return kind, host, None
        elapsed = (time.perf_counter() - started) * 1000
        ok = bool(answer) and self._is_instance(answer, kind)
        HEALTH.record(
            f"{kind}:{host}",
            ok,
            ms=elapsed,
            error="" if ok else "no usable streams in the answer",
        )
        if not ok:
            logger.debug("fallback %s answered without streams (%s)", host, kind)
        return kind, host, answer

    @staticmethod
    def _parse(kind: str, host: str, payload: dict, *, height: int) -> DirectStream | None:
        if kind == "invidious":
            return (
                parse_invidious_video(payload, host, height)
                if height
                else parse_invidious(payload, host)
            )
        if kind == "piped":
            return (
                parse_piped_video(payload, host, height) if height else parse_piped(payload, host)
            )
        return parse_cobalt(payload, host, height=height)

    async def probe(self, video_id: str, *, height: int = 0) -> list[dict]:
        """Ask *every* source at once and report each one — /sources.

        This is the command that answers "is it my bot or is it this host?":
        same inputs, same second, one row per tier with latency and reason.
        """
        target = (video_id or "").strip()
        if not re.fullmatch(r"[\w-]{6,24}", target):
            from vyron.core.search import youtube_id

            target = youtube_id(target) or target
        results: list[dict] = []

        async def one(kind: str, host: str, payload) -> dict:
            started = time.perf_counter()
            try:
                if isinstance(payload, tuple):
                    url, body = payload
                    answer = await self._fetch(url, body=body)
                else:
                    answer = await self._json(payload)
            except Exception as exc:
                return {
                    "source": f"{kind}:{host}",
                    "ok": False,
                    "ms": round((time.perf_counter() - started) * 1000),
                    "error": f"{type(exc).__name__}: {exc}"[:120],
                }
            elapsed = round((time.perf_counter() - started) * 1000)
            stream = self._parse(kind, host, answer, height=height) if answer else None
            HEALTH.record(
                f"{kind}:{host}",
                stream is not None,
                ms=elapsed,
                error="" if stream else "no usable stream",
            )
            return {
                "source": f"{kind}:{host}",
                "ok": stream is not None,
                "ms": elapsed,
                "detail": stream.label if stream else "",
                "error": "" if stream else "no usable stream",
            }

        tasks = [one(kind, host, payload) for kind, host, payload in self._plan(target, height=height)]
        if tasks:
            results = list(await asyncio.gather(*tasks))
        return results

    async def meta(self, video_id: str) -> VideoMeta | None:
        """Read a video's title from a mirror — no yt-dlp, no player page.

        This is what makes a shared link usable while YouTube is refusing the
        server: the id is all we have, and the title is what the substitution
        tier needs to find the same song somewhere that plays.
        """
        target = (video_id or "").strip()
        if not re.fullmatch(r"[\w-]{6,24}", target):
            from vyron.core.search import youtube_id

            target = youtube_id(target) or ""
        if not target:
            return None
        requests: list[asyncio.Task] = []
        for host in self.invidious:
            if HEALTH.available(f"invidious:{host}"):
                requests.append(
                    asyncio.create_task(self._meta_one(f"https://{host}/api/v1/videos/{target}"))
                )
        for host in self.piped:
            if HEALTH.available(f"piped:{host}"):
                requests.append(asyncio.create_task(self._meta_one(f"https://{host}/streams/{target}")))
        if not requests:
            return None
        try:
            for finished in asyncio.as_completed(requests):
                meta = await finished
                if meta is not None:
                    return meta
        finally:
            for task in requests:
                if not task.done():
                    task.cancel()
        return None

    async def _meta_one(self, url: str) -> VideoMeta | None:
        payload = await self._json(url)
        return parse_meta("meta", payload) if payload else None

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
    "COBALT_HOSTS",
    "DirectStream",
    "INVIDIOUS_HOSTS",
    "PIPED_HOSTS",
    "PublicStreams",
    "get_public_streams",
    "parse_cobalt",
    "parse_invidious",
    "parse_invidious_video",
    "parse_piped",
    "parse_piped_video",
    "reset_public_streams",
]
