# ---------------------------------------------------------------------------
#  VYRON — HTTP middleware that feeds the owner journal
#
#  A 500 that only exists in Render's log stream is useless six hours later.
#  Every unhandled exception and every 5xx the API produces is recorded with
#  the method, path and traceback, so `/logs` and the Mini App console can show
#  what actually broke.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time

from aiohttp import web

from vyron.core.journal import journal

logger = logging.getLogger(__name__)

_SLOW_MS = 4000
_MAX_MESSAGE = 400
# Endpoints that are long-lived by design: the log tail holds its connection
# open for as long as the console is on screen, and streamed audio lasts as long
# as the song. Calling those "slow" buries the requests that really are.
_STREAMING = ("/api/logs/stream", "/logs/live", "/api/stream", "/v1/tracks/")


@web.middleware
async def record_errors(request: web.Request, handler) -> web.StreamResponse:
    started = time.perf_counter()
    try:
        response = await handler(request)
    except web.HTTPException:
        raise
    except Exception as exc:
        # The type and message go in the *message*, not only in the metadata:
        # Render's log stream shows messages, so a bare "crashed" line forced a
        # trip to /api/logs before anyone knew what had happened. The full
        # traceback still travels in the meta.
        journal.error(
            "webapp",
            f"{request.method} {request.path_qs[:120]} crashed: "
            f"{type(exc).__name__}: {exc}"[: _MAX_MESSAGE],
            exc,
            status=500,
        )
        raise
    elapsed = (time.perf_counter() - started) * 1000
    if response.status >= 500:
        journal.error(
            "webapp",
            f"{request.method} {request.path_qs[:120]} → {response.status}",
            ms=round(elapsed),
        )
    elif (
        elapsed > _SLOW_MS
        and request.path.startswith("/api/")
        and not request.path.startswith(_STREAMING)
    ):
        journal.warn(
            "webapp",
            f"slow request {request.method} {request.path} ({elapsed:.0f} ms)",
        )
    return response


__all__ = ["record_errors"]
