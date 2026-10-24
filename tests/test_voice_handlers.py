"""Voice-chat event wiring must survive pytgcalls' filter API drift.

The Render crash of 2026-10-23 was `chat_update.__init__() missing 1 required
positional argument: 'flags'` — the filter class was instantiated with no
arguments, which aborted the whole boot. These tests build the real filters.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from vyron.core.player import Player


class FakeCalls:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.filters: list = []
        self.handlers: list = []

    def on_update(self, filter_obj):
        if self.fail:
            raise TypeError("boom")
        self.filters.append(filter_obj)

        def wrap(handler):
            self.handlers.append(handler)
            return handler

        return wrap


def _player(calls):
    from vyron.config import settings

    return Player(
        bot=None,
        calls=calls,
        settings=settings,
        storage=None,
        youtube=None,
    )


def test_chat_update_filter_is_built_with_flags():
    """`filters.chat_update` needs a Status mask — never call it bare."""
    filter_obj = Player._chat_update_filter()
    assert filter_obj is not None
    assert getattr(filter_obj, "flags", None) is not None


def test_register_handlers_wires_both_events():
    calls = FakeCalls()
    _player(calls).register_handlers()

    names = sorted(type(f).__name__ for f in calls.filters)
    assert names == ["chat_update", "stream_end"]
    assert len(calls.handlers) == 2


def test_a_failing_registration_does_not_raise():
    """A pytgcalls API change must cost the events, not the boot."""
    calls = FakeCalls(fail=True)
    _player(calls).register_handlers()  # must not raise
    assert calls.filters == []


def test_chat_update_status_accepts_an_enum_and_a_string():
    calls = FakeCalls()
    player = _player(calls)
    seen = []

    class Bot:
        async def send_message(self, *args, **kwargs):
            seen.append(kwargs)

    player.bot = Bot()

    enum_update = SimpleNamespace(
        chat_id=-1001,
        status=SimpleNamespace(name="CLOSED_VOICE_CHAT"),
    )
    import asyncio

    asyncio.run(player.on_chat_update(None, enum_update))
    # no current track: nothing to announce, but no exception either
    assert player.queues.get(-1001).current is None

    string_update = SimpleNamespace(chat_id=-1002, status="kicked")
    asyncio.run(player.on_chat_update(None, string_update))
    assert player.queues.get(-1002).current is None


@pytest.mark.parametrize("name", ["KICKED", "CLOSED_VOICE_CHAT", "LEFT_GROUP", "DISCARDED_CALL"])
def test_every_call_end_flag_exists(name):
    from pytgcalls.types import ChatUpdate

    assert getattr(ChatUpdate.Status, name, None) is not None
