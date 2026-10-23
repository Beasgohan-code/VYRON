# ---------------------------------------------------------------------------
#  VYRON API — endpoints
#
#  /v1 is mounted as its own aiohttp sub-application, so everything below is
#  relative to that prefix.  Two route families are served side by side:
#
#    canonical  POST /tracks · GET /tracks/{id} · GET /tracks/{id}/stream
#               POST /search · GET /lyrics · GET /me · /admin/keys
#    legacy     POST /track/by-video-id · POST /track/by-query
#               GET /info/by-video-id · GET /key          (legacy aliases)
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import platform
import logging
import re
import time
from urllib.parse import quote
from typing import Any

from aiohttp import web

from vyron.api.errors import ApiError
from vyron.api.metrics import METRICS
from vyron.api.state import AUTH
from vyron.api.security import authorize, describe, headers_for
from vyron.config import settings
from vyron.core.musicapi import SCOPES, get_music_api, mask_key
from vyron.runtime import runtime

logger = logging.getLogger(__name__)

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{6,24}$")
_download_slots: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _download_slots
    if _download_slots is None:
        _download_slots = asyncio.Semaphore(2)
    return _download_slots


# ── shared helpers ─────────────────────────────────────────────────────────
def base_url(request: web.Request) -> str:
    prefix = "/v1"
    if settings.api_base:
        return f"{settings.api_base}{prefix}"
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}{prefix}"


def _site_url(request: web.Request) -> str:
    """Everything before /v1 — used for links back to the Mini App."""
    return base_url(request)[: -len("/v1")]


def ensure_ready() -> None:
    if runtime.youtube is None or runtime.downloader is None:
        raise ApiError("not_ready")


async def payload(request: web.Request) -> dict[str, Any]:
    data: dict[str, Any] = dict(request.query)
    if request.can_read_body:
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                data.update(parsed)
        except Exception:
            try:
                form = await request.post()
                data.update({key: str(value) for key, value in form.items()})
            except Exception:
                pass
    return data


def video_id_from(data: dict[str, Any]) -> str:
    raw = str(data.get("video_id") or data.get("id") or data.get("v") or data.get("url") or "").strip()
    if raw.startswith("http"):
        from vyron.core.search import youtube_id

        raw = youtube_id(raw) or ""
    if not VIDEO_RE.match(raw):
        raise ApiError("invalid_video")
    return raw


def track_json(track, request: web.Request) -> dict[str, Any]:
    api = base_url(request)
    return {
        "video_id": track.id,
        "title": track.title,
        "artist": track.uploader,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "source": track.source,
        "url": track.watch_url,
        "stream_url": f"{api}/tracks/{track.id}/stream",
        "info_url": f"{api}/tracks/{track.id}",
        "lyrics_url": f"{api}/lyrics?title={track.title}&artist={track.uploader}",
    }


async def _resolve(target: str):
    try:
        return await runtime.youtube.resolve(target)
    except Exception as exc:
        logger.info("music api resolve failed: %s", exc)
        raise ApiError("upstream_failed", str(exc)) from exc


async def _download(track):
    async with _sem():
        try:
            return await runtime.downloader.audio(track)
        except Exception as exc:
            logger.warning("music api download failed: %s", exc)
            raise ApiError("upstream_failed", str(exc)) from exc


def content_disposition(title: str, track_id: str, *, inline: bool = False) -> str:
    """A latin-1-safe ``Content-Disposition`` for any title.

    HTTP headers cannot carry arbitrary Unicode; a Cyrillic or emoji title used
    to raise UnicodeEncodeError and turn a good request into a 500.
    """
    safe = (
        f"{title[:60]} [{track_id}]"
        .replace("/", "-")
        .replace('"', "")
        .replace("\\", "-")
        .replace("\n", " ")
        .replace("\r", " ")
    )
    ascii_name = safe.encode("ascii", "ignore").decode().strip() or str(track_id)
    encoded = quote(f"{safe}.mp3", safe="")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}.mp3\"; filename*=UTF-8''{encoded}"


async def serve_track(request: web.Request, target: str, *, inline: bool = False) -> web.StreamResponse:
    auth = request[AUTH]
    ensure_ready()
    track = await _resolve(target)
    path = await _download(track)
    size = path.stat().st_size
    await get_music_api().note_use(auth.record, size=size)
    METRICS.note_download(size)

    headers = {
        **headers_for(auth),
        "Content-Disposition": content_disposition(track.title, str(track.id), inline=inline),
        "X-Track-Id": str(track.id),
        "X-Track-Title": track.title[:200].encode("ascii", "ignore").decode() or "track",
        "X-Track-Artist": (track.uploader or "")[:200].encode("ascii", "ignore").decode(),
        "X-Track-Duration": str(track.duration),
        "X-Track-Size": str(size),
        "Cache-Control": "private, max-age=0",
        "Access-Control-Expose-Headers": "X-Track-Id, X-Track-Title, X-Track-Artist, "
        "X-Track-Duration, X-Track-Size, X-RateLimit-Limit, X-RateLimit-Remaining",
    }
    return web.FileResponse(path, headers=headers)


