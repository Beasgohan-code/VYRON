# ---------------------------------------------------------------------------
#  VYRON — per-chat artwork (/thumbnail)
#
#  Every now-playing poster is rendered from the song's cover. A group can
#  replace the blurred backdrop with a picture of its own — a banner, a logo,
#  a photo of the room — while the cover tile and the colour accent still come
#  from the track, so the poster stays *this song* in *this chat*.
#
#      /thumbnail                 → status card (+ a preview of the artwork)
#      /thumbnail  (reply photo)  → use that photo here
#      /thumbnail off             → back to the song cover
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

from vyron.core import chatcfg
from vyron.ui import cards, rich
from vyron.utils.helpers import is_chat_admin, is_owner

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


async def allowed_to_set(client: Client, message: Message) -> bool:
    """Admins in a group, anyone in their own DM, the owner everywhere."""
    user = message.from_user
    if user is None:
        return False
    if is_owner(user.id):
        return True
    if message.chat.type == ChatType.PRIVATE:
        return True
    try:
        return await is_chat_admin(client, message.chat.id, user.id)
    except Exception:  # pragma: no cover - Telegram hiccup
        return False


async def show_status(client: Client, message: Message) -> None:
    """Status card, with the artwork itself when one is set."""
    chat_id = message.chat.id
    file_id = str(await chatcfg.get(chat_id, "thumbnail", "") or "")
    editor = await allowed_to_set(client, message)
    caption = cards.thumbnail_card(bool(file_id), can_edit=editor)

    if file_id:
        from vyron.ui.nowplaying import chat_art

        art = await chat_art(chat_id, client)
        if art:
            if await rich.send_photo(
                client, chat_id, art, caption, reply_to=message.id
            ):
                return

    await rich.send(client, chat_id, caption, reply_to=message.id)


async def save_art(client: Client, message: Message, file_id: str) -> None:
    chat_id = message.chat.id
    await chatcfg.set(chat_id, "thumbnail", file_id)
    logger.info("custom artwork set for %s", chat_id)
    await rich.send(
        client,
        chat_id,
        cards.thumbnail_set_card(),
        reply_to=message.id,
    )


async def clear_art(client: Client, message: Message) -> None:
    await chatcfg.set(message.chat.id, "thumbnail", "")
    logger.info("custom artwork cleared for %s", message.chat.id)
    await rich.send(
        client,
        message.chat.id,
        cards.thumbnail_cleared_card(),
        reply_to=message.id,
    )


def register(client: Client) -> None:
    @client.on_message(filters.command(["thumbnail"]))
    async def _thumbnail(actor: Client, message: Message) -> None:
        argument = (message.command[1].lower() if len(message.command) > 1 else "").strip()
        file_id = photo_file_id(message)
        current = str(await chatcfg.get(message.chat.id, "thumbnail", "") or "")

        if argument in {"off", "clear", "reset", "remove", "auto", "delete"}:
            if not await allowed_to_set(actor, message):
                await rich.send(
                    actor,
                    message.chat.id,
                    cards.error_card(
                        "<b>Admins only</b>\n"
                        "<blockquote>Only a group admin can change the artwork.</blockquote>"
                    ),
                    reply_to=message.id,
                )
                return
            await clear_art(actor, message)
            return

        if file_id:
            if art_too_big(message):
                await rich.send(
                    actor,
                    message.chat.id,
                    cards.error_card(
                        "<b>That picture is too big</b>\n"
                        f"<blockquote>Keep the artwork under {MAX_ART_BYTES // (1024 * 1024)} MB "
                        "— a normal photo works best.</blockquote>"
                    ),
                    reply_to=message.id,
                )
                return
            if not await allowed_to_set(actor, message):
                await rich.send(
                    actor,
                    message.chat.id,
                    cards.error_card(
                        "<b>Admins only</b>\n"
                        "<blockquote>Only a group admin can change the artwork.</blockquote>"
                    ),
                    reply_to=message.id,
                )
                return
            await save_art(actor, message, file_id)
            return

        del current  # only the file id matters for the card
        await show_status(actor, message)


__all__ = ["allowed_to_set", "photo_file_id", "register"]
