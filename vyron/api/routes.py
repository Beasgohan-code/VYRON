# ---------------------------------------------------------------------------
#  VYRON API — endpoints
#
#  /v1 is mounted as its own aiohttp sub-application, so everything below is
#  relative to that prefix.  Two route families are served side by side:
#
#    canonical  POST /tracks · GET /tracks/{id} · GET /tracks/{id}/stream
#               POST /search · GET /lyrics · GET /me · GET /sources
#               GET/POST /keys · PATCH/DELETE /keys/{id} · /admin/keys
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
from vyron.core.musicapi import (
    API_VERSION,
    MAX_KEYS_PER_OWNER,
    SCOPES,
    get_music_api,
    mask_key,
)
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


async def ensure_ready() -> None:
    """Wait out a cold start, then fail honestly if the engine never arrives."""
    if runtime.youtube is not None and runtime.downloader is not None:
        return
    await runtime.wait_ready(getattr(settings, "boot_wait", 15.0))
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


async def _guard_url(target: str) -> str:
    """SSRF guard for a URL that came from a client, not from us."""
    from vyron.core.urlguard import BlockedURL, check_user_url

    try:
        return await check_user_url(target)
    except BlockedURL as exc:
        raise ApiError("blocked_url", str(exc)) from exc


async def _resolve(target: str):
    if target.lower().startswith(("http://", "https://")):
        target = await _guard_url(target)
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
    await ensure_ready()
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
            "api_version": API_VERSION,
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
                "download_api": "POST /vyron/v1/track/by-video-id · by-query",
            },
        }
    )


async def readiness(request: web.Request) -> web.Response:
    """Liveness says the process is up; this says it can actually work.

    Render's health check belongs on /v1/health (a restart loop is worse than a
    slow boot); a load balancer or an uptime probe that should stop sending
    traffic belongs here, because it returns 503 until the engine exists.
    """
    ready = runtime.youtube is not None and runtime.downloader is not None
    body = {
        "ok": ready,
        "ready": ready,
        "status": "ready" if ready else "booting",
        "streaming": runtime.streaming_ready,
        "storage": getattr(runtime.storage, "backend", "none"),
        "uptime": round(runtime.uptime, 1),
        "boot_seconds": round(time.time() - runtime.boot_started_at, 1),
    }
    headers = {"Cache-Control": "no-store"}
    if not ready:
        headers["Retry-After"] = "5"
    return web.json_response(body, status=200 if ready else 503, headers=headers)


