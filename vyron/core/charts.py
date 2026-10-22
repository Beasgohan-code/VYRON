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

    def __init__(self, youtube: YouTube, *, ttl: int = 1800) -> None:
        self.youtube = youtube
        self.ttl = ttl
        self._cache: dict[str, tuple[float, list[Track]]] = {}
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

            tracks: list[Track] = []
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

    async def home(self, *, mixes: int = 6, trending: int = 12) -> dict[str, Any]:
        """Everything the Home view needs, fetched in parallel."""
        keys = list(MIXES)[:mixes]
        trending_tracks, *mix_tracks = await asyncio.gather(
            self.trending(trending),
            *(self.mix(key, 8) for key in keys),
        )
        shelves = [
            Shelf(
                key=key,
                title=MIXES[key]["title"],
                glyph=MIXES[key]["glyph"],
                tracks=tracks,
                kind="mix",
            )
            for key, tracks in zip(keys, mix_tracks)
        ]
        cover = next((t.thumbnail for t in trending_tracks if t.thumbnail), "")
        return {
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
