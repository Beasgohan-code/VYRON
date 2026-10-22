# ---------------------------------------------------------------------------
#  VYRON — assistant account console
#
#  The userbot that actually joins the voice chat has its own Telegram profile.
#  These owner-only commands rebrand it without touching a terminal:
#
#      /setpfp   reply to a photo → new profile picture
#      /delpfp   remove every profile picture
#      /setbio <text>            → bio (max 70 chars)
#      /setname <first> [last]   → display name
#      /assistant                → current profile card
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args

logger = logging.getLogger(__name__)

MAX_BIO = 70
MAX_NAME = 64


async def _assistant():
    return runtime.assistant if runtime.streaming_ready else None


def _card(me) -> str:
    username = f"@{me.username}" if me.username else "—"
    return (
        B.heading(f"{E('microphone')} assistant", 3)
        + B.kv(
            [
                (f"{E('user')} name", f"<b>{rich.esc(me.first_name or '—')}</b>"),
                ("", rich.esc(me.last_name or "")),
                (f"{E('link')} username", f"<code>{rich.esc(username)}</code>"),
                (f"{E('id')} id", f"<code>{me.id}</code>"),
                (f"{E('info')} bio", f"<i>{rich.esc(truncate(me.bio or '—', MAX_BIO))}</i>"),
            ]
        )
        + B.note(
            f"{E('bolt')} This is the account that joins voice chats.\n"
            "<code>/setname</code> · <code>/setbio</code> · reply a photo with <code>/setpfp</code>"
        )
    )


def register(client: Client) -> None:
    async def _guard(message: Message) -> bool:
        if await _assistant() is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('warn')} The assistant session isn't configured.\n"
                    "Set <code>STRING_SESSION</code> (see <code>python -m vyron.tools.session</code>)."
                ),
                reply_to=message.id,
            )
            return False
        return True

    @client.on_message(filters.command(["assistant", "assistantinfo"]) & owner)
    async def _info(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        me = await runtime.assistant.get_me()
        await rich.send(client, message.chat.id, _card(me), reply_to=message.id)

    @client.on_message(filters.command(["setname", "assname"]) & owner)
    async def _setname(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        parts = command_args(message).split(maxsplit=1)
        if not parts or not parts[0]:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Usage: <code>/setname VYRON Assistant</code>"),
                reply_to=message.id,
            )
            return
        first = truncate(parts[0], MAX_NAME)
        last = truncate(parts[1], MAX_NAME) if len(parts) > 1 else ""
        try:
            await runtime.assistant.update_profile(first_name=first, last_name=last)
        except Exception as exc:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} Telegram refused that: {rich.esc(truncate(str(exc), 120))}"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('check')} Assistant is now <b>{rich.esc((first + ' ' + last).strip())}</b>."),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["setbio", "assbio"]) & owner)
    async def _setbio(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        bio = command_args(message).strip()
        if len(bio) > MAX_BIO:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} Telegram allows {MAX_BIO} characters — yours is {len(bio)}."),
                reply_to=message.id,
            )
            return
        try:
            await runtime.assistant.update_profile(bio=bio)
        except Exception as exc:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} Could not update the bio: {rich.esc(truncate(str(exc), 120))}"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('check')} Bio updated"
                + (f" → <i>{rich.esc(bio)}</i>" if bio else " (cleared)")
            ),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["setpfp", "asspfp"]) & owner)
    async def _setpfp(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        photo = None
        if message.reply_to_message:
            replied = message.reply_to_message
            photo = replied.photo or (replied.document if replied.document else None)
        if photo is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Reply to a photo with <code>/setpfp</code>."),
                reply_to=message.id,
            )
            return
        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} {B.think()} <b>Uploading profile photo…</b>",
            reply_to=message.id,
            editable=True,
        )
        try:
            path = await client.download_media(message.reply_to_message)
            with open(path, "rb") as handle:
                data = handle.read()
            await runtime.assistant.set_profile_photo(photo=io.BytesIO(data))
        except Exception as exc:
            markup = B.note(f"{E('warn')} Upload failed: {rich.esc(truncate(str(exc), 140))}")
        else:
            markup = B.note(f"{E('check')} Profile photo updated.")
        finally:
            try:
                import os

                if "path" in locals() and path:
                    os.unlink(path)
            except Exception:
                pass
        if status:
            await rich.edit(client, message.chat.id, status.id, markup)
        else:
            await rich.send(client, message.chat.id, markup)

    @client.on_message(filters.command(["delpfp", "delasspfp"]) & owner)
    async def _delpfp(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        removed = 0
        try:
            async for photo in runtime.assistant.get_chat_photos("me"):
                await runtime.assistant.delete_profile_photos(photo.file_id)
                removed += 1
        except Exception as exc:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} {rich.esc(truncate(str(exc), 120))}"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('check')} Removed {removed} profile photo{'s' if removed != 1 else ''}."
                if removed
                else f"{E('info')} The assistant had no profile photos."
            ),
            reply_to=message.id,
        )


__all__ = ["register"]
