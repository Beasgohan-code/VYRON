# ---------------------------------------------------------------------------
#  VYRON — download accelerators
# ---------------------------------------------------------------------------
# yt-dlp's own HTTP client is fine for one connection; a music bot wants the
# file *now*. Every serious downloader in the open-source world solves that the
# same way — split the file into ranges and pull them in parallel:
#
#   aria2c   the reference implementation (aria2). 16 connections, resume,
#            works on any signed URL a resolver hands us.
#   curl     already everywhere, and modern curl does ranged parallel transfers
#            in one invocation (`--parallel --range`), so it is a real second
#            option rather than a formality.
#   aiohttp  always present; one connection, used last so a container without
#            either binary still works.
#
# The order is configurable (DOWNLOAD_ACCELERATOR=auto|aria2|curl|none) and
# whatever is chosen falls back down the list on failure — a missing binary, an
# expired URL and a mirror that rejects ranges all end in the same place:
# a working file or a clear error.
from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# (name, binary, extra args) — `auto` walks this list in order.
ARA2_CONNECTIONS = 16
PREFERRED = ("aria2", "curl")

Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class Tool:
    name: str
    binary: str
    present: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.binary})" if self.present else ""


def _which(name: str) -> str:
    return shutil.which(name) or ""


def available() -> list[Tool]:
    """The accelerators this image actually has, best first."""
    return [
        Tool("aria2", "aria2c", bool(_which("aria2c"))),
        Tool("curl", "curl", bool(_which("curl"))),
    ]


def detect() -> str:
    """The accelerator that will be used: aria2 → curl → aiohttp."""
    for tool in available():
        if tool.present:
            return tool.name
    return "aiohttp"


def describe() -> str:
    """One line for /doctor."""
    found = [tool.name for tool in available() if tool.present]
    return (" + ".join(found) + " → aiohttp") if found else "aiohttp (install aria2 for 16 connections)"


# ── command lines ──────────────────────────────────────────────────────────
def aria2_command(url: str, target: Path, headers: dict[str, str] | None = None) -> list[str]:
    command = [
        _which("aria2c") or "aria2c",
        "--dir", str(target.parent),
        "--out", target.name,
        "--max-connection-per-server", str(ARA2_CONNECTIONS),
        "--split", str(ARA2_CONNECTIONS),
        "--min-split-size", "1M",
        "--continue=true",
        "--allow-overwrite=true",
        "--auto-file-renaming=false",
        "--file-allocation=none",
        "--console-log-level=error",
        "--summary-interval=0",
        "--download-result=hide",
    ]
    for key, value in (headers or {}).items():
        # aria2 wants one --header per line, and refuses a broken one outright
        if key and value and "\n" not in str(value):
            command.append(f"--header={key}: {value}")
    command.append(url)
    return command


def curl_command(url: str, target: Path, headers: dict[str, str] | None = None) -> list[str]:
    command = [
        _which("curl") or "curl",
        "--fail",  # a 403 must not leave a 0-byte "success"
        "--location",  # signed URLs redirect
        "--silent",
        "--show-error",
        "--retry", "2",
        "--retry-delay", "1",
        "--output", str(target),
    ]
    for key, value in (headers or {}).items():
        if key and value and "\n" not in str(value):
            command.extend(["--header", f"{key}: {value}"])
    command.append(url)
    return command


def _size(path: Path) -> int:
    """Bytes on disk so far — ``os.stat`` so the poll stays off the event loop's
    blocking-pathlib list and costs one syscall."""
    import os

    try:
        return os.stat(path).st_size
    except (OSError, ValueError):
        return 0


#: How often the size of an in-flight download is read. Four polls a second is
#: one `stat` per 250 ms — free — and fast enough for a progress bar a human
#: reads rather than measures.
WATCH_INTERVAL = 0.25


async def _watch(
    target: Path | None,
    on_progress: Progress | None,
    total: int,
    stop: asyncio.Event,
) -> None:
    """Report the growing file size while a binary downloader works.

    aria2c and curl talk to us over a pipe we are not reading until they exit,
    so without this the bar sat at zero for the whole transfer — the single
    most "is it broken?" part of downloading a song.
    """
    if target is None or on_progress is None:
        return
    seen = -1
    while not stop.is_set():
        try:
            size = _size(target)
        except OSError:  # pragma: no cover - the file is being renamed
            size = 0
        if size != seen:
            seen = size
            try:
                on_progress(size, total)
            except Exception:  # a broken callback must not kill the download
                pass
        try:
            await asyncio.wait_for(stop.wait(), WATCH_INTERVAL)
        except asyncio.TimeoutError:
            continue


