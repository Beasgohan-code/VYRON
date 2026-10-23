"""Log-channel tests: formatting, gating and the rate limit."""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from vyron.core import logsink
from vyron.core.journal import Event


def event(level: str = "warn", **meta) -> Event:
    return Event(
        seq=1,
        ts=time.time(),
        level=level,
        scope="player",
        message="stream start failed <in chat>",
        meta=meta,
    )


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(logsink, "settings", SimpleNamespace(logger_id=1234))
    logsink._sent.clear()
    monkeypatch.setattr(logsink, "_enabled", False)
    yield
    logsink._sent.clear()


def test_format_escapes_html():
    text = logsink.format_event(event(error="boom"))
    assert "&lt;in chat&gt;" in text
    assert "WARN" in text and "player" in text
    assert "error=boom" in text


def test_format_includes_a_traceback_for_errors():
    text = logsink.format_event(
        event(level="error", type="ValueError", traceback="Traceback: bad")
    )
    assert "Traceback: bad" in text
    assert "<pre>" in text
    # a warning never dumps a traceback
    assert "<pre>" not in logsink.format_event(event(level="warn", traceback="x"))


def test_channel_is_off_until_enabled(monkeypatch):
    assert logsink.is_enabled() is False
    monkeypatch.setattr(logsink, "_enabled", True)
    assert logsink.is_enabled() is True


def test_enabling_without_a_channel_stays_off(monkeypatch):
    monkeypatch.setattr(logsink, "settings", SimpleNamespace(logger_id=0))
    assert asyncio.run(logsink.set_enabled(None, True)) is False
    assert logsink.is_enabled() is False


def test_flag_is_persisted():
    class Storage:
        def __init__(self) -> None:
            self.meta: dict = {}

        async def set_meta(self, key, value):
            self.meta[key] = value

        async def get_meta(self, key, default=None):
            return self.meta.get(key, default)

    storage = Storage()

    assert asyncio.run(logsink.set_enabled(storage, True)) is True
    assert storage.meta[logsink._META] is True

    logsink._enabled = False
    assert asyncio.run(logsink.load(storage)) is True


def test_rate_limit_allows_twenty_then_stops():
    now = 1000.0
    allowed = [logsink._rate_limited(now) for _ in range(logsink._MAX_PER_MINUTE)]
    assert not any(allowed)
    assert logsink._rate_limited(now) is True
    # a minute later the bucket has drained
    assert logsink._rate_limited(now + 61) is False


def test_sink_ignores_info_when_enabled(monkeypatch):
    posted: list = []

    async def fake_deliver(payload):
        posted.append(payload)

    monkeypatch.setattr(logsink, "_enabled", True)
    monkeypatch.setattr(logsink, "_bot", object())
    logsink._deliver = fake_deliver  # type: ignore[assignment]

    logsink._sink(event(level="info"))
    assert posted == []
