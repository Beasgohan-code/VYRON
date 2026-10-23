# ---------------------------------------------------------------------------
#  VYRON — owner / maintenance commands
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.ui.theme import E, reload_pack
from vyron.utils.helpers import command_args
from vyron.utils.filters import owner


def register(client: Client) -> None:
    @client.on_message(filters.command(["stats", "status"]))
    async def _stats(_: Client, message: Message) -> None:
        if not runtime.storage:
            return
        counters = await runtime.storage.counters()
        chats = len(await runtime.storage.all_chat_ids())
        active = len(runtime.player.active_chats()) if runtime.player else 0
        cache = runtime.downloader.cache_size() if runtime.downloader else 0
        markup = cards.stats_card(
            uptime=runtime.uptime,
            chats=chats,
            active=active,
            tracks=counters.get("tracks", runtime.player.tracks_played if runtime.player else 0),
            downloads=counters.get("downloads", 0),
            cache_bytes=cache,
            backend=runtime.storage.backend,
            version=runtime.version,
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

    @client.on_message(filters.command("broadcast") & owner)
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
            try:
                if target:
                    await target.copy(chat_id)
                else:
                    await client.send_message(chat_id, text)
                sent += 1
            except Exception:
                failed += 1
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

    @client.on_message(filters.command(["leaveall", "assleaveall"]) & owner)
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