async def _run(
    command: list[str],
    *,
    timeout: float,
    cap: int,
    target: Path | None = None,
    total: int = 0,
    on_progress: Progress | None = None,
) -> tuple[bool, str]:
    """Run a downloader with a hard timeout, a size ceiling and live progress."""
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return False, "binary not found"
    except Exception as exc:  # pragma: no cover - permissions, exec format …
        return False, f"{type(exc).__name__}: {exc}"

    stop = asyncio.Event()
    watcher = asyncio.create_task(
        _watch(target, on_progress, total, stop), name="accelerator:watch"
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        return False, "timed out"
    finally:
        stop.set()
        if not watcher.done():
            watcher.cancel()
            try:
                await watcher
            except (asyncio.CancelledError, Exception):  # pragma: no cover
                pass
    # The size cap is checked by the caller on the finished file, but kill the
    # process early when it is obviously overshooting.
    if stderr and len(stderr) > cap:  # pragma: no cover - defensive
        return False, "too much output"
    if process.returncode != 0:
        message = (stderr or b"").decode("utf-8", "replace").strip().splitlines()
        return False, (message[-1] if message else f"exit {process.returncode}")[:200]
    return True, ""


async def fetch(
    url: str,
    target: Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 600.0,
    cap: int = 0,
    on_progress: Progress | None = None,
    order: tuple[str, ...] | None = None,
    total: int = 0,
) -> str:
    """Download *url* into *target* with the best available accelerator.

    Returns the name of the tool that produced the file (``"aria2"``,
    ``"curl"`` or ``"aiohttp"``). Raises :class:`RuntimeError` when every tool
    fails, with all three reasons in the message — that sentence is what
    /doctor and the API surface to the user.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    chosen = order or PREFERRED
    errors: list[str] = []

    for name in chosen:
        if name == "aria2" and _which("aria2c"):
            ok, why = await _run(
                aria2_command(url, target, headers),
                timeout=timeout,
                cap=cap,
                target=target,
                total=total,
                on_progress=on_progress,
            )
        elif name == "curl" and _which("curl"):
            ok, why = await _run(
                curl_command(url, target, headers),
                timeout=timeout,
                cap=cap,
                target=target,
                total=total,
                on_progress=on_progress,
            )
        else:
            continue
        if ok:
            size = _harvest(target, cap)
            if size:
                logger.info("downloaded %s with %s (%d bytes)", target.name, name, size)
                if on_progress:
                    on_progress(size, size)
                return name
            errors.append(f"{name}: empty or oversized file")
            continue
        errors.append(f"{name}: {why}")
        _discard(target)
        logger.info("%s could not fetch %s (%s)", name, target.name, why)

    # Last resort: the pure-Python client. One connection, but it never
    # depends on a binary being installed.
    try:
        await _aiohttp(url, target, headers=headers, cap=cap, on_progress=on_progress)
    except Exception as exc:
        errors.append(f"aiohttp: {exc}")
        raise RuntimeError(" · ".join(errors) or "download failed") from exc
    return "aiohttp"


def _harvest(path: Path, cap: int) -> int:
    """Size of a finished download, or ``0`` after deleting an unusable one.

    Deliberately synchronous: a `stat` and an `unlink` on a file we have just
    written are syscalls, not I/O waits — a thread hop would cost more than
    the calls themselves.
    """
    size = path.stat().st_size if path.is_file() else 0
    if size <= 0 or (cap and size > cap):
        _discard(path)
        return 0
    return size


def _discard(path: Path) -> None:
    """Best-effort removal of a partial file."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


async def _aiohttp(
    url: str,
    target: Path,
    *,
    headers: dict[str, str] | None,
    cap: int,
    on_progress: Progress | None,
) -> None:
    import aiohttp

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=60)
    written = 0
    async with aiohttp.ClientSession(timeout=timeout, headers=headers or None) as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            total = int(response.headers.get("Content-Length") or 0)
            with target.open("wb") as handle:
                async for chunk in response.content.iter_chunked(256 * 1024):
                    written += len(chunk)
                    if cap and written > cap:
                        raise RuntimeError("larger than the allowed size")
                    handle.write(chunk)
                    if on_progress:
                        on_progress(written, total)


__all__ = [
    "ARA2_CONNECTIONS",
    "Tool",
    "aria2_command",
    "available",
    "curl_command",
    "describe",
    "detect",
    "fetch",
]