# ── system ─────────────────────────────────────────────────────────────────
async def index(request: web.Request) -> web.Response:
    if "text/html" in request.headers.get("Accept", "") and request.query.get("format") != "json":
        from vyron.api.docs import render

        return await render(request)
    api = base_url(request)
    site = _site_url(request)
    stats = await get_music_api().stats()
    return web.json_response(
        {
            "ok": True,
            "service": "vyron-music-api",
            "api_version": "2.0",
            "version": runtime.version,
            "status": "ok",
            "base_url": api,
            "docs": f"{site}/v1/docs",
            "openapi": f"{api}/openapi.json",
            "changelog": f"{site}/v1/docs#changelog",
            "keys": stats["keys"],
            "auth": "open" if stats["open"] else "required",
            "endpoints": {
                "health": "GET /v1/health",
                "download": "POST /v1/tracks",
                "downloads": "POST /v1/downloads  →  GET /v1/downloads/{job_id}",
                "stream": "GET /v1/tracks/{video_id}/stream",
                "metadata": "GET /v1/tracks/{video_id}",
                "search": "GET /v1/search?q=…",
                "lyrics": "GET /v1/lyrics?title=…",
                "me": "GET /v1/me",
                "admin": "GET /v1/admin/keys",
                "metrics": "GET /v1/metrics",
            },
        }
    )


