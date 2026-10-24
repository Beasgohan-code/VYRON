# ---------------------------------------------------------------------------
#  VYRON — playback controls
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.types import Message

from vyron.core.queue import LoopMode
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, nowplaying, rich
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, parse_seek
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)


def _player():
    return runtime.require_player()


def register(client: Client) -> None:
    async def _guard(message: Message) -> bool:
        if not runtime.player:
            await rich.send(message._client, message.chat.id, cards.error_card("Player is not ready yet."))
            return False
        return True

    @client.on_message(cmd(["pause"]))
    async def _pause(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        chat_id = message.chat.id
        if await _player().pause(chat_id):
            await rich.react(message, "👍")
        else:
            await rich.send(message._client, chat_id, cards.warn_card("Nothing is playing right now."))

    @client.on_message(cmd(["resume"]))
    async def _resume(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        if await _player().resume(message.chat.id):
            await rich.react(message, "🔥")
        else:
            await rich.send(message._client, message.chat.id, cards.warn_card("That track is not paused."))

    @client.on_message(cmd(["skip"]))
    async def _skip(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        count = 1
        arg = command_args(message)
        if arg.isdigit():
            count = max(1, min(20, int(arg)))
        track = await _player().skip(message.chat.id, count=count)
        if track is None:
            await rich.send(message._client, message.chat.id, cards.warn_card("Queue is empty — nothing to skip to."))
        else:
            await rich.react(message, "⏭")

    @client.on_message(cmd(["stop"]))
    async def _stop(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        await _player().stop(message.chat.id, leave=True)
        await rich.send(
            message._client,
            message.chat.id,
            cards.ok_card("<b>Stopped</b> — left the voice chat and cleared the queue."),
        )

    @client.on_message(cmd(["seek"]))
    async def _seek(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        state = _player().queues.get(message.chat.id)
        if not state.current:
            await rich.send(message._client, message.chat.id, cards.warn_card("Nothing is playing."))
            return
        command = message.command[0].lower()
        arg = command_args(message) or ("-15" if command == "rewind" else "+15")
        target = parse_seek(arg, state.elapsed(), state.current.duration or 0)
        await _player().seek(message.chat.id, target)
        await rich.react(message, "👍")

    @client.on_message(cmd(["volume"]))
    async def _volume(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        state = _player().queues.get(message.chat.id)
        arg = command_args(message)
        if not arg:
            await rich.send(
                message._client,
                message.chat.id,
                f"{E('volume')} <b>Volume</b> <code>{state.volume}%</code>",
            )
            return
        if arg[0] in "+-" and arg[1:].isdigit():
            value = state.volume + (int(arg[1:]) if arg[0] == "+" else -int(arg[1:]))
        elif arg.isdigit():
            value = int(arg)
        else:
            await rich.send(message._client, message.chat.id, cards.warn_card("Use a number between 1 and 200."))
            return
        volume = await _player().set_volume(message.chat.id, value)
        await rich.react(message, "👍")
        await rich.send(
            message._client,
            message.chat.id,
            f"{E('volume')} <b>Volume set</b> <code>{volume}%</code>",
        )

    @client.on_message(cmd(["loop"]))
    async def _loop(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        state = _player().queues.get(message.chat.id)
        arg = command_args(message).lower()
        state.loop = LoopMode.parse(arg) if arg in {"off", "one", "all"} else state.loop.next()
        await _player().persist(message.chat.id)
        await _player().refresh_now_playing(message.chat.id)
        await rich.send(
            message._client,
            message.chat.id,
            f"{E('loop')} <b>Loop</b> <code>{state.loop.label}</code>",
        )

    @client.on_message(cmd(["shuffle"]))
    async def _shuffle(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        count = _player().queues.shuffle(message.chat.id)
        await _player().refresh_now_playing(message.chat.id)
        await rich.send(
            message._client,
            message.chat.id,
            f"{E('shuffle')} <b>Shuffled</b> <code>{count}</code> queued tracks",
        )

    @client.on_message(cmd(["autoplay"]))
    async def _autoplay(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        from vyron.core import autoplay as auto
        from vyron.core import chatcfg

        state = _player().queues.get(message.chat.id)
        parts = (message.text or "").split(maxsplit=2)
        option = parts[1].strip().lower() if len(parts) > 1 else ""
        value = parts[2].strip().lower() if len(parts) > 2 else ""
        chat_id = message.chat.id
        client_ = message._client

        def _status() -> str:
            lane = auto.describe(state.mood, state.language) or "no lane — anything goes"
            return (
                B.banner("autoplay", glyph="spark")
                + B.kv(
                    [
                        ("state", "<b>on</b>" if state.autoplay else "<b>off</b>"),
                        ("mood", f"<b>{state.mood or '–'}</b>"),
                        ("language", f"<b>{state.language or '–'}</b>"),
                        ("lane", lane),
                    ]
                )
            )

        if not option:  # bare /autoplay keeps the old toggle behaviour
            state.autoplay = not state.autoplay
            await _player().persist(chat_id)
            await rich.send(
                client_,
                chat_id,
                f"{E('spark')} <b>Autoplay</b> <code>{'on' if state.autoplay else 'off'}</code>",
            )
            return

        if option == "status":
            await rich.send(client_, chat_id, _status())
            return

        if option == "mood":
            if not value:
                moods = " · ".join(f"<code>{name}</code>" for name in auto.MOODS)
                await rich.send(
                    client_,
                    chat_id,
                    cards.info_card(f"Pick a mood: {moods}\nOr clear it with <code>/autoplay mood off</code>."),
                )
                return
            if value in {"off", "none", "clear", "any"}:
                state.mood = ""
            elif value in auto.MOODS:
                state.mood = value
            else:
                await rich.send(
                    client_,
                    chat_id,
                    cards.warn_card(f"Unknown mood — try {', '.join(sorted(auto.MOODS))}."),
                )
                return
            await _player().persist(chat_id)
            await chatcfg.set(chat_id, "autoplay_mood", state.mood)
            await rich.send(client_, chat_id, _status())
            return

        if option in {"lang", "language"}:
            if not value:
                codes = " · ".join(f"<code>{name}</code>" for name in auto.LANGUAGES)
                await rich.send(
                    client_,
                    chat_id,
                    cards.info_card(f"Pick a language: {codes}\nOr clear it with <code>/autoplay lang off</code>."),
                )
                return
            if value in {"off", "none", "clear", "any"}:
                state.language = ""
            elif value in auto.LANGUAGES:
                state.language = value
            else:
                await rich.send(
                    client_,
                    chat_id,
                    cards.warn_card(f"Unknown language — try {', '.join(sorted(auto.LANGUAGES))}."),
                )
                return
            await _player().persist(chat_id)
            await chatcfg.set(chat_id, "autoplay_language", state.language)
            await rich.send(client_, chat_id, _status())
            return

        if option in {"on", "off"}:
            state.autoplay = option == "on"
            await _player().persist(chat_id)
            await rich.send(client_, chat_id, _status())
            return

        await rich.send(
            client_,
            chat_id,
            cards.info_card("<code>/autoplay</code> toggles · "
                "<code>/autoplay mood chill</code> · <code>/autoplay lang malayalam</code> · "
                "<code>/autoplay status</code>"),
        )

    @client.on_message(cmd(["np"]))
    async def _np(_: Client, message: Message) -> None:
        if not await _guard(message):
            return
        state = _player().queues.get(message.chat.id)
        if not state.current:
            await rich.send(message._client, message.chat.id, cards.warn_card("Nothing is playing right now."))
            return
        keyboard = keyboards.now_playing(state)
        # The generated poster, with the live clock as its caption. Falls back
        # to the text card when Pillow (or the render) is unavailable.
        # Same code path as the auto-posted poster, so `/np` shows the chat's
        # own artwork and hits the same memoised render.
        art = (
            await nowplaying.poster(
                state, state.current, bot=message._client, chat_id=message.chat.id
            )
            if await nowplaying.allowed(message.chat.id)
            else None
        )
        if art:
            sent = await rich.send_photo(
                message._client,
                message.chat.id,
                art,
                cards.now_playing_caption(state),
                markup_keyboard=keyboard,
                reply_to=message.id,
            )
            if sent is not None:
                return

        await rich.send(
            message._client,
            message.chat.id,
            cards.now_playing_card(state),
            markup_keyboard=keyboard,
            reply_to=message.id,
        )


__all__ = ["register"]
