# ---------------------------------------------------------------------------
#  VYRON — now-playing delivery
#
#  One place that decides *how* a track is announced:
#
#    · a generated poster (cover art, vinyl, chips, waveform) when Pillow is
#      available and NP_POSTER is on,
#    · the classic rich card when it is not,
#    · and, for playback started from the Mini App, the same poster mirrored
#      into the listener's DM so the phone sees what the bot is doing.
#
#  The poster is cached per track: rendering is ~120 ms, and `/np` should never
#  make people wait for it twice.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from collections import OrderedDict

from vyron.config import settings
from vyron.core import i18n
from vyron.core.queue import ChatState, Track
from vyron.ui import cards, keyboards, rich
from vyron.utils import thumbnails

logger = logging.getLogger(__name__)

_CACHE: "OrderedDict[str, bytes]" = OrderedDict()
_CACHE_MAX = 24

# Chat artwork (`/thumbnail`) is a Telegram file id; the bytes are fetched once
# and kept, because a poster is re-rendered for every track in that chat.
_ART: "OrderedDict[str, bytes]" = OrderedDict()
_ART_MAX = 12


def _key(track: Track) -> str:
    return f"{track.id}|{track.title}|{track.uploader}|{track.duration}"


def enabled() -> bool:
    return bool(settings.np_poster and thumbnails.PIL_AVAILABLE)


async def allowed(chat_id: int) -> bool:
    """Global switch *and* this chat's preference (`/settings` → Poster)."""
    if not enabled():
        return False
    try:
        from vyron.core import chatcfg

        return bool(await chatcfg.get(chat_id, "poster", True))
    except Exception:  # pragma: no cover - never block playback on config
        return True


async def chat_art(chat_id: int, bot=None) -> bytes | None:
    """The custom artwork this chat set with `/thumbnail`, if any."""
    from vyron.core import chatcfg

    try:
        file_id = await chatcfg.get(int(chat_id), "thumbnail", "")
    except Exception:  # pragma: no cover - config must never break playback
        return None
    if not file_id:
        return None
    cached = _ART.get(str(file_id))
    if cached is not None:
        _ART.move_to_end(str(file_id))
        return cached
    if bot is None:
        from vyron.runtime import runtime  # local: runtime imports the player

        bot = getattr(runtime, "bot", None)
    client = bot
    if client is None:
        return None
    try:
        data = await client.download_media(str(file_id), in_memory=True)
        blob = data.getvalue() if hasattr(data, "getvalue") else bytes(data or b"")
    except Exception as exc:
        logger.debug("custom thumbnail download failed: %s", exc)
        return None
    if not blob:
        return None
    _ART[str(file_id)] = blob
    while len(_ART) > _ART_MAX:
        _ART.popitem(last=False)
    return blob


async def poster(state: ChatState, track: Track, *, bot=None, chat_id: int | None = None) -> bytes | None:
    """The rendered poster for *track*, memoised (bytes, JPEG)."""
    if not enabled() or track is None:
        return None
    target = int(chat_id or (state.chat_id if state else 0) or 0)
    backdrop = await chat_art(target, bot) if target else None
    # The artwork is part of the identity of the picture, so it belongs in the
    # cache key; a chat that changes its backdrop gets a fresh render.
    key = _key(track) if not backdrop else f"{_key(track)}|art{hash(backdrop) & 0xFFFFFFFF}"
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    # Render at the start of the track: the picture is a *cover*, the live
    # clock lives in the caption so nothing has to be re-uploaded.
    snapshot = ChatState(chat_id=state.chat_id if state else 0, current=track)
    snapshot.started_at = 0.0
    image = await thumbnails.now_playing(snapshot, track, backdrop=backdrop)
    if image:
        _CACHE[key] = image
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return image


async def announce(
    bot,
    chat_id: int,
    state: ChatState,
    *,
    dm_to: int | None = None,
    chat_title: str = "",
    edit: bool = False,
) -> None:
    """Post the now-playing picture (or card) and remember where it landed."""
    if bot is None or state is None or state.current is None:
        return
    track = state.current
    keyboard = keyboards.now_playing(state)

    catalog = await i18n.for_chat(chat_id)

    if edit and state.np_message_id:
        markup = (
            cards.now_playing_caption(state, catalog)
            if rich.is_photo(chat_id, state.np_message_id)
            else cards.now_playing_card(state)
        )
        if await rich.edit(bot, chat_id, state.np_message_id, markup, markup_keyboard=keyboard):
            return

    want_poster = await allowed(chat_id)
    image = await poster(state, track, bot=bot, chat_id=chat_id) if want_poster else None
    if want_poster and image is None:
        # Silent was the problem: the chat got a text card instead of the
        # artwork with nothing anywhere saying why. One line in the owner's
        # journal is enough to diagnose it (no Pillow, no fonts, a render bug).
        from vyron.core.journal import journal

        journal.warn(
            "art",
            "the now-playing poster could not be drawn",
            chat=chat_id,
            track=track.id,
            pillow=bool(thumbnails.PIL_AVAILABLE),
        )
    message = None
    if image:
        message = await rich.send_photo(
            bot,
            chat_id,
            image,
            cards.now_playing_caption(state, catalog),
            markup_keyboard=keyboard,
        )
    if message is None:
        message = await rich.send(
            bot,
            chat_id,
            cards.now_playing_card(state),
            markup_keyboard=keyboard,
            editable=True,
        )
    if message is not None:
        state.np_message_id = message.id

    if dm_to and settings.np_dm and dm_to != int(chat_id):
        await mirror_to_dm(bot, dm_to, state, chat_title=chat_title)


async def mirror_to_dm(bot, user_id: int, state: ChatState, *, chat_title: str = "") -> None:
    """Send the same poster to a person's DM — used for Mini App playback."""
    if bot is None or state is None or state.current is None or not user_id:
        return
    track = state.current
    catalog = await i18n.for_chat(user_id)
    caption = cards.now_playing_dm_caption(
        track, chat_title=chat_title, state=state, catalog=catalog
    )
    # The mirrored poster shows the *room* it is playing in — the DM inherits
    # the group's artwork, not whatever the listener set in private.
    image = await poster(state, track, bot=bot, chat_id=int(state.chat_id or user_id))
    try:
        if image:
            await rich.send_photo(bot, int(user_id), image, caption)
        else:
            await rich.send(bot, int(user_id), caption)
    except Exception as exc:  # user never opened the bot, blocked it, etc.
        logger.debug("now-playing mirror to %s failed: %s", user_id, exc)


__all__ = ["announce", "enabled", "mirror_to_dm", "poster"]