async def health(request: web.Request) -> web.Response:
    api = get_music_api()
    stats = await api.stats()
    metrics = METRICS.snapshot()
    return web.json_response(
        {
            "status": "ok",
            "ok": True,
            "service": "vyron-music-api",
            "api_version": "2.0",
            "version": runtime.version,
            "uptime": round(runtime.uptime, 1),
            "ready": runtime.youtube is not None and runtime.downloader is not None,
            "streaming": runtime.streaming_ready,
            "auth_required": not settings.music_api_open,
            "rate_limit": stats["rate_limit"],
            "keys": stats["keys"],
            "downloads_served": metrics["downloads"],
            "scopes": list(SCOPES),
            "endpoints": [
                "/v1/tracks",
                "/v1/tracks/{video_id}",
                "/v1/tracks/{video_id}/stream",
                "/v1/downloads",
                "/v1/search",
                "/v1/lyrics",
                "/v1/me",
                "/v1/metrics",
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


async def version(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "api": "2.0",
            "bot": runtime.version,
            "python": platform.python_version(),
            "features": ["download", "stream", "search", "metadata", "lyrics", "keys", "metrics"],
        }
    )


async def metrics_route(request: web.Request) -> web.Response:
    await authorize(request, "admin")
    wants_text = request.query.get("format") == "prometheus" or "text/plain" in request.headers.get("Accept", "")
    if wants_text:
        return web.Response(text=METRICS.prometheus(), content_type="text/plain; version=0.0.4")
    return web.json_response({"ok": True, **METRICS.snapshot()})


# ── tracks ─────────────────────────────────────────────────────────────────
async def download(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    ensure_ready()
    data = await payload(request)
    video_id = data.get("video_id") or data.get("id")
    query = str(data.get("query") or data.get("q") or "").strip()
    if video_id:
        return await serve_track(request, f"https://www.youtube.com/watch?v={video_id_from(data)}")
    if query:
        return await serve_track(request, query)
    raise ApiError("bad_request", "send either video_id or query")


async def track_by_video_id(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    ensure_ready()
    data = await payload(request)
    return await serve_track(request, f"https://www.youtube.com/watch?v={video_id_from(data)}")


async def track_by_query(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    ensure_ready()
    data = await payload(request)
    query = str(data.get("query") or data.get("q") or "").strip()
    if not query:
        raise ApiError("missing_query")
    return await serve_track(request, query)


async def stream(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    ensure_ready()
    video_id = request.match_info.get("video_id", "")
    if not VIDEO_RE.match(video_id):
        raise ApiError("invalid_video")
    return await serve_track(
        request,
        f"https://www.youtube.com/watch?v={video_id}",
        inline=request.query.get("download") not in {"1", "true", "yes"},
    )


async def track_info(request: web.Request) -> web.Response:
    auth = await authorize(request, "read")
    ensure_ready()
    video_id = request.match_info.get("video_id", "")
    if not VIDEO_RE.match(video_id):
        raise ApiError("invalid_video")
    track = await _resolve(f"https://www.youtube.com/watch?v={video_id}")
    return web.json_response({"ok": True, "track": track_json(track, request)}, headers=headers_for(auth))


async def legacy_info(request: web.Request) -> web.Response:
    request.match_info["video_id"] = video_id_from(await payload(request))
    return await track_info(request)


# ── search / lyrics ────────────────────────────────────────────────────────
async def search(request: web.Request) -> web.Response:
    auth = await authorize(request, "search")
    ensure_ready()
    data = await payload(request)
    query = str(data.get("query") or data.get("q") or "").strip()
    if not query:
        raise ApiError("missing_query")
    try:
        limit = max(1, min(25, int(data.get("limit") or settings.search_results)))
    except (TypeError, ValueError):
        limit = settings.search_results

    started = time.perf_counter()
    try:
        tracks = await runtime.youtube.search(query, limit=limit)
    except Exception as exc:
        logger.info("music api search failed: %s", exc)
        raise ApiError("upstream_failed", str(exc)) from exc

    return web.json_response(
        {
            "ok": True,
            "query": query,
            "count": len(tracks),
            "took_ms": round((time.perf_counter() - started) * 1000, 1),
            "results": [track_json(track, request) for track in tracks],
        },
        headers=headers_for(auth),
    )


async def lyrics(request: web.Request) -> web.Response:
    auth = await authorize(request, "read")
    data = await payload(request)
    title = str(data.get("title") or data.get("q") or "").strip()
    artist = str(data.get("artist") or "").strip()
    if not title:
        raise ApiError("bad_request", "title is required")
    if runtime.lyrics is None:
        raise ApiError("not_ready", "lyrics engine is not ready")

    try:
        duration = int(float(data.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    try:
        result = await (
            runtime.lyrics.timed(title, artist, duration)
            if duration
            else runtime.lyrics.find(title, artist)
        )
    except Exception as exc:
        raise ApiError("upstream_failed", str(exc)) from exc
    if result is None:
        raise ApiError("not_found", "no lyrics found for that track")

    from vyron.core.lyrics import parse_lrc

    return web.json_response(
        {
            "ok": True,
            "title": result.title,
            "artist": result.artist,
            "synced": bool(result.has_sync),
            "text": result.as_text(),
            "lines": parse_lrc(result.synced),
        },
        headers=headers_for(auth),
    )


# ── key self-service + admin ───────────────────────────────────────────────
async def me(request: web.Request) -> web.Response:
    auth = await authorize(request)
    return web.json_response({"ok": True, **describe(auth)}, headers=headers_for(auth))


async def admin_keys(request: web.Request) -> web.Response:
    auth = await authorize(request, "admin")
    api = get_music_api()

    if request.method == "GET":
        owner = request.query.get("owner_id")
        records = await api.keys(int(owner) if owner and owner.lstrip("-").isdigit() else None, reveal=False)
        return web.json_response(
            {
                "ok": True,
                "count": len(records),
                "keys": [
                    {
                        **record,
                        "key": f"{record.get('prefix')}…",
                        "masked": mask_key(str(record.get("hash") or record.get("prefix") or "")),
                    }
                    for record in records
                ],
                "requested_by": mask_key(str((auth.record or {}).get("prefix") or "")),
            },
            headers=headers_for(auth),
        )

    data = await payload(request)
    owner_id = int(data.get("owner_id") or (auth.record or {}).get("owner_id") or settings.owner_id or 0)
    record, error = await api.issue(
        owner_id,
        str(data.get("label") or "api"),
        scopes=data.get("scopes"),
        days=int(data["days"]) if str(data.get("days") or "").isdigit() else None,
        rate_limit=int(data["rate_limit"]) if str(data.get("rate_limit") or "").isdigit() else None,
    )
    if record is None:
        raise ApiError("bad_request", error or "could not create key")
    return web.json_response(
        {
            "ok": True,
            "created": {
                **{key: value for key, value in record.items() if key != "hash"},
                "masked": mask_key(record["key"]),
            },
        },
        status=201,
        headers=headers_for(auth),
    )


async def admin_key_item(request: web.Request) -> web.Response:
    auth = await authorize(request, "admin")
    identifier = request.match_info.get("identifier", "")
    revoked = await get_music_api().revoke(None, identifier, force=True)
    if not revoked:
        raise ApiError("not_found", "no key matches that id, prefix or value")
    return web.json_response(
        {"ok": True, "revoked": identifier, "by": mask_key(str((auth.record or {}).get("prefix") or ""))},
        headers=headers_for(auth),
    )


async def admin_rotate(request: web.Request) -> web.Response:
    await authorize(request, "admin")
    identifier = request.match_info.get("identifier", "")
    record, error = None, "not found"
    for candidate in await get_music_api().keys(reveal=False):
        if candidate.get("id") == identifier or candidate.get("prefix") == identifier:
            record, error = await get_music_api().rotate(int(candidate.get("owner_id") or 0), identifier)
            break
    if record is None:
        raise ApiError("not_found", error)
    return web.json_response(
        {"ok": True, "created": {**{k: v for k, v in record.items() if k != "hash"}, "masked": mask_key(record["key"])}}
    )


# ── docs / spec ────────────────────────────────────────────────────────────
async def docs(request: web.Request) -> web.Response:
    from vyron.api.docs import render

    return await render(request)


async def openapi(request: web.Request) -> web.Response:
    from vyron.api.openapi import spec

    return web.json_response(spec(request))


__all__ = ["base_url", "payload", "track_json", "ensure_ready"]
