# ---------------------------------------------------------------------------
#  VYRON — discovery / charts
#
#  Feeds the web app's Home screen: trending tracks, "made for you" mixes and
#  mood shelves.  Everything is yt-dlp + a TTL cache, resolved in worker
#  threads, so the first paint never waits on YouTube.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from vyron.core.queue import Track
from vyron.core.search import MediaError, YouTube

logger = logging.getLogger(__name__)

TRENDING_URLS = (
    "https://www.youtube.com/feed/trending?bp=4gINGgt5dG1hX2NoYXJ0cw%3D%3D",
    "https://www.youtube.com/playlist?list=PL4fGSI1pDJn6O1LS0XSdF3RyO0Rq_LDeI",
)

MIXES: dict[str, dict[str, Any]] = {
    "daily": {
        "title": "Daily Mix",
        "glyph": "sun",
        "queries": ["top hits this week", "feel good songs", "popular music mix"],
    },
    "chill": {
        "title": "Chill Vibes",
        "glyph": "wave",
        "queries": ["lofi chill mix", "chill acoustic playlist", "calm evening music"],
    },
    "anime": {
        "title": "Anime Mix",
        "glyph": "star",
        "queries": ["anime opening songs", "japanese anime ost", "anime lofi mix"],
    },
    "workout": {
        "title": "Workout",
        "glyph": "bolt",
        "queries": ["workout motivation songs", "gym hype playlist", "edm workout mix"],
    },
    "focus": {
        "title": "Focus",
        "glyph": "moon",
        "queries": ["deep focus music", "study instrumental playlist", "ambient focus mix"],
    },
    "night": {
        "title": "Night Vibes",
        "glyph": "moon",
        "queries": ["late night drive songs", "night r&b playlist", "midnight chill mix"],
    },
    "party": {
        "title": "Party",
        "glyph": "fire",
        "queries": ["party anthem playlist", "dance hits 2026", "club bangers"],
    },
    "romance": {
        "title": "Romance",
        "glyph": "heart",
        "queries": ["love songs playlist", "romantic bollywood hits", "slow love songs"],
    },
}

MOODS: dict[str, str] = {
    "lofi": "lofi hip hop radio",
    "bollywood": "bollywood hits 2026",
    "kpop": "kpop hits playlist",
    "rock": "classic rock anthems",
    "edm": "edm festival mix",
    "sad": "sad songs playlist",
}


@dataclass
class Shelf:
    key: str
    title: str
    glyph: str = "note"
    tracks: list[Track] = field(default_factory=list)
    kind: str = "chart"  # chart | mix | mood


