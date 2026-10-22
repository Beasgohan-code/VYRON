# ---------------------------------------------------------------------------
#  VYRON — queue commands
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import cards, keyboards, rich
from vyron.ui.theme import E
from vyron.utils.helpers import command_args


def register(client: Client) -> None:
    @client.on_message(filters.command(["queue", "q"]))
    async def _queue(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        arg = command_args(message)
        page = int(arg) - 1 if arg.isdigit() else 0
        state = runtime.player.queues.get(message.chat.id)
        markup, pages = cards.queue_card(state, max(0, page))
        await rich.send(
            client,
            message.chat.id,
            markup,
            markup_keyboard=keyboards.queue(state, max(0, min(page, pages - 1)), pages),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["clear", "clearqueue"]))
    async def _clear(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        removed = runtime.player.queues.clear(message.chat.id, keep_current=True)
        await runtime.player.refresh_now_playing(message.chat.id)
        await rich.send(
            client,
            message.chat.id,
            f"{E('check')} <b>Queue cleared</b> <code>{removed}</code> tracks removed",
            reply_to=message.id,
        )

    @client.on_message(filters.command(["remove", "rm"]))
    async def _remove(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        arg = command_args(message)
        if not arg.isdigit():
            await rich.send(client, message.chat.id, cards.warn_card("Usage: <code>/remove 3</code>"))
            return
        track = runtime.player.queues.remove(message.chat.id, int(arg))
        if not track:
            await rich.send(client, message.chat.id, cards.warn_card("There is nothing at that position."))
            return
        await runtime.player.refresh_now_playing(message.chat.id)
        await rich.send(
            client,
            message.chat.id,
            f"{E('check')} <b>Removed</b> {rich.esc(track.short)}",
            reply_to=message.id,
        )

    @client.on_message(filters.command(["move", "reorder"]))
    async def _move(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        parts = command_args(message).split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await rich.send(client, message.chat.id, cards.warn_card("Usage: <code>/move 3 1</code>"))
            return
        ok = runtime.player.queues.move(message.chat.id, int(parts[0]), int(parts[1]))
        await runtime.player.refresh_now_playing(message.chat.id)
        await rich.send(
            client,
            message.chat.id,
            cards.ok_card("<b>Queue reordered</b>" if ok else "Those positions do not exist."),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["jump", "playpos"]))
    async def _jump(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        arg = command_args(message)
        if not arg.isdigit():
            await rich.send(client, message.chat.id, cards.warn_card("Usage: <code>/jump 2</code>"))
            return
        track = await runtime.player.jump(message.chat.id, int(arg))
        if not track:
            await rich.send(client, message.chat.id, cards.warn_card("No track at that position."))
            return
        await rich.react(message, "⏭")


__all__ = ["register"]
