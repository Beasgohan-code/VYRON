# ---------------------------------------------------------------------------
#  VYRON — lyrics, favourites & history
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core.lyrics import split_title
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args


def register(client: Client) -> None:
    @client.on_message(filters.command(["lyrics"]))
    async def _lyrics(_: Client, message: Message) -> None:
        if not runtime.lyrics:
            return
        query = command_args(message)
        state = runtime.player.queues.get(message.chat.id) if runtime.player else None
        current = state.current if state else None

        if not query and not current:
            await rich.send(client, message.chat.id, cards.warn_card("Play something or give me a song name."))
            return

        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} <b>Looking up lyrics…</b>",
            reply_to=message.id,
        )
        if current and not query:
            title, artist = split_title(current.title), current.uploader
            result = await runtime.lyrics.timed(title[0], artist or title[1], current.duration)
            track_for_card = current
        else:
            needle = query
            parts = split_title(needle)
            if parts[1]:
                result = await runtime.lyrics.find(parts[0], parts[1])
            else:
                result = await runtime.lyrics.find(needle)
            track_for_card = current or type("T", (), {"title": needle})()

        if status:
            await rich.edit(client, message.chat.id, status.id, cards.lyrics_card(track_for_card, result))

    @client.on_message(filters.command(["fav", "save"]))
    async def _fav(_: Client, message: Message) -> None:
        if not runtime.player or not runtime.storage:
            return
        state = runtime.player.queues.get(message.chat.id)
        if not state.current:
            await rich.send(client, message.chat.id, cards.warn_card("Nothing is playing to save."))
            return
        added = await runtime.storage.add_favorite(message.from_user.id, state.current.to_dict())
        if added:
            await rich.react(message, "❤️")
            await rich.send(
                client,
                message.chat.id,
                f"{E('favorite')} <b>Saved</b> {rich.esc(truncate(state.current.title, 48))}",
            )
        else:
            await rich.send(client, message.chat.id, cards.warn_card("Already in your favourites."))

    @client.on_message(filters.command(["favorites"]))
    async def _favs(_: Client, message: Message) -> None:
        if not runtime.storage:
            return
        items = await runtime.storage.favorites(message.from_user.id, limit=10)
        await rich.send(client, message.chat.id, cards.favorites_card(items), reply_to=message.id)

    @client.on_message(filters.command(["history"]))
    async def _history(_: Client, message: Message) -> None:
        if not runtime.storage:
            return
        items = await runtime.storage.history(message.from_user.id, limit=10)
        await rich.send(client, message.chat.id, cards.history_card(items), reply_to=message.id)


__all__ = ["register"]
