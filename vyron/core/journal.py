# ---------------------------------------------------------------------------
#  VYRON — owner journal
#
#  A single, bounded, append-only record of what the process actually did:
#  boot and shutdown, streaming start/stop, watchdog reconnects, database
#  failures and every warning or error the loggers emit.
#
#  It exists because "the bot died at 3am" is not a diagnosis. Owners can read
#  it three ways:
#
#      /logs                 inside Telegram (owner only)
#      GET /api/logs         the Mini App's console (owner token required)
#      data/journal.jsonl    on disk, rotated at 4 MB
#
#  The ring buffer keeps the last 2000 events in memory so the API can serve a
#  cursor (`?since=<seq>`) without touching the disk.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
import platform
import sys
import threading
import time
import traceback
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

LEVELS: tuple[str, ...] = ("debug", "info", "ok", "warn", "error")
_SEVERITY = {"debug": 10, "info": 20, "ok": 20, "warn": 30, "error": 40}

_MAX_EVENTS = 2000
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_MESSAGE = 600

# Logger prefixes are noisy (`vyron.core.player`); the scope is what an owner
# scans for, so every event carries a short one.
_SCOPES: tuple[tuple[str, str], ...] = (
    ("vyron.core.player", "player"),
    ("vyron.core.queue", "queue"),
    ("vyron.core.search", "search"),
    ("vyron.core.downloader", "download"),
    ("vyron.core.watchdog", "watchdog"),
    ("vyron.core.keepalive", "keepalive"),
    ("vyron.core.maintenance", "maintenance"),
    ("vyron.core.journal", "journal"),
    ("vyron.web.stream", "stream"),
    ("vyron.web.server", "webapp"),
    ("vyron.web.auth", "auth"),
    ("vyron.api.", "api"),
    ("vyron.database", "database"),
    ("vyron.clients", "telegram"),
    ("vyron.modules", "command"),
    ("pyrogram", "telegram"),
    ("pytgcalls", "voice"),
    ("ntgcalls", "voice"),
    ("aiohttp", "http"),
    ("motor", "database"),
    ("pymongo", "database"),
    ("asyncio", "asyncio"),
)


def _scope_for(name: str) -> str:
    for prefix, scope in _SCOPES:
        if name == prefix or name.startswith(prefix):
            return scope
    return name.rsplit(".", 1)[-1] or "app"


def _trim(text: str, limit: int = _MAX_MESSAGE) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(slots=True)
class Event:
    """One line in the journal."""

    seq: int
    ts: float
    level: str
    scope: str
    message: str
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "level": self.level,
            "scope": self.scope,
            "message": self.message,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            seq=int(data.get("seq", 0)),
            ts=float(data.get("ts", 0)),
            level=str(data.get("level", "info")),
            scope=str(data.get("scope", "app")),
            message=str(data.get("message", "")),
            meta=dict(data.get("meta") or {}),
        )


