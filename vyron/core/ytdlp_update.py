# ---------------------------------------------------------------------------
#  VYRON — keep yt-dlp fresh
# ---------------------------------------------------------------------------
# YouTube changes its player several times a month, and every change breaks
# older extractors first. A deployment that pinned yt-dlp on day one starts
# answering "Nothing could be extracted from that link" a few weeks later — with
# no config change and no crash, which is the worst kind of outage.
#
# So: ask PyPI for the current version, compare it with the installed one, and —
# if YTDLP_AUTOUPDATE is on and we are actually allowed to write to the
# environment (a container, a VPS, not a locked-down lambda) — upgrade it in a
# worker thread. The new extractor is used by the next resolve, because yt-dlp
# imports the module lazily per download.
#
# Everything here is best-effort: a failed check, a failed install or no
# internet at all leaves the deployment exactly as it was, one warning richer.
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
import urllib.request

from vyron.config import settings

logger = logging.getLogger(__name__)

PYPI_URL = "https://pypi.org/pypi/yt-dlp/json"
_state: dict[str, object] = {
    "installed": "",
    "latest": "",
    "checked": 0.0,
    "updated": 0.0,
    "error": "",
    "running": False,
}
_lock = threading.Lock()


# ── version helpers ────────────────────────────────────────────────────────
def installed_version() -> str:
    try:
        import yt_dlp.version

        return str(yt_dlp.version.__version__)
    except Exception:  # pragma: no cover - packaging problem
        return ""


def _parts(version: str) -> tuple[int, ...]:
    """`2026.10.21` → a comparable tuple; suffixes like `.1` are kept."""
    out: list[int] = []
    for chunk in (version or "").split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(candidate: str, current: str) -> bool:
    return bool(candidate) and bool(current) and _parts(candidate) > _parts(current)


def latest_version(timeout: float = 8.0) -> str:
    """The newest release on PyPI, or ``""`` when the network says no."""
    try:
        request = urllib.request.Request(
            PYPI_URL, headers={"User-Agent": "VYRON (yt-dlp version check)"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
        return str(payload.get("info", {}).get("version") or "")
    except Exception as exc:
        logger.debug("yt-dlp version check failed: %s", exc)
        return ""


def should_update(*, autoupdate: bool | None = None) -> bool:
    """Only containers/VPSes: a read-only filesystem must not try to pip."""
    enabled = settings.ytdlp_autoupdate if autoupdate is None else autoupdate
    if not enabled:
        return False
    try:
        import os

        return os.access(sys.prefix, os.W_OK)
    except Exception:  # pragma: no cover - exotic filesystem
        return False


def upgrade(timeout: float = 300.0) -> tuple[bool, str]:
    """`pip install -U yt-dlp` in a child process. Returns (ok, message)."""
    command = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-U", "yt-dlp"]
    try:
        # A fixed argv with no shell: nothing here comes from a message.
        result = subprocess.run(  # noqa: S603
            command, capture_output=True, timeout=timeout, text=True, check=False
        )
    except Exception as exc:  # pragma: no cover - pip missing / no permission
        return False, f"{type(exc).__name__}: {exc}"
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()[-3:]
        return False, " · ".join(tail)[:300]
    return True, "installed"


def check(update: bool | None = None) -> dict:
    """One version check (and, optionally, the upgrade). Never raises."""
    from vyron.core.journal import journal

    with _lock:
        if _state["running"]:
            return dict(_state)
        _state["running"] = True
    try:
        current = installed_version()
        newest = latest_version()
        _state.update(installed=current, latest=newest, checked=time.time(), error="")
        if not newest:
            _state["error"] = "PyPI did not answer"
            return dict(_state)
        if not is_newer(newest, current):
            return dict(_state)
        logger.info("yt-dlp %s is out — this deployment runs %s", newest, current)
        journal.info("engine", f"yt-dlp {newest} is available (running {current})")
        wants = should_update() if update is None else update
        if not wants:
            return dict(_state)
        ok, message = upgrade()
        if ok:
            _state.update(updated=time.time(), installed=installed_version())
            logger.info("yt-dlp upgraded to %s", _state["installed"] or newest)
            journal.ok("engine", f"yt-dlp upgraded to {_state['installed'] or newest}")
        else:
            _state["error"] = message
            logger.warning("yt-dlp upgrade failed: %s", message)
            journal.warn("engine", "yt-dlp upgrade failed", error=message)
        return dict(_state)
    except Exception as exc:  # pragma: no cover - defensive
        _state["error"] = f"{type(exc).__name__}: {exc}"
        return dict(_state)
    finally:
        with _lock:
            _state["running"] = False


def start(delay: float = 25.0) -> None:
    """Check (and maybe upgrade) shortly after boot, then once a day."""

    def _after_boot() -> None:
        time.sleep(delay)
        check()

    try:
        threading.Thread(target=_after_boot, name="ytdlp-update", daemon=True).start()
    except Exception:  # pragma: no cover - thread limits
        pass


def status() -> dict:
    """For /doctor — never exposes a proxy, cookie or token."""
    return {
        "installed": _state["installed"] or installed_version(),
        "latest": _state["latest"],
        "checked": _state["checked"],
        "updated": _state["updated"],
        "error": _state["error"],
        "autoupdate": settings.ytdlp_autoupdate,
    }


__all__ = [
    "check",
    "installed_version",
    "is_newer",
    "latest_version",
    "should_update",
    "start",
    "status",
    "upgrade",
]
