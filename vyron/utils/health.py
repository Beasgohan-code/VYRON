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
    ready = runtime.bot is not None and runtime.storage is not None
    return web.json_response({"ok": ready}, status=200 if ready else 503)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/status", _index)
    return app


async def start(port: int) -> web.AppRunner | None:
    """Start the health server on 0.0.0.0:<port>. Returns the runner."""
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
