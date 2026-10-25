# ---------------------------------------------------------------------------
#  VYRON — HTTP middleware that feeds the owner journal
#
#  A 500 that only exists in Render's log stream is useless six hours later.
#  Every unhandled exception and every 5xx the API produces is recorded with
#  the method, path and traceback, so `/logs` and the Mini App console can show
#  what actually broke.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

from aiohttp import web

try:  # aiohttp ≥ 3.10 names this class explicitly
    from aiohttp import ClientConnectionResetError as _ClientReset
except Exception:  # pragma: no cover - older aiohttp
    _ClientReset = ConnectionResetError  # type: ignore[assignment,misc]

from vyron.core.journal import journal

logger = logging.getLogger(__name__)

# The browser seeked, closed the tab, or the phone locked mid-stream. aiohttp
# raises its own class for this since 3.10, and it is *not* a ConnectionResetError
# subclass, so every `except ConnectionResetError` in the codebase missed it and
# the noise landed in the owner journal as a crash.
CLIENT_GONE: tuple[type[BaseException], ...] = (
    ConnectionResetError,
    ConnectionError,
    _ClientReset,
)

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
    except CLIENT_GONE as exc:
        # The browser seeked, closed the tab, or the phone locked. That is a
        # normal end to a stream request, not a server fault — logging it as an
        # error buried the requests that really were broken.
        logger.debug("%s %s: client went away (%s)", request.method, request.path, exc)
        if request.path.startswith(_STREAMING):
            # Streaming routes prepare the response themselves, so its bytes are
            # already on the wire; sending a 499 now would write a second status
            # line into the body (aiohttp then reads "Invalid character in chunk
            # size"). Cancelling is how this request actually ended: quietly.
            raise asyncio.CancelledError() from None
        return web.Response(status=499)
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


__all__ = ["CLIENT_GONE", "record_errors"]