class Journal:
    """Bounded event log — thread safe, JSONL backed, cursor addressable."""

    def __init__(self, path: Path | None = None, capacity: int = _MAX_EVENTS) -> None:
        self.path = path
        self._events: deque[Event] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._seq = 0
        self._counts: Counter[str] = Counter()
        self._handler: logging.Handler | None = None
        self.started_at = time.time()
        self.installed = False

    # ── writing ────────────────────────────────────────────────────────────
    def record(self, level: str, scope: str, message: str, **meta: Any) -> Event:
        level = level if level in _SEVERITY else "info"
        with self._lock:
            self._seq += 1
            event = Event(
                seq=self._seq,
                ts=time.time(),
                level=level,
                scope=scope or "app",
                message=_trim(message),
                meta={key: value for key, value in meta.items() if value is not None},
            )
            self._events.append(event)
            self._counts[level] += 1
            path = self.path
        if path is not None:
            self._persist(event, path)
        return event

    def _persist(self, event: Event, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > _MAX_FILE_BYTES:
                rotated = path.with_suffix(path.suffix + ".1")
                try:
                    if rotated.exists():
                        rotated.unlink()
                    path.rename(rotated)
                except OSError:
                    pass
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
        except OSError as exc:  # read-only disk — the ring buffer still works
            if self.installed:
                logging.getLogger("vyron.core.journal").debug("journal write failed: %s", exc)

    # ── convenience ────────────────────────────────────────────────────────
    def debug(self, scope: str, message: str, **meta: Any) -> Event:
        return self.record("debug", scope, message, **meta)

    def info(self, scope: str, message: str, **meta: Any) -> Event:
        return self.record("info", scope, message, **meta)

    def ok(self, scope: str, message: str, **meta: Any) -> Event:
        return self.record("ok", scope, message, **meta)

    def warn(self, scope: str, message: str, **meta: Any) -> Event:
        return self.record("warn", scope, message, **meta)

    def error(self, scope: str, message: str, exc: BaseException | None = None, **meta: Any) -> Event:
        if exc is not None:
            meta.setdefault("type", type(exc).__name__)
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            meta.setdefault("traceback", tb[-1800:])
        return self.record("error", scope, message, **meta)

    # ── reading ────────────────────────────────────────────────────────────
    def events(
        self,
        *,
        since: int = 0,
        limit: int = 120,
        levels: Iterable[str] | None = None,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        wanted = {level.lower() for level in levels} if levels else None
        minimum = min((_SEVERITY[level] for level in wanted), default=0) if wanted else 0
        with self._lock:
            snapshot = list(self._events)
        picked: list[Event] = []
        for event in reversed(snapshot):
            if since and event.seq <= since:
                break
            if scope and event.scope != scope:
                continue
            if wanted and event.level not in wanted and _SEVERITY[event.level] < minimum:
                continue
            picked.append(event)
            if len(picked) >= limit:
                break
        return [event.to_dict() for event in reversed(picked)]

    def tail(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.events(limit=limit)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            counts = dict(self._counts)
            total = len(self._events)
            seq = self._seq
        return {
            "seq": seq,
            "buffered": total,
            "counts": counts,
            "errors": counts.get("error", 0),
            "warnings": counts.get("warn", 0),
            "uptime": max(0.0, time.time() - self.started_at),
            "file": str(self.path) if self.path else "",
        }

    def clear(self) -> int:
        with self._lock:
            removed = len(self._events)
            self._events.clear()
        self.info("journal", f"journal cleared ({removed} events dropped)")
        return removed

    def export(self) -> Path | None:
        """Write the whole ring buffer to a temp file for `/logs export`."""
        if self.path is None:
            return None
        with self._lock:
            snapshot = list(self._events)
        target = self.path.with_name(f"journal-export-{int(time.time())}.jsonl")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as handle:
                for event in snapshot:
                    handle.write(json.dumps(event.to_dict(), ensure_ascii=False, default=str) + "\n")
        except OSError:
            return None
        return target

    # ── logging bridge ─────────────────────────────────────────────────────
    def install(self, level: int = logging.INFO) -> None:
        """Capture every logger (ours, pyrogram, tgcalls, aiohttp) into the journal."""
        if self._handler is not None:
            return
        journal = self

        class _Sink(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - logging glue
                try:
                    if record.name == "vyron.core.journal":
                        return
                    if record.levelno >= logging.ERROR:
                        level_name = "error"
                    elif record.levelno >= logging.WARNING:
                        level_name = "warn"
                    else:
                        level_name = "info"
                    message = record.getMessage()
                    if record.exc_info:
                        exc = record.exc_info[1]
                        journal.error(
                            _scope_for(record.name),
                            message,
                            exc if isinstance(exc, BaseException) else None,
                        )
                    else:
                        journal.record(level_name, _scope_for(record.name), message)
                except Exception:  # never let logging raise
                    pass

        handler = _Sink()
        handler.setLevel(level)
        root = logging.getLogger()
        root.addHandler(handler)
        self._handler = handler
        self.installed = True

    def uninstall(self) -> None:
        if self._handler is None:
            return
        try:
            logging.getLogger().removeHandler(self._handler)
        finally:
            self._handler = None
            self.installed = False

    # ── lifecycle helpers ──────────────────────────────────────────────────
    def boot(self, *, version: str, storage: str, streaming: bool, handlers: int = 0) -> None:
        self.info(
            "boot",
            f"VYRON {version} online",
            python=platform.python_version(),
            platform=f"{platform.system()} {platform.release()}",
            storage=storage,
            streaming=streaming,
            handlers=handlers,
            pid=__import__("os").getpid(),
            argv=" ".join(sys.argv[:3]),
        )

    def shutdown(self, reason: str = "signal") -> None:
        self.info("boot", f"shutting down ({reason})", uptime=round(self.stats()["uptime"], 1))


# The process-wide journal. `main.py` points it at `data/journal.jsonl`.
journal = Journal()


def attach(path: Path | None) -> Journal:
    """Point the shared journal at *path* and start capturing loggers."""
    journal.path = path
    journal.started_at = time.time()
    journal.install()
    return journal


__all__ = ["Event", "Journal", "LEVELS", "attach", "journal"]
