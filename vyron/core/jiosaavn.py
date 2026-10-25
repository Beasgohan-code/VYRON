# ---------------------------------------------------------------------------
#  VYRON — JioSaavn (second direct-stream catalogue)
# ---------------------------------------------------------------------------
# Like Audius, JioSaavn hands out real audio URLs, which makes it the best
# fallback for Indian music when YouTube is refusing this server's IP. We talk
# to the open-source `saavn.dev` API (the same JSON the site itself uses) — no
# key, no login.
#
#   https://saavn.dev/api/search/songs?query=…&limit=…
#   https://saavn.dev/api/songs/{id}
#
# Every call is best-effort: an unreachable API returns ``[]``/``None`` and the
# resolver simply moves to the next tier.
from __future__ import annotations

import logging
import re
from urllib.parse import quote, urlsplit

from vyron.core.queue import Track

logger = logging.getLogger(__name__)

API = "https://saavn.dev/api"
APP_NAME = "VYRON"
TIMEOUT = 8.0
_UA = {"User-Agent": "VYRON/1.6"}

_LINK = re.compile(r"(?:https?://)?(?:www\.)?jiosaavn\.com/[^\s]+", re.I)


def is_jiosaavn(url: str) -> bool:
    return bool(_LINK.search(url or ""))


def _text(value) -> str:
    """JioSaavn returns HTML entities in titles ("Kesariya&nbsp;…")."""
    raw = str(value or "")
    for entity, replacement in (
        ("&quot;", '"'),
        ("&amp;", "&"),
        ("&#039;", "'"),
        ("&apos;", "'"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&nbsp;", " "),
    ):
        raw = raw.replace(entity, replacement)
    return raw.strip()


def _pick_url(entry: dict) -> str | None:
    """The highest-quality download URL, whatever order the API used."""
    downloads = entry.get("downloadUrl") or entry.get("download_url") or []
    if isinstance(downloads, list) and downloads:
        best = None
        best_quality = -1
        for item in downloads:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not url:
                continue
            quality = str(item.get("quality") or "")
            score = int(re.sub(r"\D", "", quality) or 0)
            if score > best_quality:
                best, best_quality = url, score
        if best:
            return str(best)
    stream = entry.get("media_url") or entry.get("url")
    if isinstance(stream, str) and stream.startswith("http"):
        return stream
    return None


def _artist(entry: dict) -> str:
    artists = entry.get("artists") or {}
    if isinstance(artists, dict):
        for bucket in ("primary", "featured", "all"):
            items = artists.get(bucket)
            if isinstance(items, list) and items:
                names = [
                    _text(item.get("name") if isinstance(item, dict) else item)
                    for item in items
                ]
                joined = ", ".join(name for name in names if name)
                if joined:
                    return joined
    if isinstance(artists, list):
        names = [_text(item.get("name") if isinstance(item, dict) else item) for item in artists]
        return ", ".join(name for name in names if name)
    return _text(entry.get("primaryArtists") or entry.get("singers") or "")


def _artwork(entry: dict) -> str | None:
    images = entry.get("image") or entry.get("images") or []
    if isinstance(images, list) and images:
        best = None
        best_size = -1
        for item in images:
            if not isinstance(item, dict):
                continue
            size = int(re.sub(r"\D", "", str(item.get("quality") or "")) or 0)
            if size > best_size and item.get("url") or item.get("link"):
                best = item.get("url") or item.get("link")
                best_size = size
        if best:
            return str(best)
    if isinstance(images, str) and images.startswith("http"):
        return images
    return None


def parse_song(entry: dict) -> Track | None:
    """One JioSaavn song object → VYRON's Track (with a direct URL)."""
    if not isinstance(entry, dict) or not entry.get("id"):
        return None
    url = _pick_url(entry)
    if not url:
        return None
    duration = entry.get("duration")
    if isinstance(duration, str):
        duration = int(re.sub(r"\D", "", duration) or 0)
    return Track(
        id=str(entry["id"]),
        title=_text(entry.get("name") or entry.get("title") or "Unknown title"),
        duration=int(duration or 0),
        url=url,
        uploader=_artist(entry),
        thumbnail=_artwork(entry),
        source="jiosaavn",
        is_video=False,
    )


async def _json(url: str) -> dict | None:
    """One request over the shared keep-alive session (see utils.net)."""
    from vyron.utils import net

    payload = await net.get_json(url, timeout=TIMEOUT, headers=_UA)
    return payload if isinstance(payload, dict) else None


async def search(query: str, limit: int = 5) -> list[Track]:
    """Search JioSaavn for streamable songs."""
    query = (query or "").strip()
    if not query:
        return []
    payload = await _json(
        f"{API}/search/songs?query={quote(query)}&limit={max(1, min(20, limit))}"
        f"&page=1&app_name={APP_NAME}"
    )
    data = (payload or {}).get("data")
    if isinstance(data, dict):
        results = data.get("results") or data.get("songs") or []
    elif isinstance(data, list):
        results = data
    else:
        results = []
    tracks = [parse_song(item) for item in results]
    return [track for track in tracks if track]


async def by_id(song_id: str) -> Track | None:
    if not song_id:
        return None
    payload = await _json(f"{API}/songs/{quote(str(song_id))}?app_name={APP_NAME}")
    data = (payload or {}).get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    return parse_song(data) if isinstance(data, dict) else None


def _slug_words(url: str) -> tuple[str, str]:
    """`.../song/kesariya-lyrics/<token>` → ("kesariya lyrics", token)."""
    path = urlsplit(url if url.lower().startswith("http") else "https://" + url).path
    parts = [part for part in path.split("/") if part]
    token = parts[-1] if parts else ""
    slug = next((part for part in reversed(parts) if "-" in part or part.isalpha()), "")
    words = slug.replace("-", " ").replace("_", " ").strip()
    return " ".join(dict.fromkeys(words.split())), token


async def resolve(url: str) -> Track | None:
    """A `jiosaavn.com` link → the streamable song behind it."""
    if not is_jiosaavn(url):
        return None
    words, token = _slug_words(url)
    candidates = await search(words or token, limit=6)
    if not candidates:
        return None
    # The share link's trailing token is a base64-ish id; matching the id is
    # exact when present, otherwise the slug text is what we trusted above.
    for track in candidates:
        if token and token in track.id:
            return track
    return candidates[0]


def describe() -> str:
    return "open saavn.dev API (direct 320kbps streams)"


__all__ = ["by_id", "describe", "is_jiosaavn", "parse_song", "resolve", "search"]
