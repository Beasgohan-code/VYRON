# ---------------------------------------------------------------------------
#  VYRON — health / keep-alive web server
#  Render, Koyeb and Railway all want an HTTP port; this also gives you a
#  tiny JSON status endpoint.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from aiohttp import web

from vyron.config import settings
from vyron.runtime import runtime

logger = logging.getLogger(__name__)


def _build_stamp() -> str:
    """The build stamp, even before `run()` has written it to the runtime.

    `/health` and `/status` are read by operators *because* something is wrong,
    often in a harness that never went through `vyron.__main__`. An empty
    string there reads as "no build" instead of "unknown build".
    """
    try:
        from vyron import __build__

        return runtime.build or __build__
    except Exception:  # pragma: no cover - defensive
        return runtime.build or "dev"


async def _index(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "service": "vyron",
            "version": runtime.version,
            "build": _build_stamp(),
            "uptime": round(runtime.uptime, 1),
            "streaming": runtime.streaming_ready,
            "problems": list(runtime.boot_problems),
            "active_players": len(runtime.player.active_chats()) if runtime.player else 0,
            "storage": runtime.storage.backend if runtime.storage else "none",
            "instance": _lease_status(),
            "database": _database(),
        }
    )


def _database() -> dict:
    """Backend and a live round-trip — a cached "connected" is not a probe."""
    storage = runtime.storage
    if storage is None:
        return {"backend": "none", "ok": False}
    reason = getattr(storage, "ephemeral_reason", "") or ""
    return {
        "backend": getattr(storage, "backend", "unknown"),
        "ok": True,
        "durable": not reason,
        "warning": reason or None,
        "last_error": getattr(storage, "last_error", "") or None,
    }


def _lease_status() -> dict:
    """Whether this process owns the voice chat, and who does if not."""
    try:
        from vyron.core import lease

        return lease.status()
    except Exception:  # pragma: no cover - never break a health probe
        return {}


def _youtube_status() -> dict:
    """Whether YouTube is refusing this server, and who is playing instead.

    This is the one line an operator needs when the app "plays nothing": it
    separates a walled IP (nothing to do with the code) from a broken resolver.
    """
    youtube = getattr(runtime, "youtube", None)
    if youtube is None:
        return {"ready": False}
    try:
        from vyron.core import alternate

        return {
            "ready": True,
            "walled": bool(getattr(youtube, "walled", lambda: False)()),
            "wall_seconds_left": int(getattr(youtube, "wall_seconds_left", lambda: 0)()),
            "serving_from": alternate.describe(),
        }
    except Exception:  # pragma: no cover - never break a health probe
        return {"ready": True}


def _resolver_summary() -> dict:
    """Which tier produced a URL recently — no host names, no secrets."""
    try:
        from vyron.core.resolvers import HEALTH

        return HEALTH.summary()
    except Exception:  # pragma: no cover - never break a health probe
        return {}


async def _health(_request: web.Request) -> web.Response:
    """Liveness probe.

    Always 200 (Render/Koyeb treat non-2xx as unhealthy); `ready` tells you
    whether the bot has finished booting.
    """
    ready = runtime.bot is not None and runtime.storage is not None
    from vyron.core import accelerator, keepalive, watchdog

    try:
        from vyron.utils import commands

        prefixes = list(commands.configured())
    except Exception:  # pragma: no cover - never break a health probe
        prefixes = []

    return web.json_response(
        {
            "ok": True,
            # `status` keeps third-party uptime monitors ({"status": "ok"}) happy too.
            "status": "ok",
            "ready": ready,
            "degraded": bool(runtime.boot_problems) or not runtime.streaming_ready,
            "problems": list(runtime.boot_problems),
            "streaming": runtime.streaming_ready,
            "playback": "disk" if settings.play_from_disk else "stream",
            "resolvers": _resolver_summary(),
            "youtube": _youtube_status(),
            "downloads": {
                "accelerator": accelerator.detect(),
                "installed": [tool.name for tool in accelerator.available() if tool.present],
            },
            "prefixes": prefixes,
            "version": runtime.version,
            "build": _build_stamp(),
            "instance": _lease_status(),
            "database": _database(),
            "apis": {
                "music": settings.music_api,
                "download": settings.vyron_api,
            },
            "uptime": round(runtime.uptime, 1),
            "watchdog": {
                key: value
                for key, value in watchdog.status().items()
                if key in {"checks", "reconnects", "last", "last_error"}
            },
            "keepalive": {
                key: value
                for key, value in keepalive.status().items()
                if key in {"enabled", "runs", "last_ok", "last_status"}
            },
        }
    )