async def health(request: web.Request) -> web.Response:
    api = get_music_api()
    stats = await api.stats()
    metrics = METRICS.snapshot()
    return web.json_response(
        {
            "status": "ok",
            "ok": True,
            "service": "vyron-music-api",
            "api_version": API_VERSION,
            "version": runtime.version,
            "uptime": round(runtime.uptime, 1),
            "ready": runtime.youtube is not None and runtime.downloader is not None,
            "boot_seconds": round(time.time() - runtime.boot_started_at, 1),
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
                "/vyron/v1/track/by-video-id",
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
            "api": API_VERSION,
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
    await ensure_ready()
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
    await ensure_ready()
    data = await payload(request)
    return await serve_track(request, f"https://www.youtube.com/watch?v={video_id_from(data)}")


async def track_by_query(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    await ensure_ready()
    data = await payload(request)
    query = str(data.get("query") or data.get("q") or "").strip()
    if not query:
        raise ApiError("missing_query")
    return await serve_track(request, query)


async def stream(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    await ensure_ready()
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
    await ensure_ready()
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
    await ensure_ready()
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
    """Who am I, what may I do, how much quota is left, when do I expire."""
    auth = await authorize(request)
    info = describe(auth)
    created = info.get("created_at")
    expires = info.get("expires_at")
    now = time.time()
    info["usage"] = {
        "requests": int((auth.record or {}).get("uses") or 0),
        "bytes": int((auth.record or {}).get("bytes") or 0),
        "last_used_at": (auth.record or {}).get("last_used_at"),
        "age_seconds": round(now - created, 1) if created else None,
        "expires_in": round(expires - now, 1) if expires else None,
    }
    info["capabilities"] = {
        scope: info["scopes"].count(scope) > 0 or info["mode"] in {"owner", "open"}
        for scope in SCOPES
    }
    info["available_scopes"] = list(SCOPES)
    return web.json_response({"ok": True, **info}, headers=headers_for(auth))


# ── sources ────────────────────────────────────────────────────────────────
async def sources_route(request: web.Request) -> web.Response:
    """Every source VYRON can use, in fallback order, with live health."""
    auth = await authorize(request, "read")
    from vyron.core import sources as registry

    rows = registry.status(settings)
    if request.query.get("probe") in {"1", "true", "yes"}:
        # Probing spends an upstream request per source, so it is an admin tool.
        await authorize(request, "admin")
        rows = await registry.probe(settings)
    name = request.match_info.get("name")
    if name:
        match = next((row for row in rows if row["name"] == name), None)
        if match is None:
            raise ApiError("not_found", f"no source called '{name}'")
        match["tracks"] = _source_usage(name)
        return web.json_response({"ok": True, "source": match}, headers=headers_for(auth))

    return web.json_response(
        {
            "ok": True,
            "primary": ["ytmusic", "ytdlp"],
            "fallback": [row["name"] for row in rows if row["kind"] == "stream"],
            "catalogues": [row["name"] for row in rows if row["kind"] == "catalogue"],
            "order": registry.describe(settings),
            "sources": [{**row, "tracks": _source_usage(row["name"])} for row in rows],
        },
        headers=headers_for(auth),
    )


def _actor(auth) -> int:
    """The owner id behind the current request (key owner, else the owner)."""
    if auth.record:
        return int(auth.record.get("owner_id") or 0)
    return int(settings.owner_id or 0)


def _source_usage(name: str) -> int:
    """How many successful resolves this process has seen for *name*."""
    try:
        from vyron.core.resolvers import HEALTH

        summary = HEALTH.summary()
        for key, value in summary.items():
            if str(key).lower().startswith(name):
                return int((value or {}).get("ok") or 0)
    except Exception:  # pragma: no cover - health is advisory
        pass
    return 0


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
                    {**record, "key": record.get("masked") or ""} for record in records
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
        by=_actor(auth),
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


async def own_keys(request: web.Request) -> web.Response:
    """Self-service: a key manages *its own owner's* keys, nothing else.

    The Mini App uses owner-token auth for the same job; this is the path for a
    script or a CI pipeline that already holds a `vyrn_` key and should not need
    an owner token to rotate itself.
    """
    auth = await authorize(request, "read")
    owner_id = _actor(auth)
    if not owner_id:
        raise ApiError("forbidden_scope", "this key has no owner to manage")
    api = get_music_api()

    if request.method == "GET":
        records = await api.keys(owner_id, reveal=False, include_revoked=False)
        return web.json_response(
            {
                "ok": True,
                "owner_id": owner_id,
                "count": len(records),
                "limit": MAX_KEYS_PER_OWNER,
                "keys": records,
            },
            headers=headers_for(auth),
        )

    data = await payload(request)
    if not auth.has("admin"):
        # Minting is a privileged act even on your own account: otherwise a
        # stolen read key could be laundered into a download key.
        raise ApiError("forbidden_scope", "creating keys requires the admin scope")
    record, error = await api.issue(
        owner_id,
        str(data.get("label") or "api"),
        scopes=data.get("scopes"),
        days=int(data["days"]) if str(data.get("days") or "").isdigit() else None,
        rate_limit=int(data["rate_limit"]) if str(data.get("rate_limit") or "").isdigit() else None,
        by=_actor(auth),
    )
    if record is None:
        raise ApiError("bad_request", error or "could not create key")
    created = {key: value for key, value in record.items() if key != "hash"}
    created["masked"] = mask_key(str(record.get("key") or ""))
    return web.json_response({"ok": True, "created": created}, status=201, headers=headers_for(auth))


async def own_key_item(request: web.Request) -> web.Response:
    auth = await authorize(request, "read")
    owner_id = _actor(auth)
    identifier = request.match_info.get("identifier", "")
    api = get_music_api()

    if request.method == "DELETE":
        revoked = await api.revoke(owner_id, identifier, by=_actor(auth))
        if not revoked:
            raise ApiError("not_found", "no key of yours matches that id or prefix")
        return web.json_response(
            {"ok": True, "revoked": identifier}, headers=headers_for(auth)
        )

    data = await payload(request)
    days = data.get("days", data.get("expires_in_days"))
    record, error = await api.update_key(
        owner_id,
        identifier,
        label=data.get("label"),
        scopes=data.get("scopes"),
        days=int(days) if str(days).lstrip("-").isdigit() else None,
        rate_limit=(
            int(data["rate_limit"]) if str(data.get("rate_limit")).lstrip("-").isdigit() else None
        ),
        by=_actor(auth),
    )
    if record is None:
        raise ApiError("not_found" if "not found" in error or "belongs" in error else "bad_request", error)
    return web.json_response({"ok": True, "key": record}, headers=headers_for(auth))


async def admin_key_item(request: web.Request) -> web.Response:
    """GET one key's details · PATCH its label/scopes/expiry/quota · DELETE it."""
    auth = await authorize(request, "admin")
    identifier = request.match_info.get("identifier", "")
    if request.method in {"GET", "PATCH"}:
        if request.method == "GET":
            record = await get_music_api().find(identifier, force=True)
            if record is None:
                raise ApiError("not_found", "no key matches that id, prefix or value")
            record["quota"] = {
                "limit_per_minute": get_music_api()._limit_for(record),
                "requests": int(record.get("uses") or 0),
                "bytes": int(record.get("bytes") or 0),
            }
            return web.json_response({"ok": True, "key": record}, headers=headers_for(auth))

        data = await payload(request)
        days = data.get("days", data.get("expires_in_days"))
        record, error = await get_music_api().update_key(
            None,
            identifier,
            label=data.get("label"),
            scopes=data.get("scopes"),
            days=int(days) if str(days or "").lstrip("-").isdigit() else None,
            rate_limit=(
                int(data["rate_limit"])
                if str(data.get("rate_limit")).lstrip("-").isdigit()
                else None
            ),
            force=True,
            by=_actor(auth),
        )
        if record is None:
            raise ApiError("not_found" if "not found" in error else "bad_request", error)
        return web.json_response({"ok": True, "key": record}, headers=headers_for(auth))

    revoked = await get_music_api().revoke(None, identifier, force=True, by=_actor(auth))
    if not revoked:
        raise ApiError("not_found", "no key matches that id, prefix or value")
    return web.json_response(
        {"ok": True, "revoked": identifier, "by": _actor(auth)},
        headers=headers_for(auth),
    )


async def admin_rotate(request: web.Request) -> web.Response:
    auth = await authorize(request, "admin")
    identifier = request.match_info.get("identifier", "")
    record, error = None, "not found"
    for candidate in await get_music_api().keys(reveal=False):
        if candidate.get("id") == identifier or candidate.get("prefix") == identifier:
            record, error = await get_music_api().rotate(
                int(candidate.get("owner_id") or 0), identifier, by=_actor(auth)
            )
            break
    if record is None:
        raise ApiError("not_found", error)
    created = {key: value for key, value in record.items() if key != "hash"}
    created["masked"] = mask_key(str(record.get("key") or ""))
    return web.json_response({"ok": True, "created": created}, headers=headers_for(auth))


# ── docs / spec ────────────────────────────────────────────────────────────
async def docs(request: web.Request) -> web.Response:
    from vyron.api.docs import render

    return await render(request)


async def openapi(request: web.Request) -> web.Response:
    from vyron.api.openapi import spec

    return web.json_response(spec(request))


__all__ = ["base_url", "payload", "track_json", "ensure_ready"]
