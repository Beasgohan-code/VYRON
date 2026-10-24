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


__all__ = ["fetch_bytes"]
