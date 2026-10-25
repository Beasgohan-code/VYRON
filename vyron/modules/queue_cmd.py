# ---------------------------------------------------------------------------
#  VYRON — queue commands
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.ui.progress import fmt_duration
from vyron.ui.theme import E
from vyron.utils.helpers import command_args
from vyron.utils.commands import cmd


def register(client: Client) -> None:
    @client.on_message(cmd(["queue", "q"]))
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

    @client.on_message(cmd(["clearqueue", "clear"]))
    async def _clear(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        removed = runtime.player.queues.clear(message.chat.id, keep_current=True)
        await runtime.player.refresh_now_playing(message.chat.id)
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "queue cleared",
                glyph="check",
                label="removed",
                value=f"<b>{removed}</b> " + ("track" if removed == 1 else "tracks"),
                note="What is playing keeps playing — only the line behind it was emptied.",
                actions=B.row(
                    B.btn(f"{E('play')} Play something", data="v:help:playback", style="primary"),
                    B.btn(f"{E('now')} Now playing", data="v:np"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["remove"]))
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
            cards.change_card(
                "removed",
                glyph="check",
                label="track",
                value=f"<b>{rich.esc(track.title)}</b>",
                note=f"Position #{int(arg)} is gone; everything after it moved up one.",
                extra=[("clock", "length", f"<b>{fmt_duration(track.duration)}</b>")],
                actions=B.row(
                    B.btn(f"{E('queue')} Queue", data="v:queue", style="primary"),
                    B.btn(f"{E('now')} Now playing", data="v:np"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["move"]))
    async def _move(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        parts = command_args(message).split()
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            await rich.send(client, message.chat.id, cards.warn_card("Usage: <code>/move 3 1</code>"))
            return
        ok = runtime.player.queues.move(message.chat.id, int(parts[0]), int(parts[1]))
        await runtime.player.refresh_now_playing(message.chat.id)
        if not ok:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Those positions do not exist in this queue."),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "queue reordered",
                glyph="check",
                label="moved",
                value=f"<b>#{parts[0]}</b> → <b>#{parts[1]}</b>",
                note="The order is saved — a restart keeps it.",
                actions=B.row(
                    B.btn(f"{E('queue')} See the queue", data="v:queue", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["jump"]))
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
