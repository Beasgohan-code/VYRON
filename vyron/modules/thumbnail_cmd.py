# ---------------------------------------------------------------------------
#  VYRON — artwork helpers
# ---------------------------------------------------------------------------
#  There is no `/thumbnail` command: the now-playing poster draws itself from
#  the song's own cover, which is what people actually want, and asking a group
#  to choose a backdrop for it was a step nobody took. What is left here is the
#  shared reading of a photo message, used by `/cthumbnail` for a channel's
#  poster art — one place that knows what "the picture in this message" means.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram.types import Message

logger = logging.getLogger(__name__)

MAX_ART_BYTES = 4 * 1024 * 1024  # Telegram photos are far below this


def _media_of(message: Message):
    """The photo (or image document) attached to *message*, if any."""
    photo = getattr(message, "photo", None)
    if photo is not None:
        return photo
    document = getattr(message, "document", None)
    if document is not None and (getattr(document, "mime_type", "") or "").lower().startswith("image/"):
        return document
    return None


def photo_file_id(message: Message) -> str:
    """The best file id available on *message* (its own photo, or a reply's)."""
    for candidate in (message.reply_to_message, message):
        if candidate is None:
            continue
        media = _media_of(candidate)
        if media is not None:
            return str(getattr(media, "file_id", "") or "")
    return ""


def art_too_big(message: Message) -> bool:
    """Photos are compressed by Telegram; an image *file* can be a huge PNG."""
    for candidate in (message.reply_to_message, message):
        media = _media_of(candidate) if candidate is not None else None
        size = int(getattr(media, "file_size", 0) or 0) if media is not None else 0
        if size and size > MAX_ART_BYTES:
            return True
    return False


__all__ = ["MAX_ART_BYTES", "art_too_big", "photo_file_id"]
