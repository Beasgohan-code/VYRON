# ---------------------------------------------------------------------------
#  VYRON — in-app audio
#
#  The Mini App can play tracks itself (Spotify-style) instead of only steering
#  the voice chat. Two endpoints make that work:
#
#      GET /api/stream/<media_id>   audio bytes, HTTP Range aware
#      GET /api/audio/<media_id>    small JSON: duration, mime, source
#
#  Resolution order for `<media_id>`:
#      1. the per-process track registry (everything the UI has been shown)
#      2. the live player (current track + queue)
#      3. the user's favourites / playlists
#
#  Bytes come from the download cache when a file exists, otherwise the
#  resolved googlevideo URL is proxied with the browser's Range header, so
#  seeking works without downloading the whole track first.
#
#  Demo tracks (`demo01`…) have no upstream: a deterministic little synth loop
#  is generated locally, which is what makes the standalone preview playable
#  without network access.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from pathlib import Path
from urllib.parse import quote

import aiohttp
from aiohttp import web

from vyron.config import settings
from vyron.core.queue import Track
from vyron.core.search import MediaError, StreamInfo
from vyron.runtime import runtime
from vyron.web.auth import WebUser, resolve_user

logger = logging.getLogger(__name__)

MAX_REGISTRY = 600
_REGISTRY: OrderedDict[str, Track] = OrderedDict()
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)", re.I)
_CHUNK = 64 * 1024


# ── registry ───────────────────────────────────────────────────────────────
def remember(*tracks: Track | None) -> None:
    """Keep the tracks we have serialised to a client, so /api/stream can find them."""
    for track in tracks:
        if track is None or not track.id:
            continue
        key = str(track.id)
        _REGISTRY[key] = track
        _REGISTRY.move_to_end(key)
    while len(_REGISTRY) > MAX_REGISTRY:
        _REGISTRY.popitem(last=False)


def lookup(media_id: str, *, user_id: int = 0) -> Track | None:
    """Find a playable track by id — registry first, then live state."""
    key = str(media_id)
    found = _REGISTRY.get(key)
    if found is not None:
        return found

    player = runtime.player
    if player is not None:
        for chat_id in player.active_chats():
            try:
                state = player.queues.get(chat_id)
            except Exception:  # pragma: no cover - defensive
                continue
            if state.current is not None and str(state.current.id) == key:
                return state.current
            for item in state.queue:
                if str(item.id) == key:
                    return item

    storage = runtime.storage
    if storage is not None and user_id:
        # favourites and playlists are only reachable through async calls; the
        # caller runs inside the loop, so this is fine.
        return None
    return None


async def lookup_async(media_id: str, *, user_id: int = 0) -> Track | None:
    found = lookup(media_id, user_id=0)
    if found is not None:
        return found
    storage = runtime.storage
    if storage is None or not user_id:
        return None
    try:
        for item in await storage.favorites(user_id, limit=50):
            if str(item.get("id")) == str(media_id):
                return Track.from_dict(item)
        for playlist in await storage.playlists(user_id):
            for item in playlist.get("tracks", []):
                if str(item.get("id")) == str(media_id):
                    return Track.from_dict(item)
    except Exception as exc:  # pragma: no cover - storage hiccup
        logger.debug("lookup_async failed: %s", exc)
    return None


def registry_size() -> int:
    return len(_REGISTRY)


# ── demo tone ──────────────────────────────────────────────────────────────
def _tone_path(media_id: str) -> Path:
    root = Path(settings.data_dir) / "audio"
    return root / f"{media_id}.wav"


