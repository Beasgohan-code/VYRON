# ---------------------------------------------------------------------------
#  VYRON — one instance per deployment
# ---------------------------------------------------------------------------
# Player state lives in this process, and a voice chat can only have one
# streamer. Deploys on Render/Koyeb can overlap for a few seconds, and a
# mis-scaled service runs two copies permanently — both would join the same call
# and take turns fighting over it.
#
# So every process claims a short lease in the shared store:
#
#   meta["instance"] = {"id": …, "since": …, "beat": …}
#
# A process that finds a *fresh* lease belonging to somebody else is a standby:
# it serves HTTP, answers /health, and refuses to resume 24/7 playback or start
# streams on its own. A stale lease is taken over, which is what makes a crashed
# instance recover without manual intervention.
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import socket
import time

logger = logging.getLogger(__name__)

META_KEY = "instance"
LEASE_SECONDS = 90.0          # fresh enough to mean "alive"
HEARTBEAT_SECONDS = 30.0

_ME = "ins_" + secrets.token_hex(4)
_started = time.time()
_state: dict[str, object] = {"primary": True, "holder": "", "since": 0.0}


def instance_id() -> str:
    return _ME


def describe_self() -> dict[str, object]:
    return {
        "id": _ME,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "since": _started,
    }


def is_primary() -> bool:
    return bool(_state["primary"])


def status() -> dict[str, object]:
    return {
        "primary": is_primary(),
        "id": _ME,
        "holder": _state["holder"],
        "holder_since": _state["since"],
        "lease_seconds": LEASE_SECONDS,
    }


async def claim(storage=None) -> bool:
    """Try to become the primary instance. Returns True when this is it."""
    if storage is None:
        from vyron.runtime import runtime

        storage = runtime.storage
    if storage is None:
        _state.update(primary=True, holder=_ME)
        return True
    try:
        current = await storage.get_meta(META_KEY, {}) or {}
    except Exception as exc:  # pragma: no cover - storage trouble is not fatal
        logger.debug("could not read the instance lease: %s", exc)
        _state.update(primary=True, holder=_ME)
        return True

    holder = str((current or {}).get("id") or "")
    beat = float((current or {}).get("beat") or 0.0)
    fresh = bool(holder) and holder != _ME and (time.time() - beat) < LEASE_SECONDS
    if fresh:
        _state.update(primary=False, holder=holder, since=float((current or {}).get("since") or 0.0))
        logger.error(
            "another instance (%s, last beat %.0fs ago) already owns this deployment — "
            "running as standby: no 24/7 resume, no streams from here. "
            "Scale the service to one instance for voice playback.",
            holder,
            time.time() - beat,
        )
        return False

    info = {**describe_self(), "beat": time.time()}
    try:
        await storage.set_meta(META_KEY, info)
    except Exception as exc:  # pragma: no cover
        logger.debug("could not write the instance lease: %s", exc)
    _state.update(primary=True, holder=_ME, since=_started)
    return True


async def heartbeat(storage=None) -> None:
    """Keep the lease alive while this process is the primary."""
    if not is_primary():
        return
    if storage is None:
        from vyron.runtime import runtime

        storage = runtime.storage
    if storage is None:
        return
    try:
        await storage.set_meta(META_KEY, {**describe_self(), "beat": time.time()})
    except Exception as exc:  # pragma: no cover - advisory only
        logger.debug("instance heartbeat failed: %s", exc)


async def release(storage=None) -> None:
    """Give the lease back on a clean shutdown, so a redeploy starts fast."""
    if not is_primary():
        return
    if storage is None:
        from vyron.runtime import runtime

        storage = runtime.storage
    if storage is None:
        return
    try:
        await storage.set_meta(META_KEY, {"id": "", "beat": 0.0})
    except Exception:  # pragma: no cover
        pass


_task = None


async def _beat_forever() -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        await heartbeat()


def start() -> "asyncio.Task | None":
    """Keep this instance's lease fresh, once, for the life of the process."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_beat_forever())
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


__all__ = [
    "HEARTBEAT_SECONDS",
    "start",
    "stop",
    "LEASE_SECONDS",
    "claim",
    "describe_self",
    "heartbeat",
    "instance_id",
    "is_primary",
    "release",
    "status",
]
