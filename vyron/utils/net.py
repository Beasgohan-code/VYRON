# ---------------------------------------------------------------------------
#  VYRON — the shared HTTP session (thumbnails, catalogue JSON, health)
#
#  Every small call used to open its own `ClientSession`: a TCP+TLS handshake
#  per lookup, per lane, per keystroke in the Mini App's search box. On a cold
#  datacenter host that handshake is most of a second, and when three catalogue
#  lanes are asked at once it is three handshakes — which is how a "0.4 s
#  JioSaavn answer" turned into a 7-second search that timed out before the
#  socket was even warm.
#
#  One keep-alive session, one DNS cache, one connector. Everything that fetches
#  a JSON document or a small picture goes through it.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; VYRON/1.0)"
_MAX_THUMB = 280 * 1024

#: How long a single request may take when the caller does not say. A connect
#: timeout shorter than the total is what keeps a black-holed host from eating
#: the whole budget.
DEFAULT_TIMEOUT = 5.0
CONNECT_TIMEOUT = 3.5

_SESSION: aiohttp.ClientSession | None = None
_LOCK: asyncio.Lock | None = None
#: The loop the session was built on. A `ClientSession` is bound to its loop, so
#: one kept across `asyncio.run`-style restarts (tests, an in-process supervisor)
#: answers with "Event loop is closed" instead of a socket.
_LOOP: asyncio.AbstractEventLoop | None = None


def _lock() -> asyncio.Lock:
    """One lock per event loop (the tests build more than one)."""
    global _LOCK
    if _LOCK is None or _LOCK.locked() and _SESSION is None:  # pragma: no cover
        _LOCK = asyncio.Lock()
    return _LOCK


async def session() -> aiohttp.ClientSession:
    """The process-wide session, created on first use (and per event loop)."""
    global _SESSION, _LOOP
    loop = asyncio.get_running_loop()
    if _SESSION is not None and not _SESSION.closed and _LOOP is loop:
        return _SESSION
    async with _lock():
        if _SESSION is not None and not _SESSION.closed and _LOOP is not loop:
            try:  # pragma: no cover - only on a loop restart
                await _SESSION.close()
            except Exception:
                pass
            _SESSION = None
        if _SESSION is None or _SESSION.closed:
            _SESSION = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(
                    total=DEFAULT_TIMEOUT + 3, connect=CONNECT_TIMEOUT
                ),
                connector=aiohttp.TCPConnector(
                    limit=48,
                    ttl_dns_cache=300,
                    enable_cleanup_closed=True,
                ),
                headers={"User-Agent": _UA},
            )
            _LOOP = loop
    return _SESSION


async def close() -> None:
    """Close the shared session (shutdown, and between tests)."""
    global _SESSION, _LOOP
    current, _SESSION = _SESSION, None
    _LOOP = None
    if current is not None and not current.closed:
        try:
            await current.close()
        except Exception as exc:  # pragma: no cover - nothing to do at shutdown
            logger.debug("closing the shared http session failed: %s", exc)


def _timeout(seconds: float | None) -> aiohttp.ClientTimeout:
    total = float(seconds or DEFAULT_TIMEOUT)
    return aiohttp.ClientTimeout(total=total, connect=min(CONNECT_TIMEOUT, total))


async def get_json(
    url: str | None,
    *,
    timeout: float | None = None,
    headers: dict | None = None,
):
    """GET a JSON document. Returns a dict/list, or ``None``. Never raises."""
    if not url:
        return None
    try:
        client = await session()
        async with client.get(url, headers=headers, timeout=_timeout(timeout)) as response:
            if response.status != 200:
                logger.debug("%s → HTTP %s", url, response.status)
                return None
            payload = await response.json(content_type=None)
            return payload if isinstance(payload, (dict, list)) else None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("%s failed: %s", url, exc)
        return None


async def post_json(
    url: str | None,
    body: dict,
    *,
    timeout: float | None = None,
    headers: dict | None = None,
):
    """POST a JSON body and read a JSON answer. Never raises."""
    if not url:
        return None
    merged = {"Accept": "application/json", "Content-Type": "application/json"}
    merged.update(headers or {})
    try:
        client = await session()
        async with client.post(url, json=body, headers=merged, timeout=_timeout(timeout)) as response:
            if response.status not in (200, 201):
                logger.debug("%s → HTTP %s", url, response.status)
                return None
            payload = await response.json(content_type=None)
            return payload if isinstance(payload, (dict, list)) else None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("%s failed: %s", url, exc)
        return None


async def fetch_bytes(
    url: str | None,
    *,
    limit: int = _MAX_THUMB,
    timeout: float | None = None,
    follow_redirects: bool = True,
) -> bytes | None:
    """Fetch a small remote asset (covers, avatars). Never raises."""
    if not url:
        return None
    try:
        client = await session()
        async with client.get(
            url,
            timeout=_timeout(timeout),
            allow_redirects=follow_redirects,
        ) as response:
            if response.status != 200:
                return None
            data = await response.content.read(limit + 1)
            return data if len(data) <= limit else None
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("thumb fetch failed: %s", exc)
        return None


async def get_text(
    url: str | None,
    *,
    timeout: float | None = None,
    headers: dict | None = None,
    follow_redirects: bool = True,
) -> str | None:
    """GET a page's text. Never raises; a non-200 is ``None``."""
    if not url:
        return None
    try:
        client = await session()
        async with client.get(
            url,
            headers=headers,
            timeout=_timeout(timeout),
            allow_redirects=follow_redirects,
        ) as response:
            if response.status != 200:
                logger.debug("%s → HTTP %s", url, response.status)
                return None
            return await response.text(errors="replace")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("%s failed: %s", url, exc)
        return None


def as_file(data: bytes | None, name: str = "cover.jpg"):
    """Bytes → a *binary* file pointer Telegram will accept.

    The client's upload path only takes a path or an ``io.IOBase``; raw
    ``bytes`` raises "Invalid file. Expected a file path as string or a binary
    (not text) file pointer" — which is exactly how `/song` lost the *whole*
    file whenever the cover had downloaded: the artwork took the upload down
    with it.
    """
    if not data:
        return None
    import io as _io

    if isinstance(data, (bytes, bytearray)):
        pointer = _io.BytesIO(bytes(data))
        pointer.name = name          # type: ignore[attr-defined]
        return pointer
    return data


async def probe(
    url: str | None,
    *,
    timeout: float | None = None,
    headers: dict | None = None,
) -> tuple[int, str]:
    """``(status, final_url)`` for a URL, having fetched at most one byte.

    Used to *test* a mirror's media endpoint before handing the URL to a
    player: a `302` to a real CDN is proof the instance still serves audio,
    while a `404`/"Video unavailable" page is what a listener would have seen.
    The request is a one-byte ranged GET, so a 40 MB file costs a header.
    """
    if not url:
        return 0, ""
    merged = dict(headers or {})
    merged.setdefault("Range", "bytes=0-0")
    try:
        client = await session()
        async with client.get(url, headers=merged, timeout=_timeout(timeout)) as response:
            return response.status, str(response.url)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("probe %s failed: %s", url, exc)
        return 0, ""


__all__ = [
    "as_file",
    "close",
    "fetch_bytes",
    "get_json",
    "get_text",
    "post_json",
    "probe",
    "session",
]
