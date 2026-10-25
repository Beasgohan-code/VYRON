# ---------------------------------------------------------------------------
#  VYRON — cover art for the Mini App
#
#      GET /api/art/<media_id>?s=96|300|600
#
#  The app used to point every `<img>` straight at `i.ytimg.com`. That leaks
#  every listener's IP to a third party, adds a TLS handshake to the first
#  paint, and turns into a grey tile whenever a video is deleted. This route
#  serves the picture from our own origin instead:
#
#    · the track is resolved from the same registry `/api/stream` uses, so only
#      artwork the server has actually shown can be requested;
#    · the bytes are fetched once and kept in a small LRU;
#    · Pillow resizes to one of three widths and encodes WebP (JPEG on the
#      first request if it is already small enough);
#    · the response is `immutable` for thirty days and carries an ETag, so a
#      second render is a 304 — no bytes at all.
#
#  A miss is a 404 on purpose: the client already draws deterministic artwork
#  for a track with no picture, and that is better than a placeholder we would
#  have to keep in sync.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections import OrderedDict

from aiohttp import web

from vyron.utils.net import fetch_bytes

logger = logging.getLogger(__name__)

# The only hosts a `?u=` URL may name. A picture the app already holds a URL
# for is proxied; *any* URL is not, or this endpoint would be an open image
# proxy billed to the host (and an SSRF path into the private network).
ALLOWED_HOSTS = (
    "i.ytimg.com",
    "img.youtube.com",
    "yt3.ggpht.com",
    "yt3.googleusercontent.com",
    "i.scdn.co",
    "c.saavncdn.com",
    "aac.saavncdn.com",
    "lh3.googleusercontent.com",
    "pbs.twimg.com",
)

SIZES = (96, 300, 600)
MAX_ENTRIES = 240
MAX_BYTES = 400 * 1024
CACHE_MAX_AGE = 30 * 24 * 3600

# url → raw bytes (one download per picture, shared by every size)
_SOURCE: OrderedDict[str, bytes] = OrderedDict()
# (url, size) → (body, content_type, etag)
_RENDERED: OrderedDict[tuple[str, int], tuple[bytes, str, str]] = OrderedDict()
_LOCKS: dict[str, asyncio.Lock] = {}


def _trim(cache: OrderedDict, limit: int = MAX_ENTRIES) -> None:
    while len(cache) > limit:
        cache.popitem(last=False)


def forget() -> None:
    _SOURCE.clear()
    _RENDERED.clear()
    _LOCKS.clear()


def _etag(body: bytes) -> str:
    return f'"{hashlib.sha256(body).hexdigest()[:20]}"'


def allowed(url: str) -> str:
    """Return *url* when it is a picture on a host we proxy, else ``""``."""
    value = (url or "").strip()
    if not value.lower().startswith("https://") or len(value) > 900:
        return ""
    try:
        host = value.split("/", 3)[2].split(":")[0].lower()
    except IndexError:
        return ""
    if not any(host == allowed_host or host.endswith(f".{allowed_host}") for allowed_host in ALLOWED_HOSTS):
        return ""
    return value


def size_from(query: str) -> int:
    """The requested width, snapped to one of the three we cache."""
    try:
        wanted = int(query)
    except (TypeError, ValueError):
        return SIZES[1]
    return min(SIZES, key=lambda allowed: abs(allowed - wanted))


def shrink(body: bytes, size: int) -> tuple[bytes, str]:
    """Square-ish resize to *size* px and encode WebP. Falls back to the original.

    Covers are shown in cropped squares and wide backdrops, so the aspect ratio
    is kept and only the long edge is capped — `object-fit` does the rest. If
    Pillow is missing (a minimal deployment) the original bytes are served: a
    bigger JPEG is still far better than a third-party request.
    """
    try:
        from vyron.utils import thumbnails

        if not thumbnails.PIL_AVAILABLE:
            return body, "image/jpeg"
    except Exception:  # pragma: no cover - import guard
        return body, "image/jpeg"

    def work() -> tuple[bytes, str]:
        from io import BytesIO

        from PIL import Image

        with Image.open(BytesIO(body)) as image:
            image = image.convert("RGB")
            if max(image.size) > size:
                image.thumbnail((size, size), Image.LANCZOS)
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=4)
            return output.getvalue(), "image/webp"

    try:
        return work()
    except Exception as exc:
        # A truncated or exotic file is not a reason to fail the request: the
        # original bytes are still a picture the browser can draw.
        logger.debug("artwork resize failed (%s): %s", size, exc)
        return body, "image/jpeg"


async def _source_for(url: str) -> bytes | None:
    """One download per picture, even under a burst of parallel tiles."""
    cached = _SOURCE.get(url)
    if cached is not None:
        _SOURCE.move_to_end(url)
        return cached
    lock = _LOCKS.setdefault(url, asyncio.Lock())
    async with lock:
        cached = _SOURCE.get(url)
        if cached is not None:
            return cached
        body = await fetch_bytes(url, limit=MAX_BYTES)
        if body:
            _SOURCE[url] = body
            _trim(_SOURCE)
        return body


def _track(media_id: str):
    from vyron.web.stream import lookup

    try:
        return lookup(media_id)
    except Exception:  # pragma: no cover - registry is defensive already
        return None


async def artwork(request: web.Request) -> web.Response:
    """The picture for a track id, or for a URL the app was already handed."""
    media_id = request.match_info.get("media_id", "")
    if media_id:
        track = _track(media_id)
        url = (getattr(track, "thumbnail", "") or "").strip()
    else:
        # Collection art (a playlist sleeve, an artist card) arrives as a bare
        # URL with no track id, so it is proxied by URL — allowlisted, never
        # arbitrary, and cached exactly like the id form.
        url = allowed(request.query.get("u", ""))
    if not url:
        return web.Response(status=404, headers={"Cache-Control": "public, max-age=300"})

    size = size_from(request.query.get("s", ""))
    key = (url, size)
    rendered = _RENDERED.get(key)

    if rendered is None:
        source = await _source_for(url)
        if not source:
            return web.Response(status=404, headers={"Cache-Control": "public, max-age=300"})
        body, content_type = await asyncio.to_thread(shrink, source, size)
        rendered = (body, content_type, _etag(body))
        _RENDERED[key] = rendered
        _trim(_RENDERED)

    body, content_type, etag = rendered
    headers = {
        "Cache-Control": f"public, max-age={CACHE_MAX_AGE}, immutable",
        "ETag": etag,
        # The picture is served from our origin; a referrer would leak the
        # token in the app URL back to nobody useful.
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
    }
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers=headers)
    return web.Response(body=body, content_type=content_type, headers=headers)


def register(app: web.Application) -> None:
    app.router.add_get("/api/art", artwork)
    app.router.add_get("/api/art/{media_id}", artwork)


__all__ = ["ALLOWED_HOSTS", "allowed", "artwork", "forget", "register", "shrink", "size_from"]
