# ---------------------------------------------------------------------------
#  VYRON API — application factory
#
#  The API is an aiohttp *sub-application* mounted at /v1 on the same server as
#  the bot's health endpoint and Mini App.  That gives it its own middleware
#  stack (errors, request ids, CORS, metrics) without touching the rest of the
#  app, and keeps the deployment at exactly one URL.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time

from aiohttp import web

from vyron.api import downloads, routes
from vyron.api.errors import ApiError, envelope, error_response, request_id
from vyron.api.metrics import METRICS
from vyron.api.state import MOUNTED, REQUEST_ID
from vyron.config import settings
from vyron.core.musicapi import API_VERSION

logger = logging.getLogger(__name__)


# ── middleware ─────────────────────────────────────────────────────────────
@web.middleware
async def errors_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except ApiError as exc:
        return error_response(exc, request)
    except web.HTTPException as exc:
        if exc.status == 404:
            return envelope(
                "no such endpoint — see /v1/docs", code="not_found", status=404, request=request
            )
        if exc.status == 405:
            return envelope("method not allowed", code="bad_request", status=405, request=request)
        return envelope(str(exc.reason or "request failed"), code="bad_request", status=exc.status, request=request)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("music api crash on %s %s", request.method, request.path)
        return envelope(f"unexpected error: {exc}", code="internal", status=500, request=request)


@web.middleware
async def context_middleware(request: web.Request, handler):
    started = time.perf_counter()
    request[REQUEST_ID] = "req_" + request_id(request)[4:]
    response = await handler(request)
    elapsed_ms = (time.perf_counter() - started) * 1000

    response.headers["X-Request-Id"] = request[REQUEST_ID]
    response.headers["X-API-Version"] = API_VERSION
    response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
    response.headers.setdefault("Cache-Control", "no-store")

    route = request.match_info.route.resource.canonical if request.match_info.route.resource else request.path
    code = ""
    if response.status >= 400:
        try:
            code = response.headers.get("X-Error-Code", "")
        except Exception:
            code = ""
    METRICS.observe(route, response.status, elapsed_ms, code=code)
    return response


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response: web.StreamResponse = web.Response(status=204)
    else:
        response = await handler(request)

    origin = request.headers.get("Origin")
    if settings.music_api_cors:
        response.headers["Access-Control-Allow-Origin"] = origin or "*"
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "X-API-Key, Authorization, Content-Type"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


# ── factory ────────────────────────────────────────────────────────────────
def build_app() -> web.Application:
    app = web.Application(
        middlewares=[errors_middleware, context_middleware, cors_middleware],
        client_max_size=2 * 1024 * 1024,
    )
    router = app.router

    # system
    router.add_get("/", routes.index)
    router.add_get("/docs", routes.docs)
    router.add_get("/openapi.json", routes.openapi)
    router.add_get("/health", routes.health)
    router.add_get("/ready", routes.readiness)
    router.add_get("/version", routes.version)
    router.add_get("/metrics", routes.metrics_route)

    # tracks
    router.add_post("/tracks", routes.download)
    router.add_get("/tracks/{video_id}", routes.track_info)
    router.add_get("/tracks/{video_id}/stream", routes.stream)

    # asynchronous downloads (submit → poll → fetch)
    router.add_post("/downloads", downloads.submit)
    router.add_get("/downloads", downloads.listing)
    router.add_get("/downloads/by-video-id/{video_id}", downloads.by_url)
    router.add_get("/downloads/{job_id}", downloads.status)
    router.add_get("/downloads/{job_id}/file", downloads.file)
    router.add_delete("/downloads/{job_id}", downloads.cancel)

    # discovery
    router.add_get("/search", routes.search)
    router.add_post("/search", routes.search)
    router.add_get("/lyrics", routes.lyrics)
    router.add_post("/lyrics", routes.lyrics)

    # keys
    router.add_get("/me", routes.me)
    router.add_get("/sources", routes.sources_route)
    router.add_get("/sources/{name}", routes.sources_route)
    router.add_post("/token", routes.mint_token)
    router.add_get("/keys", routes.own_keys)
    router.add_post("/keys", routes.own_keys)
    router.add_patch("/keys/{identifier}", routes.own_key_item)
    router.add_delete("/keys/{identifier}", routes.own_key_item)
    router.add_get("/admin/keys", routes.admin_keys)
    router.add_post("/admin/keys", routes.admin_keys)
    router.add_get("/admin/keys/{identifier}", routes.admin_key_item)
    router.add_patch("/admin/keys/{identifier}", routes.admin_key_item)
    router.add_delete("/admin/keys/{identifier}", routes.admin_key_item)
    router.add_post("/admin/keys/{identifier}/rotate", routes.admin_rotate)

    # legacy aliases (kept so old integrations never break)
    router.add_post("/track/by-video-id", routes.track_by_video_id)
    router.add_get("/track/by-video-id", routes.track_by_video_id)
    router.add_post("/track/by-query", routes.track_by_query)
    router.add_get("/track/by-query", routes.track_by_query)
    router.add_get("/info/by-video-id", routes.legacy_info)
    router.add_get("/key", routes.me)

    return app


async def _bare_v1(_request: web.Request) -> web.StreamResponse:
    """`/v1` without the trailing slash should not 404."""
    raise web.HTTPPermanentRedirect("/v1/")


def register(app: web.Application) -> bool:
    """Mount the API at /v1 (idempotent, safe to call from tests)."""
    if not settings.music_api:
        return False
    if app.get(MOUNTED):
        return True
    app.router.add_get("/v1", _bare_v1)
    app.add_subapp("/v1", build_app())
    app[MOUNTED] = True
    logger.info(
        "music api mounted at /v1 (%s mode, %s req/min)",
        "open" if settings.music_api_open else "keyed",
        settings.music_api_rate,
    )
    return True


__all__ = ["API_VERSION", "build_app", "register"]
