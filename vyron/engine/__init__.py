# ---------------------------------------------------------------------------
#  VYRON — download API  (/vyron)
# ---------------------------------------------------------------------------
# One process, one port, one URL: the same server that answers /health, serves
# the Mini App and hosts /v1 also exposes a small, stable "give me this video"
# API. Clients that only want an audio file never have to learn the full music
# API, and scripts migrated from other services only change the base URL.
#
# The download engine itself is derived from the Eldian Music API (MIT); the
# licence text is kept at the top of engine/youtube.py, and the surface here —
# paths, keys, envelopes, headers — is VYRON's own.
from __future__ import annotations

import logging

from aiohttp import web

from vyron.config import settings

logger = logging.getLogger(__name__)

MOUNT = "/vyron"
MOUNTED = web.AppKey("vyron_engine_mounted", bool)


def register(app: web.Application) -> bool:
    """Mount the download API at /vyron (idempotent)."""
    if not getattr(settings, "vyron_api", True):
        return False
    if app.get(MOUNTED):
        return True
    from vyron.engine.routes import build

    app.add_subapp(MOUNT, build())
    app[MOUNTED] = True
    logger.info("download api mounted at %s/v1 (keys: the same ones as /v1)", MOUNT)
    return True


__all__ = ["MOUNT", "MOUNTED", "register"]
