"""The journal middleware: what is worth remembering, and what is noise."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

pytest.importorskip("aiohttp")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from vyron.core.journal import journal
from vyron.web.middleware import record_errors


@pytest.fixture()
def quiet_journal(monkeypatch):
    """Keep the shared journal's real ring buffer out of these assertions."""
    recorded: list[tuple[str, str]] = []

    def fake(level, scope, message, *args, **kwargs):
        recorded.append((level, message))

    monkeypatch.setattr(journal, "warn", lambda scope, message, *a, **k: fake("warn", scope, message))
    monkeypatch.setattr(journal, "error", lambda scope, message, *a, **k: fake("error", scope, message))
    return recorded


def test_slow_only_means_actually_slow(quiet_journal, monkeypatch):
    """A live log tail is long-lived by design; a stuck API call is not."""
    monkeypatch.setattr("vyron.web.middleware._SLOW_MS", 0)

    async def slow(request):
        await asyncio.sleep(0.05)
        return web.Response(text="ok")

    async def broken(request):
        raise RuntimeError("kaboom")

    app = web.Application(middlewares=[record_errors])
    app.router.add_get("/api/logs/stream", slow)
    app.router.add_get("/api/logs", slow)
    app.router.add_get("/api/thing", broken)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            assert (await client.get("/api/logs/stream")).status == 200
            assert quiet_journal == []                       # not "slow"
            assert (await client.get("/api/logs")).status == 200
            assert quiet_journal and "slow request" in quiet_journal[0][1]

            crash = await client.get("/api/thing")
            assert crash.status == 500
            assert any(level == "error" for level, _ in quiet_journal)
            assert any("crashed" in message for _, message in quiet_journal)
            # The line has to name the failure: Render's stream shows messages
            # only, so "GET /api/state crashed" on its own sent people digging.
            assert any("RuntimeError: kaboom" in message for _, message in quiet_journal)

    asyncio.run(scenario())


def test_boot_wait_is_configurable_and_never_negative():
    from vyron.config import settings

    assert dataclasses.replace(settings, boot_wait=3).boot_wait == 3
    assert settings.boot_wait >= 0