def _synth(seed: str, *, seconds: float = 24.0, rate: int = 16000) -> bytes:
    """A small deterministic WAV loop so the preview sounds like something."""
    import math
    import struct
    import wave

    import io

    digest = sum(ord(ch) for ch in seed) or 7
    base = 110 + (digest % 5) * 22           # A2 … C#3
    scale = (0, 3, 5, 7, 10)                 # minor pentatonic
    frames = int(rate * seconds)
    buf = bytearray()
    note_len = rate // 2                     # half-second notes
    for index in range(frames):
        step = index // note_len
        freq = base * (2 ** (scale[(step + digest) % len(scale)] / 12))
        # gentle 4-note arpeggio + low pad, then a soft fade at both ends
        t = index / rate
        arp = math.sin(2 * math.pi * freq * t) * (0.32 if step % 4 else 0.4)
        pad = math.sin(2 * math.pi * (base / 2) * t) * 0.14
        beat = 1.0 if (index // (rate // 4)) % 4 == 0 else 0.6
        sample = (arp * beat + pad) * 0.55
        fade = min(1.0, t / 0.6, max(0.0, (seconds - t) / 1.2))
        buf += struct.pack("<h", int(max(-1.0, min(1.0, sample * fade)) * 30000))

    out = io.BytesIO()
    with wave.open(out, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(buf))
    return out.getvalue()


def demo_audio(media_id: str) -> Path:
    path = _tone_path(media_id)
    if path.is_file() and path.stat().st_size > 1024:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(_synth(media_id))
    tmp.replace(path)
    return path


def demo_video(media_id: str, title: str = "") -> bytes | None:
    """A tiny MP4 wrapper is out of scope — audio only."""
    return None


# ── helpers ────────────────────────────────────────────────────────────────
def _identity(request: web.Request) -> WebUser:
    return resolve_user(
        init_data=request.query.get("init_data", ""),
        token=request.query.get("t", ""),
        bot_token=settings.bot_token,
        allow_anon=settings.webapp_allow_anon,
        owner_ids=settings.owners,
    )


_MIME_BY_SUFFIX = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "audio/webm",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
}


class UpstreamExpired(RuntimeError):
    """The signed media URL has expired (YouTube answers 403/410)."""


def _file_response(path: Path, request: web.Request, *, mime: str = "") -> web.StreamResponse:
    response = web.FileResponse(path, headers={"Accept-Ranges": "bytes"})
    response.content_type = mime or _MIME_BY_SUFFIX.get(path.suffix.lower(), "audio/mpeg")
    response.headers["Cache-Control"] = "private, max-age=3600"
    response.headers["Content-Disposition"] = f"inline; filename={quote(path.name)}"
    return response


def _proxy_headers(request: web.Request, info: StreamInfo) -> dict[str, str]:
    headers = dict(info.headers) or {"User-Agent": "Mozilla/5.0 (compatible; VYRON/1.0)"}
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header
    return headers


async def _proxy_range(
    request: web.Request, info: StreamInfo
) -> web.StreamResponse:
    """Stream the signed media URL, forwarding Range so the browser can seek.

    The headers come from yt-dlp's own resolve: googlevideo binds a URL to the
    client fingerprint that requested it, so a fresh User-Agent is a 403.
    """
    headers = _proxy_headers(request, info)
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=60)
    session = aiohttp.ClientSession(timeout=timeout, headers=headers)
    try:
        try:
            upstream = await session.get(info.url)
        except Exception as exc:
            logger.warning("audio proxy failed: %s", exc)
            raise web.HTTPBadGateway(text="could not reach the audio source") from exc

        try:
            if upstream.status in (403, 410):
                raise UpstreamExpired(f"upstream returned {upstream.status}")
            if upstream.status == 416:
                response = web.Response(status=416, headers={"Content-Range": upstream.headers.get("Content-Range", "bytes */*")})
                return response
            if upstream.status >= 400:
                raise web.HTTPBadGateway(text=f"audio source answered {upstream.status}")

            status = 206 if upstream.status == 206 else 200
            response = web.StreamResponse(
                status=status,
                headers={
                    "Content-Type": upstream.headers.get("Content-Type", info.mime),
                    "Accept-Ranges": "bytes",
                    "Cache-Control": "private, max-age=900",
                },
            )
            for header in ("Content-Range", "Content-Length"):
                if header in upstream.headers:
                    response.headers[header] = upstream.headers[header]
            await response.prepare(request)
            try:
                async for chunk in upstream.content.iter_chunked(_CHUNK):
                    await response.write(chunk)
            except (ConnectionResetError, asyncio.CancelledError):
                # the browser seeked away or closed the tab — not an error
                raise
            await response.write_eof()
            return response
        finally:
            upstream.release()
    finally:
        await session.close()


def _upstream_error(reason: str, hint: str = "tap play again in a moment") -> web.Response:
    return web.json_response(
        {"ok": False, "error": "upstream_failed", "reason": reason, "hint": hint},
        status=502,
    )


