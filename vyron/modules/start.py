# ---------------------------------------------------------------------------
#  VYRON — start / help / about / ping
# ---------------------------------------------------------------------------
from __future__ import annotations

import time

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import cards, keyboards, rich
from vyron.ui.theme import E, emoji_enabled
from vyron.utils.helpers import is_private_chat


def register(client: Client) -> None:
    @client.on_message(filters.command(["start", "begin"]))
    async def _start(_: Client, message: Message) -> None:
        stats = await runtime.storage.counters() if runtime.storage else {}
        name = (message.from_user.first_name if message.from_user else "there") or "there"
        markup = cards.start_card(
            name,
            {"chats": stats.get("chats", 0), "tracks": stats.get("tracks", 0)},
            streaming=runtime.streaming_ready,
        )
        # No credential and no URL in the card: the Mini App identifies the
        # owner from Telegram's own initData, and its button is DM-only.
        await rich.send(
            message._client,
            message.chat.id,
            markup,
            markup_keyboard=keyboards.start_panel(player=is_private_chat(message.chat)),
            reply_to=message.id,
        )
        if runtime.storage:
            await runtime.storage.bump("starts")
            if message.chat.type.name in {"GROUP", "SUPERGROUP"}:
                await runtime.storage.bump("chats")

    @client.on_message(filters.command("help"))
    async def _help(_: Client, message: Message) -> None:
        await rich.send(
            message._client,
            message.chat.id,
            cards.help_card("main"),
            markup_keyboard=keyboards.help_nav("main"),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["about", "source", "repo"]))
    async def _about(_: Client, message: Message) -> None:
        await rich.send(
            message._client,
            message.chat.id,
            cards.about_card(),
            markup_keyboard=keyboards.back_close("v:help:main"),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["app", "player", "webapp", "web"]))
    async def _webapp(_: Client, message: Message) -> None:
        """Open the Mini App *inside Telegram* — never as a browser link."""
        if not keyboards.app_url():
            await rich.send(
                message._client,
                message.chat.id,
                cards.warn_card(
                    "<b>Web app is not configured</b>\n"
                    "<blockquote>Set <code>WEBAPP_URL</code> to the public URL of this "
                    "deployment, then restart.</blockquote>"
                ),
                reply_to=message.id,
            )
            return

        if is_private_chat(message.chat):
            await rich.send(
                message._client,
                message.chat.id,
                cards.webapp_card(settings.webapp_url or ""),
                markup_keyboard=keyboards.app_markup(with_close=True),
                reply_to=message.id,
            )
        else:
            await rich.send(
                message._client,
                message.chat.id,
                cards.webapp_group_card(settings.bot_username),
                markup_keyboard=keyboards.dm_markup(),
                reply_to=message.id,
            )

    @client.on_message(filters.command("ping"))
    async def _ping(_: Client, message: Message) -> None:
        started = time.perf_counter()
        sent = await rich.send(message._client, message.chat.id, cards.ok_card("<b>Measuring…</b>"))
        latency = (time.perf_counter() - started) * 1000
        if sent:
            await rich.edit(
                message._client,
                message.chat.id,
                sent.id,
                cards.ping_card(latency, runtime.uptime),
            )

    @client.on_message(filters.command(["id", "ids"]))
    async def _id(_: Client, message: Message) -> None:
        chat = message.chat
        lines = [
            f"{E('chat')} <b>Chat</b> <code>{chat.id}</code>",
            f"{E('user')} <b>You</b> <code>{message.from_user.id if message.from_user else 0}</code>",
        ]
        if message.reply_to_message and message.reply_to_message.from_user:
            lines.append(f"{E('users')} <b>Replied</b> <code>{message.reply_to_message.from_user.id}</code>")
        if message.reply_to_message and message.reply_to_message.audio:
            lines.append(f"{E('song')} <b>File</b> <code>{message.reply_to_message.audio.file_id[:42]}…</code>")
        await rich.send(message._client, chat.id, "\n".join(lines), reply_to=message.id)

    @client.on_message(filters.command(["emojis", "emoji", "premium"]))
    async def _emojis(_: Client, message: Message) -> None:
        pack = settings.emoji_map
        if not emoji_enabled() or not pack:
            text = (
                f"{E('info')} <b>Premium emoji: off</b>\n"
                f"<blockquote>Add an <code>emoji.json</code> pack (name → id) or set "
                f"<code>PREMIUM_EMOJI_FILE</code>. VYRON keeps working with plain glyphs "
                f"until then.</blockquote>"
            )
        else:
            sample = " ".join(E(name) for name in list(pack)[:12])
            text = (
                f"{E('spark')} <b>Premium emoji: on</b>\n"
                f"<blockquote>{len(pack)} glyphs loaded</blockquote>\n{sample}"
            )
        await rich.send(message._client, message.chat.id, text, reply_to=message.id)


__all__ = ["register"]