def build_app(*, with_webapp: bool = True) -> web.Application:
    app = web.Application()
    try:
        from vyron.web.middleware import record_errors

        app.middlewares.append(record_errors)
    except Exception as exc:  # pragma: no cover - web extras disabled
        logger.debug("journal middleware unavailable: %s", exc)
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/status", _index)
    if with_webapp:
        from vyron.web import register as register_webapp

        register_webapp(app)
    # The music API is independent of the Mini App toggle: it is the same
    # process/port either way, so `/v1` always lives on this URL.
    try:
        from vyron.api import register as register_music_api

        register_music_api(app)
    except Exception as exc:  # pragma: no cover - never block liveness
        logger.warning("music api disabled: %s", exc)
    # The download API answers on /vyron of the *same* port, so a client that
    # only wants a file (or one ported from another service) changes its base
    # URL and nothing else.
    try:
        from vyron.engine import register as register_download_api

        register_download_api(app)
    except Exception as exc:  # pragma: no cover - never block liveness
        logger.warning("download api disabled: %s", exc)
    return app


async def start_degraded(port: int, reason: str, problems: list[str] | None = None) -> web.AppRunner | None:
    """Serve *only* /health, with the reason, instead of exiting.

    A music bot that crashes on a missing env var takes the whole deployment
    down with it: Render shows "server failure", restarts, and floods Telegram
    with a fresh login attempt every time. Answering this port with a JSON
    explanation keeps the service alive, the logs honest, and the health check
    green while the operator fixes the variable.
    """
    if not port:
        return None
    details = [problem for problem in (problems or []) if problem] or [reason]
    app = web.Application()

    async def _degraded(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "ok": True,
                "status": "degraded",
                "ready": False,
                "service": "vyron",
                "version": runtime.version,
            "build": _build_stamp(),
                "reason": reason,
                "problems": details,
                "hint": "fix the env var(s) above in the dashboard, then redeploy",
            }
        )

    app.router.add_get("/", _degraded)
    app.router.add_get("/health", _degraded)
    app.router.add_get("/status", _degraded)
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        # All interfaces: Render/Koyeb route to the container, not to a loopback.
        site = web.TCPSite(runner, host="0.0.0.0", port=port)  # noqa: S104
        await site.start()
        logger.error("degraded mode on 0.0.0.0:%s — %s", port, reason)
        return runner
    except Exception as exc:  # pragma: no cover
        logger.error("degraded server could not start on %s: %s", port, exc)
        return None


async def start(port: int) -> web.AppRunner | None:
    """Start the health + web-app server on 0.0.0.0:<port>."""
    if not port:
        return None
    runner = web.AppRunner(build_app(), access_log=None)
    try:
        await runner.setup()
        # All interfaces: Render/Koyeb route to the container, not to a loopback.
        site = web.TCPSite(runner, host="0.0.0.0", port=port)  # noqa: S104
        await site.start()
        logger.info("health server listening on 0.0.0.0:%s", port)
        return runner
    except Exception as exc:
        logger.warning("health server could not start on %s: %s", port, exc)
        try:
            await runner.cleanup()
        except Exception:
            pass
        return None


__all__ = ["build_app", "start", "start_degraded"]
