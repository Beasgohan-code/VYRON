# ---------------------------------------------------------------------------
#  VYRON — health / keep-alive web server
#  Render, Koyeb and Railway all want an HTTP port; this also gives you a
#  tiny JSON status endpoint.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from aiohttp import web

from vyron.runtime import runtime

logger = logging.getLogger(__name__)


async def _index(_request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "service": "vyron",
            "version": runtime.version,
            "uptime": round(runtime.uptime, 1),
            "streaming": runtime.streaming_ready,
            "active_players": len(runtime.player.active_chats()) if runtime.player else 0,
            "storage": runtime.storage.backend if runtime.storage else "none",
        }
    )


async def _health(_request: web.Request) -> web.Response:
    """Liveness probe.

    Always 200 (Render/Koyeb treat non-2xx as unhealthy); `ready` tells you
    whether the bot has finished booting.
    """
    ready = runtime.bot is not None and runtime.storage is not None
    from vyron.core import keepalive, watchdog

    return web.json_response(
        {
            "ok": True,
            # `status` keeps Eldian-style monitors ({"status": "ok"}) happy too.
            "status": "ok",
            "ready": ready,
            "streaming": runtime.streaming_ready,
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
    return app


async def start(port: int) -> web.AppRunner | None:
    """Start the health + web-app server on 0.0.0.0:<port>."""
    if not port:
        return None
    runner = web.AppRunner(build_app(), access_log=None)
    try:
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
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


__all__ = ["build_app", "start"]
