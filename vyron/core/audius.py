# ---------------------------------------------------------------------------
#  VYRON — Audius (a real open, streamable catalogue)
# ---------------------------------------------------------------------------
# The other extra sources hand us metadata and let YouTube supply the audio.
# Audius is different: it is a free, open music platform with its own public API
# and *direct* audio streams — no key, no login, no yt-dlp extractor needed. A
# link from audius.co becomes a track whose `url` is the stream itself, so a
# first play in a fresh deployment can succeed even when YouTube is throttling
# the server.
#
#   https://api.audius.co                      → discovery nodes
#   {node}/v1/resolve?url=…&app_name=VYRON     → the track behind a link
#   {node}/v1/tracks/{id}/stream?app_name=…    → the audio (302 → CDN)
#
# Mirrors are picked at random and cached for the process; every call is
# best-effort and returns ``None`` rather than raising.
from __future__ import annotations

import logging
import random
import re
from urllib.parse import quote, urlsplit

from vyron.core.queue import Track

logger = logging.getLogger(__name__)

API = "https://api.audius.co"
APP = "VYRON"
TIMEOUT = 8.0
_UA = {"User-Agent": "VYRON/1.5"}

_HOSTS: list[str] = []
_LINK = re.compile(r"(?:https?://)?(?:www\.)?audius\.co/[^\s]+", re.I)


def is_audius(url: str) -> bool:
    return bool(_LINK.search(url or ""))


async def _json(url: str) -> dict | None:
    """One request over the shared keep-alive session (see utils.net).

    Audius is the slowest of the three catalogues because it also has to pick a
    discovery node first; sharing the connection turns that from two handshakes
    into one.
    """
    from vyron.utils import net

    payload = await net.get_json(url, timeout=TIMEOUT, headers=_UA)
    return payload if isinstance(payload, dict) else None


async def host() -> str:
    """A healthy discovery node, cached for the process."""
    global _HOSTS
    if _HOSTS:
        return random.choice(_HOSTS)
    payload = await _json(f"{API}/")
    data = (payload or {}).get("data")
    if isinstance(data, list):
        _HOSTS = [str(item).rstrip("/") for item in data if isinstance(item, str)]
    if not _HOSTS:
        _HOSTS = ["https://discoveryprovider.audius.co"]
    return random.choice(_HOSTS)


def stream_url(node: str, track_id: str) -> str:
    return f"{node.rstrip('/')}/v1/tracks/{track_id}/stream?app_name={APP}"


def _artwork(payload: dict) -> str | None:
    art = payload.get("artwork") or {}
    if isinstance(art, dict):
        for key in ("1000x1000", "480x480", "150x150"):
            if art.get(key):
                return str(art[key])
    return None


def parse_track(payload: dict, node: str = "") -> Track | None:
    """Audius track JSON → VYRON's Track (stream URL included)."""
    if not isinstance(payload, dict) or not payload.get("id"):
        return None
    if str(payload.get("_type") or payload.get("kind") or "") in {"playlist", "album"}:
        return None
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    title = str(payload.get("title") or "Unknown title")
    return Track(
        id=str(payload["id"]),
        title=title,
        duration=int(payload.get("duration") or 0),
        url=stream_url(node, str(payload["id"])) if node else "",
        uploader=str(user.get("name") or user.get("handle") or ""),
        thumbnail=_artwork(payload),
        source="audius",
        is_video=False,
    )


def _normalise(url: str) -> str:
    raw = (url or "").strip()
    if not raw.lower().startswith("http"):
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    # Drop tracking noise, keep the path the API resolves.
    return f"https://{parts.netloc}{parts.path}".rstrip("/")


async def resolve(url: str) -> Track | None:
    """`audius.co/<artist>/<track>` → a playable Track with a direct stream."""
    if not is_audius(url):
        return None
    node = await host()
    payload = await _json(f"{node}/v1/resolve?url={quote(_normalise(url), safe='')}&app_name={APP}")
    data = (payload or {}).get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        logger.info("audius could not resolve %s", url)
        return None
    return parse_track(data, node)


async def search(query: str, limit: int = 5) -> list[Track]:
    """Audius search — used as an extra tier when YouTube yields nothing."""
    if not (query or "").strip():
        return []
    node = await host()
    payload = await _json(
        f"{node}/v1/tracks/search?query={quote(query)}&app_name={APP}&limit={max(1, limit)}"
    )
    data = (payload or {}).get("data")
    if not isinstance(data, list):
        return []
    tracks = [parse_track(item, node) for item in data]
    return [track for track in tracks if track]


def describe() -> str:
    return f"{len(_HOSTS)} node(s) known" if _HOSTS else "discovery on first use"


__all__ = ["describe", "host", "is_audius", "parse_track", "resolve", "search", "stream_url"]
