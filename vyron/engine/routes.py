# ---------------------------------------------------------------------------
#  VYRON — download API (/vyron)
# ---------------------------------------------------------------------------
#   GET  /vyron/                       → what this is + links
#   GET  /vyron/health                 → engine status (no secrets)
#   GET  /vyron/v1/docs                → tiny OpenAPI 3 for generated clients
#   POST /vyron/v1/track/by-video-id   → {"video_id": "..."} → audio bytes
#   POST /vyron/v1/track/by-query      → {"query": "..."}     → audio bytes
#
# Same keys, scopes and rate limits as /v1 (one key store), same error
# envelope, same process and port. A client only needs to change its base URL.
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from typing import Any

from aiohttp import web

from vyron.api.errors import ApiError, envelope
from vyron.api.security import authorize
from vyron.config import settings
from vyron.engine import MOUNT
from vyron.engine.youtube import (
    EngineError,
    cleanup_download,
    cleanup_stale_downloads,
    download_audio_async,
    engine_status,
    new_request_dir,
)

logger = logging.getLogger(__name__)

VERSION = "1.0.0"
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_QUERY = 200

# Two downloads at once: enough to keep a script moving, few enough that API
# traffic can never starve voice-chat playback of CPU or upstream quota.
_slot: asyncio.Semaphore | None = None


def slots() -> asyncio.Semaphore:
    global _slot
    if _slot is None:
        _slot = asyncio.Semaphore(2)
    return _slot


# ── helpers ────────────────────────────────────────────────────────────────
async def body(request: web.Request) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if request.can_read_body:
        try:
            parsed = await request.json()
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            data.update(parsed)
    # query string wins nothing, but it lets GET clients work too
    data.update({key: value for key, value in request.query.items() if key not in data})
    return data


def video_id_from(data: dict[str, Any]) -> str:
    raw = str(data.get("video_id") or data.get("id") or data.get("url") or "").strip()
    if "v=" in raw:
        raw = raw.split("v=", 1)[1].split("&", 1)[0]
    elif "youtu.be/" in raw:
        raw = raw.split("youtu.be/", 1)[1].split("?", 1)[0].strip("/")
    elif raw.startswith("http"):
        raw = raw.rstrip("/").rsplit("/", 1)[-1]
    if not VIDEO_RE.match(raw):
        raise ApiError(
            "invalid_video",
            "video_id must be an 11-character YouTube id",
            hint="https://www.youtube.com/watch?v=dQw4w9WgXcQ → dQw4w9WgXcQ",
        )
    return raw


def schedule_cleanup(request: web.Request, path) -> None:
    """Delete the temp file once the response has been written."""

    def _drop() -> None:
        try:
            cleanup_download(path)
        except Exception:  # pragma: no cover - cleanup must never raise
            logger.debug("engine cleanup failed for %s", path, exc_info=True)

    task = getattr(request, "task", None)
    if task is not None and hasattr(task, "add_done_callback"):
        task.add_done_callback(lambda _t: _drop())
    else:  # pragma: no cover - mocked requests in tests
        asyncio.get_event_loop().call_later(60, _drop)


async def _resolve_query(query: str) -> str:
    """First search hit for a free-text query → its video id."""
    from vyron.core.search import MediaError
    from vyron.runtime import runtime

    youtube = getattr(runtime, "youtube", None)
    if youtube is None:
        raise ApiError("not_ready", "the bot is still starting — retry in a moment", status=503)
    try:
        results = await youtube.search(query, limit=1)
    except MediaError as exc:
        raise ApiError("upstream_failed", str(exc), status=502) from exc
    if not results:
        raise ApiError("not_found", f"no results for {query!r}", status=404)
    return results[0].id