# ── routes ─────────────────────────────────────────────────────────────────
async def stream(request: web.Request) -> web.StreamResponse:
    user = _identity(request)
    if not user.authenticated and not settings.webapp_allow_anon:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    media_id = (request.match_info.get("media_id") or "").strip()
    if not media_id or "/" in media_id or ".." in media_id:
        return web.json_response({"ok": False, "error": "bad id"}, status=400)

    # demo tracks are always available locally
    if re.fullmatch(r"demo\d{2}", media_id, re.I):
        path = await asyncio.to_thread(demo_audio, media_id.lower())
        return _file_response(path, request, mime="audio/wav")

    track = await lookup_async(media_id, user_id=user.user_id)
    if track is None:
        return web.json_response(
            {"ok": False, "error": "unknown track", "hint": "search for it first"},
            status=404,
        )

    downloader = runtime.downloader
    if downloader is not None:
        cached = downloader.cached(track)
        if cached is not None:
            return _file_response(cached, request)

    if runtime.youtube is None:
        return web.json_response(
            {
                "ok": False,
                "error": "not_ready",
                "hint": "install yt-dlp (it is in requirements.txt) and restart",
            },
            status=503,
        )

    try:
        info = await runtime.youtube.stream_info(track)
    except MediaError as exc:
        logger.info("could not resolve stream for %s: %s", media_id, exc)
        return _upstream_error(str(exc)[:180], "the bot could not resolve this track — try another result")
    except Exception as exc:  # defensive: a resolver bug must not 500 the audio
        logger.warning("stream resolve crashed for %s: %s", media_id, exc)
        return _upstream_error(str(exc)[:180])

    if request.method == "HEAD":
        return web.Response(
            status=200,
            headers={
                "Content-Type": info.mime,
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=60",
            },
        )

    # Signed URLs expire; one silent re-resolve fixes the common 403.
    for attempt in range(2):
        try:
            return await _proxy_range(request, info)
        except UpstreamExpired as exc:
            logger.info("stream URL expired for %s (%s)", media_id, exc)
            if attempt:
                break
            try:
                info = await runtime.youtube.stream_info(track, refresh=True)
            except Exception:
                break
        except web.HTTPException as exc:
            # The proxy already answered upstream; turn it into JSON so the app
            # can show a reason instead of a bare HTML error page.
            logger.info("audio proxy failed for %s: %s", media_id, exc.reason)
            return _upstream_error(str(exc.reason or "the audio source failed"))

    return _upstream_error("the audio source rejected the stream", "tap play again, or use /song to get the file")


async def audio_info(request: web.Request) -> web.Response:
    user = _identity(request)
    media_id = (request.match_info.get("media_id") or "").strip()
    # Demo ids are synthetic and locally generated: answer for them first, so a
    # remembered demo track can never be described as "not streamable".
    if re.fullmatch(r"demo\d{2}", media_id, re.I):
        return web.json_response(
            {
                "ok": True,
                "id": media_id,
                "title": "VYRON demo",
                "duration": 24,
                "mime": "audio/wav",
                "demo": True,
                "playable": True,
                "stream": f"/api/stream/{media_id}",
            }
        )
    track = await lookup_async(media_id, user_id=user.user_id)
    if track is None:
        return web.json_response({"ok": False, "error": "unknown track"}, status=404)
    cached = runtime.downloader.cached(track) if runtime.downloader else None
    ready = runtime.youtube is not None
    payload = {
        "ok": True,
        "id": track.id,
        "title": track.title,
        "uploader": track.uploader,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "source": track.source,
        "cached": bool(cached),
        "playable": bool(cached) or ready,
        "mime": "audio/mpeg" if cached else "audio/mp4",
        "stream": f"/api/stream/{track.id}",
    }
    if not payload["playable"]:
        payload["reason"] = "streaming is not configured on this deployment"
    return web.json_response(payload)


def register(app: web.Application) -> None:
    app.router.add_get("/api/stream/{media_id}", stream)
    app.router.add_get("/api/audio/{media_id}", audio_info)


__all__ = ["audio_info", "demo_audio", "lookup", "lookup_async", "register", "remember", "registry_size", "stream"]