class Charts:
    """TTL-cached discovery service."""

    def __init__(self, youtube: YouTube, *, ttl: int = 1800, country: str = "ZZ") -> None:
        self.youtube = youtube
        self.country = (country or "ZZ").upper()[:2]
        self.ttl = ttl
        self.home_ttl = 180  # seconds a built Home payload stays fresh
        self.shelf_timeout = 12  # a shelf that is slower than this is skipped
        self._cache: dict[str, tuple[float, list[Track]]] = {}
        # Home is expensive (a playlist read + several searches). One payload
        # per few minutes is plenty, and a stale one beats a spinner.
        self._home_cache: tuple[float, dict[str, Any]] | None = None
        self._home_lock = asyncio.Lock()
        self._prime_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ── cache plumbing ─────────────────────────────────────────────────────
    def _fresh(self, key: str) -> list[Track] | None:
        entry = self._cache.get(key)
        if not entry:
            return None
        stamp, tracks = entry
        if time.time() - stamp > self.ttl or not tracks:
            return None
        return tracks

    def _store(self, key: str, tracks: list[Track]) -> list[Track]:
        if tracks:
            self._cache[key] = (time.time(), tracks)
        return tracks

    async def _search(self, query: str, limit: int) -> list[Track]:
        try:
            return await self.youtube.search(query, limit=limit)
        except MediaError:
            return []
        except Exception as exc:  # pragma: no cover - network variance
            logger.debug("chart search failed (%s): %s", query, exc)
            return []

    # ── public shelves ─────────────────────────────────────────────────────
    async def trending(self, limit: int = 12) -> list[Track]:
        cached = self._fresh("trending")
        if cached:
            return cached[:limit]

        async with self._lock:
            cached = self._fresh("trending")
            if cached:
                return cached[:limit]

            # An editorial chart beats a guess, and it arrives with artist,
            # album and cover art already attached. Only falls through when
            # ytmusicapi is missing or YouTube Music says no.
            tracks = await self._chart_tracks(limit)
            if not tracks:
                for url in TRENDING_URLS:
                    try:
                        _, found = await self.youtube.playlist(url, limit=limit)
                        if found:
                            tracks = found
                            break
                    except Exception as exc:
                        logger.debug("trending url failed: %s", exc)

            if not tracks:
                # graceful fallback: popular searches across genres
                picks = random.sample(list(MOODS.values()), k=3)
                results = await asyncio.gather(*(self._search(q, 5) for q in picks))
                seen: set[str] = set()
                for batch in results:
                    for track in batch:
                        if track.id not in seen:
                            seen.add(track.id)
                            tracks.append(track)

            return self._store("trending", tracks)[:limit]

    async def _chart_tracks(self, limit: int) -> list[Track]:
        from vyron.core import ytmusic

        if not ytmusic.available():
            return []
        try:
            raw = await ytmusic.chart_tracks(self.country, limit=limit)
        except Exception as exc:  # pragma: no cover - network dependent
            logger.debug("ytmusic chart failed: %s", exc)
            return []
        tracks: list[Track] = []
        for entry in raw:
            try:
                tracks.append(
                    Track(
                        id=str(entry["id"]),
                        title=str(entry.get("title") or "Unknown title"),
                        uploader=str(entry.get("uploader") or ""),
                        duration=int(entry.get("duration") or 0),
                        url=f"https://www.youtube.com/watch?v={entry['id']}",
                        thumbnail=entry.get("thumbnail"),
                    )
                )
            except Exception:  # pragma: no cover - malformed row
                continue
        if tracks:
            logger.info("trending from the %s chart (%d tracks)", self.country, len(tracks))
        return tracks[:limit]

    async def mix(self, key: str, limit: int = 10) -> list[Track]:
        spec = MIXES.get(key)
        if not spec:
            return []
        cache_key = f"mix:{key}"
        cached = self._fresh(cache_key)
        if cached:
            return cached[:limit]

        results = await asyncio.gather(*(self._search(query, 4) for query in spec["queries"]))
        seen: set[str] = set()
        tracks: list[Track] = []
        for batch in results:
            for track in batch:
                if track.id in seen:
                    continue
                seen.add(track.id)
                tracks.append(track)
        random.shuffle(tracks)
        return self._store(cache_key, tracks)[:limit]

    async def mood(self, key: str, limit: int = 8) -> list[Track]:
        query = MOODS.get(key)
        if not query:
            return []
        cache_key = f"mood:{key}"
        cached = self._fresh(cache_key)
        if cached:
            return cached[:limit]
        tracks = await self._search(query, limit)
        return self._store(cache_key, tracks)[:limit]

    async def home(self, *, mixes: int = 4, trending: int = 12) -> dict[str, Any]:
        """Everything the Home view needs — cached, bounded, never a spinner."""
        cached = self._home_cache
        age = time.time() - cached[0] if cached else 0
        if cached and age < self.home_ttl:
            return cached[1]
        if cached and age < self.home_ttl * 3:
            # Serve what we have and refresh behind the request.
            self.prime()
            return cached[1]

        async with self._home_lock:
            cached = self._home_cache
            if cached and time.time() - cached[0] < self.home_ttl:
                return cached[1]
            payload = await self._build_home(mixes=mixes, trending=trending)
            self._home_cache = (time.time(), payload)
            return payload

    def prime(self) -> None:
        """Warm the Home payload in the background (called on boot)."""
        if self._prime_task is not None and not self._prime_task.done():
            return
        async def _warm() -> None:
            payload = await self._build_home(mixes=4, trending=12)
            self._home_cache = (time.time(), payload)

        self._prime_task = asyncio.ensure_future(_warm())

    async def _build_home(self, *, mixes: int = 4, trending: int = 12) -> dict[str, Any]:
        keys = list(MIXES)[:mixes]
        timeout = max(1.0, float(self.shelf_timeout))
        results = await asyncio.gather(
            asyncio.wait_for(self.trending(trending), timeout=timeout * 2),
            *(asyncio.wait_for(self.mix(key, 8), timeout=timeout) for key in keys),
            return_exceptions=True,
        )
        trending_tracks = results[0] if isinstance(results[0], list) else []
        mix_tracks = [item if isinstance(item, list) else [] for item in results[1:]]
        shelves = [
            Shelf(
                key=key,
                title=MIXES[key]["title"],
                glyph=MIXES[key]["glyph"],
                tracks=tracks,
                kind="mix",
            )
            for key, tracks in zip(keys, mix_tracks, strict=False)
        ]
        cover = next((t.thumbnail for t in trending_tracks if t.thumbnail), "")
        return {
            "generated_at": int(time.time()),
            "hero": {
                "headline": "Music hits different here.",
                "subline": "Discover, stream, download and listen together — all in one place.",
                "cover": cover,
            },
            "trending": [_track(t, index) for index, t in enumerate(trending_tracks, start=1)],
            "shelves": [
                {
                    "key": shelf.key,
                    "title": shelf.title,
                    "glyph": shelf.glyph,
                    "kind": shelf.kind,
                    "tracks": [_track(t, index) for index, t in enumerate(shelf.tracks, start=1)],
                }
                for shelf in shelves
                if shelf.tracks
            ],
            "moods": [
                {"key": key, "title": key.title(), "glyph": "note"} for key in MOODS
            ],
        }

    def invalidate(self, key: str | None = None) -> None:
        if key:
            self._cache.pop(key, None)
        else:
            self._cache.clear()


def _track(track: Track, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "id": track.id,
        "title": track.title,
        "uploader": track.uploader,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "source": track.source,
        "url": track.watch_url,
        "query": f"{track.title} {track.uploader}".strip(),
    }


__all__ = ["Charts", "MIXES", "MOODS", "Shelf"]
