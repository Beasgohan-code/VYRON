# ---------------------------------------------------------------------------
#  VYRON — owner / maintenance commands
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.config import settings
from vyron.core.musicapi import get_music_api
from vyron.ui import cards, rich
from vyron.ui.theme import E, reload_pack
from vyron.utils.helpers import command_args, is_private_chat

logger = logging.getLogger(__name__)
from vyron.utils.filters import owner


def register(client: Client) -> None:
    @client.on_message(filters.command(["stats"]))
    async def _stats(_: Client, message: Message) -> None:
        if not runtime.storage:
            return
        counters = await runtime.storage.counters()
        chats = len(await runtime.storage.all_chat_ids())
        active = len(runtime.player.active_chats()) if runtime.player else 0
        cache = runtime.downloader.cache_size() if runtime.downloader else 0
        api_stats = await get_music_api().stats()
        links: dict[str, str] = {}
        sender = message.from_user.id if message.from_user else 0
        if sender and sender in settings.owners:
            root = (settings.api_base or settings.keepalive_url or settings.webapp_url or "").rstrip("/")
            if root:
                links["api"] = f"{root}/v1/docs"
            if settings.webapp_ready and is_private_chat(message.chat):
                # Presence only: the button itself carries no URL.
                links["player"] = "1"
        markup = cards.stats_card(
            uptime=runtime.uptime,
            chats=chats,
            active=active,
            tracks=counters.get("tracks", runtime.player.tracks_played if runtime.player else 0),
            downloads=counters.get("downloads", 0),
            cache_bytes=cache,
            backend=runtime.storage.backend,
            version=runtime.version,
            api=api_stats,
            links=links,
        )
        await rich.send(client, message.chat.id, markup, reply_to=message.id)

    @client.on_message(filters.command("active") & owner)
    async def _active(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        lines = []
        for chat_id in runtime.player.active_chats():
            state = runtime.player.queues.get(chat_id)
            if state.current:
                lines.append(f"• <code>{chat_id}</code> — {rich.esc(state.current.title[:40])}")
        body = "\n".join(lines) if lines else "<i>No active voice chats.</i>"
        await rich.send(
            client,
            message.chat.id,
            f"{E('live')} <b>Active sessions</b>\n<blockquote>{body}</blockquote>",
        )

    @client.on_message(filters.command(["broadcast"]) & owner)
    async def _broadcast(_: Client, message: Message) -> None:
        text = command_args(message)
        target = message.reply_to_message
        if not text and not target:
            await rich.send(client, message.chat.id, cards.warn_card("Usage: <code>/broadcast text</code>"))
            return
        if not runtime.storage:
            return

        chat_ids = await runtime.storage.all_chat_ids()
        status = await rich.send(
            client,
            message.chat.id,
            f"{E('rocket')} <b>Broadcasting…</b> <code>0/{len(chat_ids)}</code>",
        )
        sent = failed = 0
        for index, chat_id in enumerate(chat_ids, start=1):
            for attempt in (1, 2):
                try:
                    if target:
                        await target.copy(chat_id)
                    else:
                        await client.send_message(chat_id, text)
                    sent += 1
                    break
                except FloodWait as exc:
                    # Telegram's own rate limit is not a failed delivery: wait
                    # the exact amount it asks for, then retry this chat once.
                    wait = int(getattr(exc, "value", 5) or 5) + 1
                    logger.info("broadcast flood wait %ss", wait)
                    if attempt == 1:
                        await asyncio.sleep(wait)
                        continue
                    failed += 1
                except Exception:
                    failed += 1
                    break
            if status and index % 10 == 0:
                await rich.edit(
                    client,
                    message.chat.id,
                    status.id,
                    f"{E('rocket')} <b>Broadcasting…</b> <code>{index}/{len(chat_ids)}</code>",
                )
            await asyncio.sleep(0.05)
        if status:
            await rich.edit(
                client,
                message.chat.id,
                status.id,
                cards.ok_card(f"<b>Broadcast finished</b> — {sent} sent, {failed} failed."),
            )

    @client.on_message(filters.command(["leaveall"]) & owner)
    async def _leaveall(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        chats = runtime.player.active_chats()
        for chat_id in chats:
            await runtime.player.leave(chat_id)
        await rich.send(
            client,
            message.chat.id,
            cards.ok_card(f"<b>Left {len(chats)} voice chats</b>"),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["emojireload", "reload"]) & owner)
    async def _reload(_: Client, message: Message) -> None:
        reload_pack()
        await rich.send(
            client,
            message.chat.id,
            cards.ok_card("<b>Emoji pack reloaded</b>"),
            reply_to=message.id,
        )


__all__ = ["register"]
