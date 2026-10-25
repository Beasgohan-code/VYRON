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
#   ranged   the same idea as aria2, in Python: ask the server for N ranges of
#            the file and pull them *at once* over the shared keep-alive session.
#            This is the tier that matters on a container with no aria2c (most
#            of them) — one connection to a CDN is throttled per connection, so
#            six ranges is three to six times the bytes per second for the same
#            URL, and it needs no binary at all.
#   aiohttp  one connection, used last so a container without anything else
#            still works.
#
# The order is configurable (DOWNLOAD_ACCELERATOR=auto|aria2|curl|none) and
# whatever is chosen falls back down the list on failure — a missing binary, an
# expired URL and a mirror that rejects ranges all end in the same place:
# a working file or a clear error.
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# (name, binary, extra args) — `auto` walks this list in order.
ARA2_CONNECTIONS = 16
#: How many ranges the Python accelerator pulls at once. Six is the point where
#: a per-connection throttle stops being the limit and the CDN's own bandwidth
#: is; more connections mostly buys failed handshakes on a signed URL.
RANGE_CONNECTIONS = 6
#: Below this a range split costs more in handshakes than it saves: a 900 KB
#: m4a arrives in one go long before six requests have been set up.
RANGE_MIN_BYTES = 1_500_000
#: Smallest slice worth its own connection.
RANGE_MIN_CHUNK = 512 * 1024
PREFERRED = ("aria2", "ranged", "curl")

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
    """The *binary* accelerator that will be used: aria2 → curl → aiohttp.

    Kept to those three names deliberately: it is a public health field
    (`/health`, /doctor) and callers switch on it. The Python range splitter is
    always there underneath, which is why "aiohttp" here means "no binary, but
    still six connections".
    """
    for tool in available():
        if tool.present:
            return tool.name
    return "aiohttp"


def describe() -> str:
    """One line for /doctor."""
    found = [tool.name for tool in available() if tool.present]
    tail = f"{RANGE_CONNECTIONS} ranges → 1 connection"
    return " + ".join(found) + " → " + tail if found else f"no binary · {tail} (install aria2 for 16)"


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


