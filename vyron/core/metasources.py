# ---------------------------------------------------------------------------
#  VYRON — extra music sources
# ---------------------------------------------------------------------------
# A link from Spotify, Deezer, Apple Music or SoundCloud is a *catalogue*
# reference: those services hand out metadata, not audio we may stream. So the
# job here is narrow and honest — read the title/artist/artwork from the
# service's own public endpoint (no API key, no credentials, no scraping of
# anything behind a login), then let the normal YouTube ladder find the audio.
#
# Endpoints used:
#   Deezer      https://api.deezer.com/{track,album,playlist}/{id}   (open API)
#   iTunes      https://itunes.apple.com/lookup?id={id}&entity=song  (open API)
#   Spotify     https://open.spotify.com/oembed?url=…                (oEmbed)
#               https://open.spotify.com/embed/{kind}/{id}           (public page)
#   SoundCloud  https://soundcloud.com/oembed?format=json&url=…      (oEmbed)
#   YT Music    music.youtube.com/watch?v=… — a YouTube id already, passed through
#
# Everything degrades to ``None``: an unreachable catalogue must never stop a
# track from playing, it only means we fall back to the plain YouTube search.
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from dataclasses import dataclass, field

import aiohttp

logger = logging.getLogger(__name__)

TIMEOUT = 8.0
_UA = {"User-Agent": "Mozilla/5.0 (compatible; VYRON/1.4)"}

# ── link shapes ─────────────────────────────────────────────────────────────
_SPOTIFY = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?(?P<kind>track|album|playlist|artist)/(?P<id>[A-Za-z0-9]+)",
    re.I,
)
_SPOTIFY_URI = re.compile(r"^spotify:(?P<kind>track|album|playlist|artist):(?P<id>[A-Za-z0-9]+)$", re.I)
_DEEZER = re.compile(r"deezer\.(?:com|page\.link)/(?:[a-z-]+/)?(?P<kind>track|album|playlist)/(?P<id>\d+)", re.I)
_DEEZER_SHORT = re.compile(r"^https?://(?:www\.)?deezer\.page\.link/\S+", re.I)
_APPLE = re.compile(
    r"music\.apple\.com/(?:[a-z]{2}/)?(?P<kind>album|playlist|artist)/[^/]*/?(?:id)?(?P<album>\d+)"
    r"(?:\?.*?\bi=(?P<track>\d+))?",
    re.I,
)
_APPLE_SONG = re.compile(r"music\.apple\.com/(?:[a-z]{2}/)?song/[^/]*/(?P<id>\d+)", re.I)
_SOUNDCLOUD = re.compile(r"soundcloud\.com/[^/\s]+/[^/\s?#]+", re.I)
_YTMUSIC = re.compile(r"music\.youtube\.com/(?:watch\?v=|shorts/)(?P<id>[\w-]{11})", re.I)

SERVICES = ("spotify", "deezer", "apple", "soundcloud", "ytmusic")


@dataclass
class MetaTrack:
    """Catalogue metadata for one track — enough to search, nothing more."""

    title: str
    artist: str = ""
    duration: int = 0
    artwork: str | None = None
    service: str = ""
    url: str = ""

    @property
    def query(self) -> str:
        """What to type into YouTube to find this. Artist first reads better."""
        bits = [part for part in (self.artist, self.title) if part]
        return " ".join(bits) or self.title

    def as_dict(self) -> dict:
        return {
            "title": self.title,
            "artist": self.artist,
            "duration": self.duration,
            "artwork": self.artwork,
            "service": self.service,
            "query": self.query,
        }


@dataclass
class MetaCollection:
    """An album / playlist: a title (optional) and its tracks."""

    kind: str
    title: str = ""
    service: str = ""
    tracks: list[MetaTrack] = field(default_factory=list)

    def queries(self, limit: int = 50) -> list[str]:
        return [track.query for track in self.tracks[:limit]]


@dataclass
class _Link:
    service: str
    kind: str            # track | album | playlist | artist | song
    id: str = ""
    album_id: str = ""
    url: str = ""