async def _serve(request: web.Request, video_id: str) -> web.StreamResponse:
    folder = new_request_dir()
    async with slots():
        try:
            path = await download_audio_async(video_id, folder)
        except EngineError as exc:
            cleanup_download(folder)
            raise ApiError(exc.code, str(exc), status=exc.status) from exc
        except Exception as exc:  # pragma: no cover - defensive
            cleanup_download(folder)
            logger.exception("engine failed for %s", video_id)
            raise ApiError("upstream_failed", f"download failed: {exc}", status=502) from exc

    schedule_cleanup(request, path)
    return web.FileResponse(
        path,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": f'attachment; filename="{path.name}"',
            "X-Track-Id": video_id,
            "X-Engine": "vyron",
            "Cache-Control": "no-store",
        },
    )


# ── middleware ─────────────────────────────────────────────────────────────
@web.middleware
async def errors_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as exc:
        return envelope(exc.message, code=exc.code, status=exc.status, request=request)
    except web.HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("download api crash on %s %s", request.method, request.path)
        return envelope(f"unexpected error: {exc}", code="internal", status=500, request=request)


@web.middleware
async def headers_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers.setdefault("X-API-Version", "2.0")
    response.headers.setdefault("X-Request-Id", "req_" + secrets.token_hex(6))
    return response


# ── endpoints ──────────────────────────────────────────────────────────────
async def index(_request: web.Request) -> web.Response:
    base = MOUNT
    return web.json_response(
        {
            "service": "VYRON Download API",
            "engine": "vyron",
            "version": VERSION,
            "docs": f"{base}/v1/docs",
            "endpoints": {
                "health": f"{base}/health",
                "by_video_id": f"{base}/v1/track/by-video-id",
                "by_query": f"{base}/v1/track/by-query",
            },
            "auth": "X-API-Key — mint one with /getapi in Telegram",
        }
    )


async def health(_request: web.Request) -> web.Response:
    from vyron.runtime import runtime

    return web.json_response(
        {
            "status": "ok",
            "engine": "vyron",
            "version": VERSION,
            "ready": bool(getattr(runtime, "ready", False)),
            "download": engine_status(settings),
        }
    )


async def by_video_id(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    data = await body(request)
    return await _serve(request, video_id_from(data))


async def by_query(request: web.Request) -> web.StreamResponse:
    await authorize(request, "download")
    data = await body(request)
    query = str(data.get("query") or data.get("q") or "").strip()
    if not query:
        raise ApiError("missing_query", "send {\"query\": \"artist - title\"}")
    if len(query) > MAX_QUERY:
        raise ApiError("bad_request", f"query is limited to {MAX_QUERY} characters")
    return await _serve(request, await _resolve_query(query))


async def docs(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "openapi": "3.0.3",
            "info": {"title": "VYRON Download API", "version": VERSION},
            "components": {
                "securitySchemes": {
                    "ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}
                }
            },
            "security": [{"ApiKeyAuth": []}],
            "paths": {
                f"{MOUNT}/health": {"get": {"summary": "liveness + engine status"}},
                f"{MOUNT}/v1/track/by-video-id": {
                    "post": {
                        "summary": "download a track by YouTube video id",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"video_id": {"type": "string"}},
                                        "required": ["video_id"],
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "audio file"}},
                    }
                },
                f"{MOUNT}/v1/track/by-query": {
                    "post": {
                        "summary": "search, then download the top hit",
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {"query": {"type": "string"}},
                                        "required": ["query"],
                                    }
                                }
                            },
                        },
                        "responses": {"200": {"description": "audio file"}},
                    }
                },
            },
        }
    )


def build() -> web.Application:
    app = web.Application(
        middlewares=[headers_middleware, errors_middleware], client_max_size=1024 * 1024
    )
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_get("/v1/docs", docs)
    app.router.add_post("/v1/track/by-video-id", by_video_id)
    app.router.add_get("/v1/track/by-video-id", by_video_id)
    app.router.add_post("/v1/track/by-query", by_query)
    app.router.add_get("/v1/track/by-query", by_query)
    app.on_startup.append(_sweep)
    app.on_cleanup.append(_sweep)
    return app


async def _sweep(_app: web.Application) -> None:
    removed = await asyncio.to_thread(cleanup_stale_downloads, settings.downloads_dir)
    if removed:
        logger.info("engine: swept %s stale download directories", removed)


__all__ = ["build", "by_query", "by_video_id", "health", "index", "video_id_from"]