# ── the Python accelerator: N ranges, one session ──────────────────────────
_CONTENT_RANGE = re.compile(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", re.I)


class RangeUnsupported(RuntimeError):
    """The server ignored a Range header — fall back to one connection."""


async def _probe(url: str, headers: dict[str, str] | None) -> tuple[int, bool]:
    """Ask the URL how big it is, and whether it honours ranges.

    One byte is requested, not the file: `Range: bytes=0-0` answers 206 with a
    `Content-Range: bytes 0-0/12345`, which gives both facts for the price of a
    header round-trip. Servers that answer 200 instead have simply ignored the
    range, and the `Content-Length` is still the size.
    """
    from vyron.utils import net

    client = await net.session()
    merged = dict(headers or {})
    merged["Range"] = "bytes=0-0"
    async with client.get(url, headers=merged) as response:
        if response.status == 206:
            match = _CONTENT_RANGE.search(response.headers.get("Content-Range", ""))
            size = int(match.group(3)) if match and match.group(3).isdigit() else 0
            return size, True
        if response.status == 200:
            return int(response.headers.get("Content-Length") or 0), False
        if response.status in (401, 403, 404, 410):
            raise RuntimeError(f"HTTP {response.status}")
        raise RangeUnsupported(f"HTTP {response.status}")


def plan_ranges(size: int, connections: int = RANGE_CONNECTIONS) -> list[tuple[int, int]]:
    """Inclusive byte ranges covering *size*, spread over a few connections."""
    if size <= 0:
        return [(0, -1)]
    count = max(1, min(connections, size // RANGE_MIN_CHUNK or 1))
    step = size // count
    ranges: list[tuple[int, int]] = []
    for index in range(count):
        start = index * step
        end = size - 1 if index == count - 1 else (index + 1) * step - 1
        ranges.append((start, end))
    return ranges


async def _part(
    url: str,
    headers: dict[str, str] | None,
    start: int,
    end: int,
    path: Path,
) -> int:
    """One range, written straight to disk as it arrives."""
    from vyron.utils import net

    client = await net.session()
    merged = dict(headers or {})
    if end >= start:
        merged["Range"] = f"bytes={start}-{end}"
    async with client.get(url, headers=merged) as response:
        if response.status == 200 and end >= start:
            # It ignored the range and is sending the whole file.
            raise RangeUnsupported("range ignored")
        if response.status not in (200, 206):
            raise RuntimeError(f"HTTP {response.status}")
        written = 0
        with path.open("wb") as handle:
            async for chunk in response.content.iter_chunked(256 * 1024):
                handle.write(chunk)
                written += len(chunk)
    return written


async def ranged_fetch(
    url: str,
    target: Path,
    *,
    headers: dict[str, str] | None = None,
    cap: int = 0,
    total: int = 0,
    on_progress: Progress | None = None,
    connections: int = RANGE_CONNECTIONS,
) -> int:
    """Pull *url* over several connections at once. Raises on failure only.

    A CDN that throttles a connection to 200 KB/s serves 1.2 MB/s to six of
    them, which is the difference between a four-minute song landing in twenty
    seconds and in three. If the server will not range, or anything at all goes
    wrong, the caller falls back to one connection — this is an accelerator,
    never a requirement.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    size, ranged = await _probe(url, headers)
    if not ranged or size < RANGE_MIN_BYTES:
        raise RangeUnsupported("server does not range this file")
    if cap and size > cap:
        raise RuntimeError("larger than the allowed size")

    pieces = plan_ranges(size, connections)
    parts = [target.with_name(f"{target.name}.part{index}") for index in range(len(pieces))]
    for part in parts:
        with contextlib.suppress(OSError):
            part.unlink()
    stop = asyncio.Event()
    watcher = asyncio.create_task(
        _watch_many(parts, on_progress, total or size, stop), name="accelerator:ranges"
    )
    try:
        tasks = [
            asyncio.create_task(_part(url, headers, start, end, part), name=f"range:{index}")
            for index, ((start, end), part) in enumerate(zip(pieces, parts, strict=True))
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            for task in done:
                error = task.exception()
                if error is not None:
                    raise error
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
    finally:
        stop.set()
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await watcher

    payload = sum(part.stat().st_size for part in parts if part.is_file())
    if payload != size:
        for part in parts:
            with contextlib.suppress(OSError):
                part.unlink()
        raise RuntimeError(f"ranges gave {payload} of {size} bytes")

    with target.open("wb") as out:
        for part in parts:
            with part.open("rb") as handle:
                shutil.copyfileobj(handle, out, 1024 * 1024)
    for part in parts:
        with contextlib.suppress(OSError):
            part.unlink()
    if on_progress:
        on_progress(size, size)
    return size


async def _watch_many(
    parts: list[Path],
    on_progress: Progress | None,
    total: int,
    stop: asyncio.Event,
) -> None:
    """Report the summed size of the ranges in flight."""
    if on_progress is None:
        return
    seen = -1
    while not stop.is_set():
        size = sum(_size(part) for part in parts)
        if size != seen:
            seen = size
            with contextlib.suppress(Exception):
                on_progress(size, total)
        try:
            await asyncio.wait_for(stop.wait(), WATCH_INTERVAL)
        except asyncio.TimeoutError:
            continue


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
        elif name == "ranged":
            try:
                await asyncio.wait_for(
                    ranged_fetch(
                        url,
                        target,
                        headers=headers,
                        cap=cap,
                        total=total,
                        on_progress=on_progress,
                    ),
                    timeout=timeout,
                )
            except Exception as exc:
                ok, why = False, f"{type(exc).__name__}: {exc}"[:200]
            else:
                ok, why = True, ""
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

    # Last resort: ranges in Python, then one connection. Neither needs a
    # binary, and the first is several times faster when the URL allows ranges.
    try:
        await asyncio.wait_for(
            ranged_fetch(
                url, target, headers=headers, cap=cap, total=total, on_progress=on_progress
            ),
            timeout=timeout,
        )
        logger.info("downloaded %s with %d ranges", target.name, RANGE_CONNECTIONS)
        return "ranged"
    except Exception as exc:
        _discard(target)  # unlink(missing_ok=True): no stat round-trip
        logger.info("ranged fetch could not get %s (%s) — one connection", target.name, exc)
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
    "RANGE_CONNECTIONS",
    "RangeUnsupported",
    "plan_ranges",
    "ranged_fetch",
    "Tool",
    "aria2_command",
    "available",
    "curl_command",
    "describe",
    "detect",
    "fetch",
]
