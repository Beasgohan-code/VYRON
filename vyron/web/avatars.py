# ---------------------------------------------------------------------------
#  VYRON — Telegram profile pictures, for the Mini App
#
#  A Mini App knows the user's name but not their face. Telegram hands the
#  picture URL to the *client* inside initData; a browser session (owner token)
#  has no picture at all. Fetching it from the webview would mean a third-party
#  request per open, a different origin, and no cache we control — so it is
#  fetched here, once, and the bytes are kept.
#
#  Two sources, in order:
#    1. the signed `photo_url` from initData (cheap, no bot API call);
#    2. the bot itself (`get_chat` → `download_media`), for token sessions.
#
#  Everything is bounded: a 6-hour TTL, a 10-minute negative cache (a user with
#  no picture is not asked again on every screen), and a small LRU.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TTL = 6 * 3600  # a picture is trusted for six hours
MISS_TTL = 10 * 60  # then ask again — people do add a profile photo
MAX_ENTRIES = 128
MAX_BYTES = 512 * 1024  # a Telegram userpic is ~20–60 KB; refuse surprises
FETCH_TIMEOUT = 4.0


@dataclass(frozen=True)
class Avatar:
    body: bytes
    content_type: str
    etag: str

    @property
    def size(self) -> int:
        return len(self.body)


_CACHE: OrderedDict[int, tuple[float, Avatar | None]] = OrderedDict()


def sniff(body: bytes) -> str:
    """Content type from the first bytes — Telegram serves JPEG, sometimes PNG."""
    if body[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return ""


def _etag(body: bytes) -> str:
    import hashlib

    # Not a security boundary: an opaque tag for one user's picture, so a
    # changed photo is a changed URL rather than a stale one.
    digest = hashlib.sha256(body).hexdigest()  # noqa: S324
    return f'"{digest[:20]}"'


def remember(user_id: int, avatar: Avatar | None, *, ttl: float | None = None) -> None:
    """Cache a picture (or the absence of one) for *user_id*."""
    if not user_id:
        return
    _CACHE[int(user_id)] = (time.time() + (TTL if avatar else MISS_TTL if ttl is None else ttl), avatar)
    _CACHE.move_to_end(int(user_id))
    while len(_CACHE) > MAX_ENTRIES:
        _CACHE.popitem(last=False)


def lookup(user_id: int) -> tuple[bool, Avatar | None]:
    """``(known, avatar)`` — ``known`` is False when nothing is cached at all.

    The distinction matters: a cached ``None`` means "this user has no picture,
    do not ask Telegram again for ten minutes", which is different from "we
    have never looked".
    """
    key = int(user_id or 0)
    entry = _CACHE.get(key)
    if entry is None:
        return (False, None)
    expires, avatar = entry
    if expires < time.time():
        _CACHE.pop(key, None)
        return (False, None)
    _CACHE.move_to_end(key)
    return (True, avatar)


def cached(user_id: int) -> Avatar | None:
    """The picture for *user_id* when it is still fresh, else ``None``."""
    return lookup(user_id)[1]


def forget(user_id: int | None = None) -> None:
    if user_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(int(user_id), None)


def _build(body: bytes) -> Avatar | None:
    if not body or len(body) > MAX_BYTES:
        return None
    content_type = sniff(body)
    if not content_type:
        return None
    return Avatar(body=body, content_type=content_type, etag=_etag(body))


async def from_url(url: str) -> Avatar | None:
    """Fetch a Telegram userpic by URL. Never raises."""
    from vyron.web.auth import safe_photo_url

    url = safe_photo_url(url)
    if not url:
        return None
    from vyron.utils import net

    body = await net.fetch_bytes(
        url,
        limit=MAX_BYTES,
        timeout=FETCH_TIMEOUT,
        follow_redirects=False,  # a redirect is how an SSRF guard gets walked past
    )
    avatar = _build(body or b"")
    if avatar is None:  # pragma: no cover - network / content sniffing
        logger.debug("profile picture was not usable (%s)", url)
    return avatar


def _photo_file_id(obj) -> str:
    """The biggest file id on a `Chat`, `User` or photo object (or ``""``)."""
    photo = getattr(obj, "photo", None)
    if photo is not None:
        found = str(getattr(photo, "big_file_id", "") or getattr(photo, "small_file_id", ""))
        if found:
            return found
    found = str(getattr(obj, "file_id", "") or "")
    if found:
        return found
    sizes = getattr(obj, "sizes", None) or []
    # Telegram lists sizes smallest-first; the last one is the one to show.
    return str(getattr(sizes[-1], "file_id", "") or "") if sizes else ""


async def _file_id_for(bot, user_id: int) -> str:
    """Ask the client, across the two or three method names it may have.

    A client with a picture attached answers immediately; the photos endpoint
    is the fallback for the rest. Method names differ between Pyrogram and
    Kurigram (`get_chat_photos` / `get_profile_photos`), so both are tried —
    this is not a place to crash over an attribute.
    """
    for name in ("get_chat", "get_users"):
        method = getattr(bot, name, None)
        if method is None:
            continue
        try:
            answer = await asyncio.wait_for(method(int(user_id)), FETCH_TIMEOUT)
        except Exception:
            continue
        for candidate in answer if isinstance(answer, list) else [answer]:
            found = _photo_file_id(candidate)
            if found:
                return found

    for name in ("get_chat_photos", "get_profile_photos"):
        method = getattr(bot, name, None)
        if method is None:
            continue
        try:
            photos = await asyncio.wait_for(method(int(user_id), limit=1), FETCH_TIMEOUT)
        except Exception:
            continue
        for entry in photos or []:
            found = _photo_file_id(entry)
            if found:
                return found
    return ""


async def from_bot(user_id: int) -> Avatar | None:
    """Ask Telegram for the user's current picture. Never raises."""
    from vyron.runtime import runtime

    bot = getattr(runtime, "bot", None)
    if bot is None or not user_id:
        return None
    file_id = await _file_id_for(bot, int(user_id))
    if not file_id:
        return None
    try:
        blob = await asyncio.wait_for(
            bot.download_media(file_id, in_memory=True), FETCH_TIMEOUT * 2
        )
    except Exception as exc:
        logger.debug("profile picture download failed: %s", exc)
        return None
    body = blob.getvalue() if hasattr(blob, "getvalue") else bytes(blob or b"")
    return _build(body)


async def avatar_for(user_id: int, photo_url: str = "") -> Avatar | None:
    """The cached picture, or a freshly fetched one; ``None`` if there is none.

    The negative result is cached too, so a user who hides their picture costs
    one lookup every ten minutes rather than one per render.
    """
    if not user_id:
        return None
    known, avatar = lookup(user_id)
    if known:
        return avatar

    avatar = await from_url(photo_url) if photo_url else None
    if avatar is None:
        avatar = await from_bot(user_id)
    remember(user_id, avatar)
    return avatar


__all__ = [
    "Avatar",
    "avatar_for",
    "cached",
    "forget",
    "lookup",
    "from_bot",
    "from_url",
    "remember",
    "sniff",
]
