# ---------------------------------------------------------------------------
#  VYRON — secrets never reach a log line
# ---------------------------------------------------------------------------
# The rule is "never expose secrets", and the easiest place to break it is a
# log statement somebody adds at 2 a.m.: an exception whose message contains a
# URL with `?api_key=…`, a Mongo connection string echoed by a driver, a bot
# token in a traceback. This module scrubs those shapes out of every record
# before any handler writes it, so the ring buffer, the log channel and the
# console all agree.
from __future__ import annotations

import logging
import re

# Anything that looks like one of our own credentials, plus the usual suspects.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bvyrn_[A-Za-z0-9_\-]{6,}"), "vyrn_…"),
    (re.compile(r"\bvown_[A-Za-z0-9_\-]{6,}"), "vown_…"),
    # Telegram bot tokens: <bot id>:<35-ish chars>
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{30,}\b"), "<bot-token>"),
    # Mongo / Postgres / Redis URLs, with or without credentials
    (re.compile(r"\b(?:mongodb(?:\+srv)?|postgres(?:ql)?|redis|rediss|amqp)://[^\s'\"]+", re.I), "<db-url>"),
    # `?api_key=…`, `&token=…`, `Authorization: Bearer …`
    (re.compile(r"(?i)\b(api[_-]?key|token|secret|password|passwd|pwd|session|signature)=([^&\s'\"]+)"), r"\1=…"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]+"), r"\1…"),
    # ENV_STYLE assignments: STRING_SESSION=…, API_HASH=…, BOT_TOKEN=…
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:SESSION|TOKEN|KEY|SECRET|PASSWORD|HASH)[A-Z0-9_]*)\s*=\s*\S+"), r"\1=…"),
    # Pyrogram session strings are long base64 blobs with a version prefix
    (re.compile(r"\b[0-9a-fA-F]{128,}\b"), "<session>"),
)

# Values so short or so common that scrubbing them would hide real messages.
_SAFE_HOSTS = re.compile(r"(?i)\b(?:https?|wss?)://[^\s'\"]*")


def scrub(text: str) -> str:
    """Return *text* with credentials replaced by a placeholder."""
    if not text:
        return text
    cleaned = text
    for pattern, replacement in _PATTERNS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


class RedactFilter(logging.Filter):
    """A logging filter that rewrites the message before it is formatted."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - a broken format string
            return True
        cleaned = scrub(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = ()
        return True


def install(level: int = logging.NOTSET) -> None:
    """Attach the filter to every handler on the root logger (idempotent)."""
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, RedactFilter) for item in handler.filters):
            handler.addFilter(RedactFilter())
    for logger_name in ("aiohttp.access", "pyrogram", "pymongo"):
        for handler in logging.getLogger(logger_name).handlers:
            if not any(isinstance(item, RedactFilter) for item in handler.filters):
                handler.addFilter(RedactFilter())


__all__ = ["RedactFilter", "install", "scrub"]
