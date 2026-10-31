# ---------------------------------------------------------------------------
#  VYRON — the log channel
#
#  Live logging, wired to the journal instead of a second printer:
#  with /logger on, every warning and error is mirrored into LOGGER_ID as a
#  compact card, so an owner sees trouble on their phone without opening
#  /logs. Off by default, persisted, rate limited, and silent when the bot has
#  no channel configured or cannot post there.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

from vyron.config import settings
from vyron.core.journal import Event, journal

logger = logging.getLogger(__name__)

_META = "log_channel_enabled"
_MAX_PER_MINUTE = 20
_GLYPH = {"warn": "⚠️", "error": "❌", "ok": "✅", "info": "ℹ️", "debug": "·"}

_enabled = False
_bot: Any = None
_sent: deque[float] = deque(maxlen=_MAX_PER_MINUTE)
_last_error: str | None = None


def is_enabled() -> bool:
    return _enabled and bool(settings.logger_id)


def last_error() -> str | None:
    return _last_error


def format_event(event: Event) -> str:
    """One journal event as a rich Telegram card — headings, blockquote, clean meta."""
    glyph = _GLYPH.get(event.level, "•")
    stamp = time.strftime("%H:%M:%S", time.localtime(event.ts))
    level = event.level.upper()
    text = (
        f"<b>{glyph} {level}</b> · <code>{_escape(event.scope)}</code> · <code>{stamp}</code>\n"
        f"<blockquote>{_escape(event.message)}</blockquote>"
    )
    meta = {k: v for k, v in (event.meta or {}).items() if k != "traceback"}
    if meta:
        pairs = " · ".join(f"{key}={value}" for key, value in list(meta.items())[:5])
        text += f"\n<i>{_escape(pairs)}</i>"
    if event.meta.get("traceback") and event.level == "error":
        text += f"\n<pre>{_escape(str(event.meta['traceback']))[-900:]}</pre>"
    return text


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _mark_error(exc: BaseException) -> None:
    global _last_error
    _last_error = str(exc)[:200]


def _rate_limited(now: float | None = None) -> bool:
    stamp = now if now is not None else time.time()
    while _sent and stamp - _sent[0] > 60:
        _sent.popleft()
    if len(_sent) >= _MAX_PER_MINUTE:
        return True
    _sent.append(stamp)
    return False


def _sink(event: Event) -> None:
    """Called from the journal on every event; cheap when disabled."""
    if not is_enabled() or event.level not in {"warn", "error"}:
        return
    if not _bot:
        return
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return  # recorded off-loop (thread pool) — the journal still has it
    from vyron.utils.helpers import spawn

    spawn(_deliver(event), name="logsink:deliver")


async def _deliver(event: Event) -> None:
    if _rate_limited():
        return
    try:
        await _bot.send_message(
            settings.logger_id,
            format_event(event),
            parse_mode="html",
            disable_web_page_preview=True,
        )
    except Exception as exc:  # channel deleted, bot removed, flood…
        logger.debug("log channel delivery failed: %s", exc)


def install(bot: Any) -> None:
    """Route journal warn/error events to the configured channel."""
    global _bot
    _bot = bot
    journal.set_sink(_sink)


async def load(storage: Any) -> bool:
    """Read the saved on/off flag at boot."""
    global _enabled
    if storage is None:
        return False
    try:
        _enabled = bool(await storage.get_meta(_META, False))
    except Exception:
        _enabled = False
    return _enabled


async def set_enabled(storage: Any, value: bool) -> bool:
    global _enabled
    _enabled = bool(value) and bool(settings.logger_id)
    if storage is not None:
        try:
            await storage.set_meta(_META, _enabled)
        except Exception as exc:  # pragma: no cover - persistence is best effort
            logger.debug("could not persist the log-channel flag: %s", exc)
    journal.info("journal", f"log channel {'on' if _enabled else 'off'}")
    return _enabled


__all__ = [
    "format_event",
    "install",
    "is_enabled",
    "load",
    "set_enabled",
]
