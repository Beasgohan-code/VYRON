# ---------------------------------------------------------------------------
#  VYRON — connection watchdog
#
#  Long-running bots drift: the MTProto socket drops, Telegram starts refusing
#  requests for a while, or the assistant client dies without an exception the
#  process could react to. This loop notices and repairs:
#
#    * bot not connected          → stop() + start()
#    * get_me() timing out        → reconnect after two consecutive failures
#    * assistant disconnected     → same, only when streaming is enabled
#
#  It also becomes a tiny health signal: `/health` and `/dbstats` can show the
#  last check and how many reconnects happened.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

from vyron.config import settings
from vyron.runtime import runtime

logger = logging.getLogger(__name__)

_state: dict[str, object] = {
    "checks": 0,
    "failures": 0,
    "reconnects": 0,
    "last": None,
    "last_error": "",
}
_task: asyncio.Task | None = None


def status() -> dict[str, object]:
    return dict(_state, enabled=settings.watchdog_seconds > 0)


def _connected(client) -> bool:
    """Pyrogram exposes `is_connected`; treat a missing attribute as connected."""
    try:
        return bool(getattr(client, "is_connected", True))
    except Exception:  # pragma: no cover - property raising
        return True


async def _restart(client) -> bool:
    """Reconnect a client in place. Returns True when it came back up."""
    try:
        await client.stop()
    except Exception as exc:
        logger.debug("watchdog: stop failed (%s)", exc)
    try:
        await client.start()
        _state["reconnects"] = int(_state["reconnects"]) + 1
        logger.warning("watchdog: reconnected %s", getattr(client, "name", "client"))
        return True
    except Exception as exc:
        logger.error("watchdog: reconnect failed: %s", exc)
        return False


async def check_once(*, bot=None, assistant=None, collect_handlers=None) -> list[str]:
    """Run one health check. Returns the list of problems repaired."""
    bot = bot or runtime.bot
    assistant = assistant or runtime.assistant
    problems: list[str] = []
    _state["checks"] = int(_state["checks"]) + 1
    _state["last"] = time.time()

    for label, client, enabled in (
        ("bot", bot, True),
        ("assistant", assistant, runtime.streaming_ready),
    ):
        if client is None or not enabled:
            continue
        if not _connected(client):
            problems.append(f"{label} disconnected")
            await _restart(client)
            continue

    if bot is not None and _connected(bot):
        try:
            await asyncio.wait_for(bot.get_me(), timeout=15)
            _state["last_error"] = ""
        except Exception as exc:
            problems.append(f"get_me: {type(exc).__name__}")
            _state["failures"] = int(_state["failures"]) + 1
            _state["last_error"] = str(exc)[:120]
            # one hiccup is normal (network blip); two in a row is not
            if int(_state["failures"]) % 2 == 0:
                await _restart(bot)
                if collect_handlers is not None:
                    try:
                        runtime.handlers_loaded = collect_handlers(bot)
                    except Exception as handler_exc:  # pragma: no cover
                        logger.debug("handler re-registration failed: %s", handler_exc)

    if problems:
        logger.warning("watchdog: %s", ", ".join(problems))
    return problems


async def _loop() -> None:
    await asyncio.sleep(max(10, settings.watchdog_seconds))
    while True:
        try:
            await check_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("watchdog loop error: %s", exc)
        await asyncio.sleep(max(10, settings.watchdog_seconds))


def start() -> asyncio.Task | None:
    global _task
    if settings.watchdog_seconds <= 0:
        logger.info("watchdog disabled (WATCHDOG_SECONDS=0)")
        return None
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
        logger.info("watchdog every %ss", settings.watchdog_seconds)
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


__all__ = ["check_once", "start", "status", "stop"]
