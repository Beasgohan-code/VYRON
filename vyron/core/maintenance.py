# ---------------------------------------------------------------------------
#  VYRON — housekeeping
#
#  A quiet loop that keeps a long-running deployment healthy:
#
#    * delete download files past `DOWNLOAD_CACHE_HOURS`
#    * prune history/favourite rows past `MAINTENANCE_DAYS`
#
#  Both are also available on demand (`/clearcache`, `/dbcleanup`); the loop
#  just means a bot left running for weeks never fills the disk or the DB.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

from vyron.config import settings
from vyron.runtime import runtime

logger = logging.getLogger(__name__)

_state: dict[str, float | int | None] = {"last": None, "files": 0, "rows": 0}
_task: asyncio.Task | None = None


def status() -> dict[str, object]:
    """Last sweep, for `/dbstats` style cards."""
    return {
        "last": _state["last"],
        "files": int(_state["files"] or 0),
        "rows": int(_state["rows"] or 0),
        "every_hours": settings.maintenance_hours,
        "days": settings.maintenance_days,
    }


async def run_once() -> dict[str, int]:
    """One sweep. Safe to call by hand — never raises."""
    files = 0
    rows = 0
    if runtime.downloader is not None:
        try:
            files = int(runtime.downloader.cleanup() or 0)
        except Exception as exc:  # pragma: no cover - filesystem oddities
            logger.debug("download cleanup failed: %s", exc)
    if runtime.storage is not None:
        try:
            removed = await runtime.storage.prune(settings.maintenance_days)
            rows = sum(int(value) for value in removed.values())
        except Exception as exc:  # pragma: no cover - backend oddities
            logger.debug("database prune failed: %s", exc)
    _state.update(last=time.time(), files=files, rows=rows)
    if files or rows:
        logger.info("housekeeping: %d files, %d rows removed", files, rows)
    return {"files": files, "rows": rows}


async def _loop() -> None:
    interval = max(1, settings.maintenance_hours) * 3600
    await asyncio.sleep(min(600, interval))  # don't sweep during the first minutes
    while True:
        await run_once()
        await asyncio.sleep(interval)


def start() -> asyncio.Task | None:
    """Background sweeper — no-op when maintenance is disabled."""
    global _task
    if settings.maintenance_hours <= 0:
        logger.info("housekeeping disabled (MAINTENANCE_HOURS=0)")
        return None
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


__all__ = ["run_once", "start", "status", "stop"]
