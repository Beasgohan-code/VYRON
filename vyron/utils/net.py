# ---------------------------------------------------------------------------
#  VYRON — tiny network helpers (thumbnails, health payloads)
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

import aiohttp

logger = logging.getLogger(__name__)

_UA = {"User-Agent": "Mozilla/5.0 (compatible; VYRON/1.0)"}
_MAX_THUMB = 280 * 1024


async def fetch_bytes(url: str | None, *, limit: int = _MAX_THUMB) -> bytes | None:
    """Fetch a small remote asset (used for audio covers). Never raises."""
    if not url:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout, headers=_UA) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                data = await response.content.read(limit + 1)
                return data if len(data) <= limit else None
    except Exception as exc:
        logger.debug("thumb fetch failed: %s", exc)
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


__all__ = ["as_file", "fetch_bytes"]
