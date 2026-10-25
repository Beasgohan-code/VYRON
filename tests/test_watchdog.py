"""Keep-alive pings and the connection watchdog, with fake clients."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import dataclasses

import pytest

from vyron.config import Settings
from vyron.core import keepalive, watchdog


def cfg(module, **overrides):
    """Swap a module's frozen Settings for a patched copy."""
    module.settings = dataclasses.replace(Settings(), **overrides)
    return module.settings


class FakeRuntime:
    def __init__(self, *, streaming=False, bot=None, assistant=None):
        self.streaming_ready = streaming
        self.bot = bot
        self.assistant = assistant
        self.handlers_loaded = []


# ── keep-alive ─────────────────────────────────────────────────────────────
def test_base_url_prefers_explicit_setting():
    cfg(keepalive, keepalive_url="https://vyron.example/", webapp_url="https://web.example")
    assert keepalive.base_url() == "https://vyron.example"


def test_base_url_falls_back_to_webapp_url():
    cfg(keepalive, keepalive_url="", webapp_url="https://vyron.onrender.com")
    assert keepalive.base_url() == "https://vyron.onrender.com"


def test_ping_hits_health_and_the_webapp():
    calls: list[str] = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def read(self):
            return b"{}"

    class FakeSession:
        def get(self, url):
            calls.append(url)
            return FakeResponse()

        async def close(self):
            return None

    ok = asyncio.run(
        keepalive.ping("https://vyron.example", session=FakeSession())
    )
    assert ok is True
    assert calls == ["https://vyron.example/health", "https://vyron.example/app/"]
    assert keepalive.status()["runs"] >= 1


def test_ping_without_a_url_is_a_noop(monkeypatch):
    cfg(keepalive, keepalive_url="", webapp_url="")
    monkeypatch.setattr(keepalive, "base_url", lambda: "")
    assert asyncio.run(keepalive.ping()) is False


def test_start_is_disabled_without_a_url(monkeypatch):
    cfg(keepalive, keepalive_url="", webapp_url="")
    monkeypatch.setattr(keepalive, "base_url", lambda: "")
    assert keepalive.start() is None


def test_start_is_disabled_when_minutes_is_zero(monkeypatch):
    cfg(keepalive, keepalive_minutes=0, webapp_url="https://vyron.example")

    async def scenario():
        await keepalive.stop()
        assert keepalive.start() is None

    asyncio.run(scenario())


# ── watchdog ───────────────────────────────────────────────────────────────
class FakeClient:
    def __init__(self, connected=True, me_raises=False):
        self.is_connected = connected
        self.me_raises = me_raises
        self.stops = 0
        self.starts = 0

    async def stop(self):
        self.stops += 1
        self.is_connected = False

    async def start(self):
        self.starts += 1
        self.is_connected = True

    async def get_me(self):
        if self.me_raises:
            raise TimeoutError("no answer from telegram")
        return SimpleNamespace(id=1, username="vyron_bot")


def test_healthy_bot_needs_no_repair():
    bot = FakeClient()
    problems = asyncio.run(watchdog.check_once(bot=bot, assistant=None))
    assert problems == []
    assert bot.stops == 0


def test_disconnected_bot_is_reconnected():
    bot = FakeClient(connected=False)
    problems = asyncio.run(watchdog.check_once(bot=bot, assistant=None))
    assert "bot disconnected" in problems
    assert bot.stops == 1 and bot.starts == 1
    assert watchdog.status()["reconnects"] >= 1


def test_one_timeout_is_tolerated_but_two_reconnect(monkeypatch):
    monkeypatch.setattr(watchdog, "runtime", FakeRuntime(streaming=False))
    bot = FakeClient(me_raises=True)

    first = asyncio.run(watchdog.check_once(bot=bot, assistant=None))
    assert first and first[0].startswith("get_me")
    assert bot.stops == 0  # single hiccup

    asyncio.run(watchdog.check_once(bot=bot, assistant=None))
    assert bot.stops >= 1  # second failure triggers a reconnect


def test_assistant_is_only_checked_when_streaming(monkeypatch):
    assistant = FakeClient(connected=False)

    monkeypatch.setattr(watchdog, "runtime", FakeRuntime(streaming=False, assistant=assistant))
    assert asyncio.run(watchdog.check_once(bot=FakeClient(), assistant=assistant)) == []
    assert assistant.stops == 0

    monkeypatch.setattr(watchdog, "runtime", FakeRuntime(streaming=True, assistant=assistant))
    problems = asyncio.run(watchdog.check_once(bot=FakeClient(), assistant=assistant))
    assert "assistant disconnected" in problems
    assert assistant.starts == 1


def test_watchdog_can_reregister_handlers_after_a_reconnect():
    bot = FakeClient(connected=False)
    seen = {}

    def handlers(client):
        seen["client"] = client
        return ["start", "play"]

    fake = FakeRuntime()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(watchdog, "runtime", fake)
    try:
        asyncio.run(watchdog.check_once(bot=bot, assistant=None, collect_handlers=handlers))
    finally:
        monkeypatch.undo()
    # handlers are only rebuilt on a get_me failure, not on a plain reconnect
    assert seen == {}


def test_start_and_stop_are_idempotent():
    cfg(watchdog, watchdog_seconds=60)

    async def scenario():
        first = watchdog.start()
        second = watchdog.start()
        assert first is second
        await watchdog.stop()
        assert watchdog.start() is not None
        await watchdog.stop()

    asyncio.run(scenario())


def test_watchdog_disabled_with_zero_seconds():
    cfg(watchdog, watchdog_seconds=0)

    async def scenario():
        await watchdog.stop()
        assert watchdog.start() is None

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [0, -5])
def test_status_reports_configuration(value):
    cfg(watchdog, watchdog_seconds=value)
    assert watchdog.status()["enabled"] is (value > 0)
