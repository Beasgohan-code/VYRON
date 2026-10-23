# ---------------------------------------------------------------------------
#  VYRON — per-chat settings
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import cards, keyboards, rich


def register(client: Client) -> None:
    @client.on_message(filters.command(["settings", "panel", "prefs"]))
    async def _settings(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        state = await runtime.player.restore_settings(message.chat.id)
        cfg = {
            "volume": state.volume,
            "loop": state.loop.value,
            "autoplay": state.autoplay,
            "always_on": state.always_on,
        }
        await rich.send(
            client,
            message.chat.id,
            cards.settings_card(cfg, message.chat.title or ""),
            markup_keyboard=keyboards.settings_panel(cfg),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["247", "alwayson", "always"]))
    async def _always(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        state = runtime.player.queues.get(message.chat.id)
        state.always_on = not state.always_on
        await runtime.player.persist(message.chat.id)
        text = "enabled" if state.always_on else "disabled"
        await rich.send(
            client,
            message.chat.id,
            cards.ok_card(f"<b>24/7 mode {text}</b>"),
            reply_to=message.id,
        )


__all__ = ["register"]