def detect(url: str) -> _Link | None:
    """Classify a catalogue link without touching the network."""
    raw = html.unescape((url or "").strip())
    if not raw:
        return None
    if raw.lower().startswith("spotify:"):
        match = _SPOTIFY_URI.match(raw)
        return _Link("spotify", match.group("kind"), match.group("id"), url=raw) if match else None
    match = _SPOTIFY.search(raw)
    if match:
        return _Link("spotify", match.group("kind"), match.group("id"), url=raw)
    match = _DEEZER.search(raw)
    if match:
        return _Link("deezer", match.group("kind"), match.group("id"), url=raw)
    if _DEEZER_SHORT.match(raw):
        return _Link("deezer", "short", url=raw)
    match = _APPLE_SONG.search(raw)
    if match:
        return _Link("apple", "song", match.group("id"), url=raw)
    match = _APPLE.search(raw)
    if match:
        if match.group("track"):
            return _Link(
                "apple", "song", match.group("track"), album_id=match.group("album"), url=raw
            )
        return _Link("apple", match.group("kind"), match.group("album"), url=raw)
    match = _YTMUSIC.search(raw)
    if match:
        return _Link("ytmusic", "track", match.group("id"), url=raw)
    if _SOUNDCLOUD.search(raw):
        return _Link("soundcloud", "track", url=raw)
    return None


def is_catalogue_link(url: str) -> bool:
    link = detect(url)
    return bool(link and link.service != "ytmusic")


def is_passthrough(url: str) -> bool:
    """YT Music links are plain YouTube ids — the normal ladder already works."""
    link = detect(url)
    return bool(link and link.service == "ytmusic")


# ── transport ───────────────────────────────────────────────────────────────
async def _json(url: str, *, session: aiohttp.ClientSession | None = None) -> dict | None:
    async def _get(client: aiohttp.ClientSession) -> dict | None:
        async with client.get(url, headers=_UA) as response:
            if response.status != 200:
                logger.debug("%s → HTTP %s", url, response.status)
                return None
            try:
                payload = await response.json(content_type=None)
            except Exception:
                return None
            return payload if isinstance(payload, (dict, list)) else None

    if session is not None:
        return await _get(session)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as client:
        return await _get(client)


async def _text(url: str) -> str | None:
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as client:
            async with client.get(url, headers=_UA) as response:
                if response.status != 200:
                    return None
                return await response.text()
    except Exception as exc:
        logger.debug("%s failed: %s", url, exc)
        return None


# ── Deezer ─────────────────────────────────────────────────────────────────
def _deezer_track(payload: dict, service: str = "deezer") -> MetaTrack | None:
    if not isinstance(payload, dict) or payload.get("error") or not payload.get("title"):
        return None
    artist = (payload.get("artist") or {}).get("name") if isinstance(payload.get("artist"), dict) else ""
    album = payload.get("album") if isinstance(payload.get("album"), dict) else {}
    artwork = album.get("cover_xl") or album.get("cover_big") or album.get("cover") or None
    return MetaTrack(
        title=str(payload["title"]),
        artist=str(artist or ""),
        duration=int(payload.get("duration") or 0),
        artwork=artwork,
        service=service,
        url=str(payload.get("link") or ""),
    )


