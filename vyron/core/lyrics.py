# ---------------------------------------------------------------------------
#  VYRON — lyrics lookup (LRCLIB, free & no API key required)
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)

LRCLIB_SEARCH = "https://lrclib.net/api/search"
LRCLIB_GET = "https://lrclib.net/api/get"
_UA = {"User-Agent": "VYRON-Music-Bot/1.0 (+https://github.com/Beasgohan-code/VYRON)"}


@dataclass
class LyricsResult:
    title: str
    artist: str
    plain: str
    synced: str | None = None
    album: str | None = None
    source: str = "LRCLIB"

    @property
    def has_sync(self) -> bool:
        return bool(self.synced)

    def as_text(self, max_chars: int = 3200) -> str:
        body = self.synced or self.plain or ""
        body = body.replace("\r\n", "\n").strip()
        if len(body) > max_chars:
            body = body[:max_chars].rsplit("\n", 1)[0] + "\n…"
        return body


_LRC_TAG = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")


def parse_lrc(text: str | None) -> list[dict]:
    """``[01:23.45] line`` → ``[{"time": 83.45, "text": "line"}]`` (sorted)."""
    if not text:
        return []
    lines: list[dict] = []
    for raw in str(text).replace("\r\n", "\n").split("\n"):
        matches = list(_LRC_TAG.finditer(raw))
        if not matches:
            continue
        body = raw[matches[-1].end():].strip()
        if not body:
            continue
        for match in matches:
            minutes, seconds, fraction = match.groups()
            millis = int((fraction or "0").ljust(3, "0")[:3])
            stamp = int(minutes) * 60 + int(seconds) + millis / 1000
            lines.append({"time": round(stamp, 2), "text": body})
    lines.sort(key=lambda item: item["time"])
    return lines


class LyricsClient:
    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session
        self._owns_session = session is None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=12), headers=_UA
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session and self._owns_session and not self._session.closed:
            await self._session.close()

    async def find(self, title: str, artist: str = "") -> LyricsResult | None:
        query = {"track_name": title}
        if artist:
            query["artist_name"] = artist
        session = await self._get_session()
        try:
            async with session.get(LRCLIB_SEARCH, params=query) as response:
                if response.status != 200:
                    logger.debug("lyrics search HTTP %s", response.status)
                    return None
                payload = await response.json(content_type=None)
        except Exception as exc:
            logger.debug("lyrics lookup failed: %s", exc)
            return None

        if isinstance(payload, dict):
            payload = [payload]
        if not payload:
            return None

        best = payload[0]
        for entry in payload:
            if entry.get("syncedLyrics"):
                best = entry
                break

        return LyricsResult(
            title=str(best.get("trackName") or title),
            artist=str(best.get("artistName") or artist),
            plain=str(best.get("plainLyrics") or ""),
            synced=best.get("syncedLyrics"),
            album=best.get("albumName"),
        )

    async def timed(self, title: str, artist: str, duration: int) -> LyricsResult | None:
        if not duration:
            return await self.find(title, artist)
        session = await self._get_session()
        params = {
            "track_name": title,
            "artist_name": artist or "",
            "duration": str(int(duration)),
        }
        try:
            async with session.get(LRCLIB_GET, params=params) as response:
                if response.status != 200:
                    return await self.find(title, artist)
                best = await response.json(content_type=None)
        except Exception:
            return await self.find(title, artist)
        return LyricsResult(
            title=str(best.get("trackName") or title),
            artist=str(best.get("artistName") or artist),
            plain=str(best.get("plainLyrics") or ""),
            synced=best.get("syncedLyrics"),
            album=best.get("albumName"),
        )


def split_title(text: str) -> tuple[str, str]:
    """Split ``Artist - Title`` into its parts (best effort)."""
    cleaned = (text or "").strip()
    for sep in (" - ", " – ", " — ", " | "):
        if sep in cleaned:
            left, right = cleaned.split(sep, 1)
            return right.strip(), left.strip()
    return cleaned, ""


__all__ = ["LyricsClient", "LyricsResult", "split_title"]
