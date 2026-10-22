"""Offline smoke tests: clients build, handlers register, keyboards render."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("pyrogram")

from vyron.clients import build_assistant, build_bot
from vyron.config import settings
from vyron.core.queue import ChatState, LoopMode, Track
from vyron.modules import MODULES, register_all
from vyron.runtime import runtime
from vyron.ui import keyboards


def test_clients_build_offline():
    bot = build_bot(settings)
    assert bot.name == settings.session_name
    assert bot.parse_mode.name == "HTML"
    # no STRING_SESSION in tests → assistant must be None
    assert build_assistant(settings) is None


def test_handlers_register_offline():
    async def scenario():
        bot = build_bot(settings)
        runtime.bot = bot
        loaded = register_all(bot)
        await asyncio.sleep(0.1)  # pyrogram attaches handlers via loop tasks
        return bot, loaded

    bot, loaded = asyncio.run(scenario())
    assert len(loaded) == len(MODULES)
    for required in ("start", "play", "controls", "callbacks", "moderation", "locks", "effects_cmd", "inline"):
        assert required in loaded
    assert len(bot.dispatcher.groups) >= 1
    total = sum(len(group) for group in bot.dispatcher.groups.values())
    assert total > 20


def test_streaming_not_ready_without_assistant():
    runtime.assistant = None
    runtime.calls = None
    assert runtime.streaming_ready is False


def test_keyboards_render_buttons():
    state = ChatState(
        chat_id=1,
        current=Track(id="a", title="T", duration=100),
        playing=True,
        loop=LoopMode.ALL,
        volume=80,
    )
    markup = keyboards.now_playing(state)
    callbacks = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert "v:pause" in callbacks
    assert "v:skip" in callbacks
    assert "v:stop" in callbacks
    assert all(cb.startswith("v:") for cb in callbacks)

    paused = keyboards.now_playing(ChatState(chat_id=1, playing=True, paused=True))
    texts = [b.text for row in paused.inline_keyboard for b in row]
    assert any("Resume" in text for text in texts)


def test_settings_panel_reflects_state():
    markup = keyboards.settings_panel({"loop": "all", "autoplay": True, "always_on": False})
    flat = [b.text for row in markup.inline_keyboard for b in row]
    assert any("All" in text for text in flat)
    assert any("On" in text for text in flat)
