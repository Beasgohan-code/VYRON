# ---------------------------------------------------------------------------
#  VYRON — keep-alive
#
#  Free web hosts (Render, Koyeb, Railway trial) sleep a service that sees no
#  inbound traffic for ~15 minutes. A music bot that sleeps stops answering
#  Telegram, so VYRON pings its own public URL on a timer:
#
#      GET {base}/health          liveness
#      GET {base}/app/            warms the Mini App bundle
#
#  The base URL comes from KEEPALIVE_URL, else RENDER_EXTERNAL_URL (set by
#  Render automatically), else WEBAPP_URL. Set KEEPALIVE_MINUTES=0 to disable.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

import aiohttp

from vyron.config import settings

logger = logging.getLogger(__name__)

_state: dict[str, object] = {
    "runs": 0,
    "failures": 0,
    "last": None,
    "last_ok": None,
    "last_status": None,
    "url": "",
}
_task: asyncio.Task | None = None

PATHS = ("/health", "/app/")


def base_url() -> str:
    """Public base URL to ping, or an empty string when there is nothing to do."""
    for candidate in (
        getattr(settings, "keepalive_url", ""),
        getattr(settings, "render_external_url", ""),
        settings.webapp_url,
    ):
        if candidate:
            return str(candidate).rstrip("/")
    return ""


def status() -> dict[str, object]:
    return dict(_state, enabled=bool(base_url()) and settings.keepalive_minutes > 0)


async def ping(base: str | None = None, *, session: aiohttp.ClientSession | None = None) -> bool:
    """One round trip against /health and /app/. Never raises."""
    target = (base or base_url()).rstrip("/")
    if not target:
        return False
    own_session = session is None
    timeout = aiohttp.ClientTimeout(total=15)
    ok = True
    try:
        if own_session:
            session = aiohttp.ClientSession(timeout=timeout)
        for path in PATHS:
            try:
                async with session.get(f"{target}{path}") as response:
                    _state["last_status"] = response.status
                    await response.read()
                    ok = ok and response.status < 500
            except Exception as exc:
                ok = False
                _state["failures"] = int(_state["failures"]) + 1
                logger.debug("keep-alive %s%s failed: %s", target, path, exc)
    finally:
        if own_session and session is not None:
            await session.close()
    _state["runs"] = int(_state["runs"]) + 1
    _state["last"] = time.time()
    _state["url"] = target
    if ok:
        _state["last_ok"] = _state["last"]
    return ok


async def _loop() -> None:
    interval = max(1, settings.keepalive_minutes) * 60
    while True:
        try:
            await ping()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("keep-alive loop error: %s", exc)
        await asyncio.sleep(interval)


def start() -> asyncio.Task | None:
    global _task
    if settings.keepalive_minutes <= 0:
        logger.info("keep-alive disabled (KEEPALIVE_MINUTES=0)")
        return None
    target = base_url()
    if not target:
        logger.info(
            "keep-alive idle — set KEEPALIVE_URL (or WEBAPP_URL) to the public "
            "URL of this deployment to keep the host awake"
        )
        return None
    logger.info("keep-alive every %sm → %s", settings.keepalive_minutes, target)
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
    return _task


async def stop() -> None:
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    _task = None


__all__ = ["base_url", "ping", "start", "status", "stop"]