async def _final_url(url: str) -> str | None:
    """Follow redirects once — `deezer.page.link/…` hides the real path."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=TIMEOUT)) as client:
            async with client.get(url, headers=_UA, allow_redirects=True) as response:
                return str(response.url)
    except Exception as exc:
        logger.debug("redirect %s failed: %s", url, exc)
        return None


async def _deezer(link: _Link) -> MetaTrack | MetaCollection | None:
    if link.kind == "short":
        # Short links carry no id: follow the redirect, then re-classify.
        final = await _final_url(link.url) if link.url else None
        resolved = detect(final or "")
        if resolved is None or resolved.kind == "short":
            return None
        return await _deezer(resolved)
    if link.kind == "track":
        payload = await _json(f"https://api.deezer.com/track/{link.id}")
        return _deezer_track(payload or {})
    if link.kind == "album":
        payload = await _json(f"https://api.deezer.com/album/{link.id}")
        if not isinstance(payload, dict) or payload.get("error"):
            return None
        items = ((payload.get("tracks") or {}).get("data") or [])
        tracks = [_deezer_track(item) for item in items]
        return MetaCollection(
            kind="album",
            title=str(payload.get("title") or ""),
            service="deezer",
            tracks=[track for track in tracks if track],
        )
    if link.kind == "playlist":
        payload = await _json(f"https://api.deezer.com/playlist/{link.id}")
        if not isinstance(payload, dict) or payload.get("error"):
            return None
        items = ((payload.get("tracks") or {}).get("data") or [])
        tracks = [_deezer_track(item) for item in items]
        return MetaCollection(
            kind="playlist",
            title=str(payload.get("title") or ""),
            service="deezer",
            tracks=[track for track in tracks if track],
        )
    return None


# ── Apple Music / iTunes ───────────────────────────────────────────────────
async def _apple(link: _Link) -> MetaTrack | MetaCollection | None:
    if link.kind == "song":
        payload = await _json(f"https://itunes.apple.com/lookup?id={link.id}")
        results = (payload or {}).get("results") or []
        if not results:
            return None
        item = results[0]
        return MetaTrack(
            title=str(item.get("trackName") or ""),
            artist=str(item.get("artistName") or ""),
            duration=int((item.get("trackTimeMillis") or 0) / 1000),
            artwork=item.get("artworkUrl100") or None,
            service="apple",
            url=str(item.get("trackViewUrl") or ""),
        )
    if link.kind == "album":
        payload = await _json(
            f"https://itunes.apple.com/lookup?id={link.id}&entity=song&limit=100"
        )
        results = (payload or {}).get("results") or []
        title = ""
        tracks: list[MetaTrack] = []
        for item in results:
            if item.get("wrapperType") == "collection":
                title = str(item.get("collectionName") or "")
                continue
            if item.get("wrapperType") != "track":
                continue
            tracks.append(
                MetaTrack(
                    title=str(item.get("trackName") or ""),
                    artist=str(item.get("artistName") or ""),
                    duration=int((item.get("trackTimeMillis") or 0) / 1000),
                    artwork=item.get("artworkUrl100") or None,
                    service="apple",
                    url=str(item.get("trackViewUrl") or ""),
                )
            )
        return MetaCollection(kind="album", title=title, service="apple", tracks=tracks)
    return None


# ── Spotify (oEmbed + the public embed page) ───────────────────────────────
def _spotify_embed_entity(page: str) -> dict | None:
    """Pull the `__NEXT_DATA__` JSON out of a public Spotify embed page."""
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(?P<json>.*?)</script>',
        page,
        re.S,
    )
    if not match:
        return None
    try:
        payload = json.loads(match.group("json"))
    except Exception:
        return None
    entity = ((payload.get("props") or {}).get("pageProps") or {}).get("state", {}).get("data", {}).get("entity")
    if isinstance(entity, dict):
        return entity
    # Newer shells keep it under pageProps.state.data itself.
    data = ((payload.get("props") or {}).get("pageProps") or {}).get("state", {}).get("data")
    return data if isinstance(data, dict) else None


def _spotify_track_from_entity(entity: dict) -> MetaTrack | None:
    name = entity.get("name") or entity.get("title")
    if not name:
        return None
    artists = entity.get("artists") or entity.get("subtitle") or ""
    if isinstance(artists, list):
        artist = ", ".join(
            str(item.get("name") if isinstance(item, dict) else item).strip()
            for item in artists
            if item
        )
    else:
        artist = str(artists)
    art = None
    sources = (entity.get("coverArt") or {}).get("sources") or []
    if sources:
        art = sources[0].get("url")
    if not art:
        images = (entity.get("visualIdentity") or {}).get("image") or []
        if images:
            art = max(images, key=lambda item: item.get("maxWidth") or 0).get("url")
    return MetaTrack(
        title=str(name),
        artist=artist.strip(),
        duration=int((entity.get("duration") or 0) / 1000),
        artwork=art,
        service="spotify",
    )


async def _spotify(link: _Link) -> MetaTrack | MetaCollection | None:
    page = await _text(f"https://open.spotify.com/embed/{link.kind}/{link.id}")
    if page:
        entity = _spotify_embed_entity(page)
        if entity:
            if link.kind == "track":
                track = _spotify_track_from_entity(entity)
                if track:
                    return track
            else:
                items = entity.get("trackList") or entity.get("tracks") or []
                tracks: list[MetaTrack] = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    title = item.get("title") or item.get("name")
                    if not title:
                        continue
                    subtitle = item.get("subtitle") or ""
                    tracks.append(
                        MetaTrack(
                            title=str(title),
                            artist=str(subtitle),
                            duration=int((item.get("duration") or 0) / 1000),
                            artwork=item.get("coverArt") or None,
                            service="spotify",
                        )
                    )
                if tracks:
                    return MetaCollection(
                        kind=link.kind,
                        title=str(entity.get("name") or entity.get("title") or ""),
                        service="spotify",
                        tracks=tracks,
                    )
    # oEmbed is the fallback: it always answers, but only knows the title.
    payload = await _json(
        "https://open.spotify.com/oembed?url=" + f"https://open.spotify.com/{link.kind}/{link.id}"
    )
    if not isinstance(payload, dict) or not payload.get("title"):
        return None
    title = str(payload["title"])
    artist = ""
    if " - song and lyrics by " in title:
        title, artist = title.split(" - song and lyrics by ", 1)
    elif " · " in title:
        title, artist = title.split(" · ", 1)
    return MetaTrack(
        title=title.strip(),
        artist=artist.strip(),
        artwork=payload.get("thumbnail_url"),
        service="spotify",
    )


# ── SoundCloud ─────────────────────────────────────────────────────────────
async def _soundcloud(url: str) -> MetaTrack | None:
    payload = await _json("https://soundcloud.com/oembed?format=json&url=" + url)
    if not isinstance(payload, dict) or not payload.get("title"):
        return None
    title = str(payload["title"])
    artist = str(payload.get("author_name") or "")
    if not artist and " by " in title:
        title, artist = title.rsplit(" by ", 1)
    return MetaTrack(
        title=title.strip(),
        artist=artist.strip(),
        artwork=payload.get("thumbnail_url"),
        service="soundcloud",
        url=url,
    )


# ── public API ─────────────────────────────────────────────────────────────
async def lookup(url: str) -> MetaTrack | MetaCollection | None:
    """Read a catalogue link. Returns ``None`` when the service cannot answer."""
    link = detect(url)
    if link is None:
        return None
    try:
        if link.service == "deezer":
            return await _deezer(link)
        if link.service == "apple":
            return await _apple(link)
        if link.service == "spotify":
            return await _spotify(link)
        if link.service == "soundcloud":
            return await _soundcloud(url)
    except Exception as exc:  # network, DNS, a changed page — all the same here
        logger.info("%s link could not be read: %s", link.service, exc)
    return None


async def lookup_many(urls: list[str], *, limit: int = 50) -> list[MetaTrack]:
    """Read several catalogue links at once (unused slots stay empty)."""
    results = await asyncio.gather(*(lookup(url) for url in urls), return_exceptions=True)
    tracks: list[MetaTrack] = []
    for result in results:
        if isinstance(result, MetaTrack):
            tracks.append(result)
        elif isinstance(result, MetaCollection):
            tracks.extend(result.tracks)
        if len(tracks) >= limit:
            break
    return tracks[:limit]


__all__ = [
    "SERVICES",
    "MetaCollection",
    "MetaTrack",
    "detect",
    "is_catalogue_link",
    "is_passthrough",
    "lookup",
    "lookup_many",
]
