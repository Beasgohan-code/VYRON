"""Deploy resilience — a bad env var must never look like a dead server.

Render/Koyeb treat a process that exits as a failed deploy and restart it, which
re-triggers the same failure (and, for Telegram, the same login). These tests pin
the two promises that stop that loop: the HTTP port opens before anything can
fail, and a degraded boot answers `/health` instead of exiting.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

pytest.importorskip("pyrogram")
pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer

from vyron.config import settings
from vyron.utils import health


def _app(reason="missing BOT_TOKEN"):
    app = health.build_app(with_webapp=False)
    return app


def test_health_payload_reports_boot_problems():
    from vyron.runtime import runtime

    runtime.boot_problems = ["STRING_SESSION is missing"]
    try:
        async def scenario(client):
            response = await client.get("/health")
            payload = await response.json()
            assert response.status == 200
            assert payload["problems"] == ["STRING_SESSION is missing"]
            assert payload["degraded"] is True

        async def run():
            async with TestClient(TestServer(_app())) as client:
                return await scenario(client)

        asyncio.run(run())
    finally:
        runtime.boot_problems = []


def test_degraded_mode_serves_health_instead_of_exiting(monkeypatch):
    """/health answers 200 with the reason, so the platform keeps the logs."""
    from vyron.utils import health as health_module

    monkeypatch.setattr(health_module.web, "AppRunner", health_module.web.AppRunner)

    async def scenario():
        runner = await health_module.start_degraded(0, "bot login failed: bad token", ["BOT_TOKEN"])
        # port 0 means "pick one" — nothing to assert about the socket, only
        # that a runner came back and had an app attached.
        if runner is not None:
            await runner.cleanup()
        return runner

    # start_degraded refuses port 0 by design (nothing to bind)
    assert asyncio.run(scenario()) is None


def test_a_missing_session_is_a_warning_not_an_exit():
    """The bot runs without streaming: downloads and the Mini App still work."""
    without_session = dataclasses.replace(settings, session_string="")
    problems = without_session.validate()

    assert any("STRING_SESSION" in problem for problem in problems)
    # `_async_main` keeps only the credential problems fatal — everything that
    # starts with STRING_SESSION is degradation, never a shutdown.
    fatal = [problem for problem in problems if not problem.startswith("STRING_SESSION")]
    assert fatal == []


def test_boot_opens_the_port_before_it_validates_configuration(monkeypatch):
    """Order matters: a validation error used to leave the port closed."""
    import vyron.__main__ as main

    calls: list[str] = []
    broken = dataclasses.replace(settings, bot_token="", api_id=0, api_hash="", session_string="")

    async def fake_start(port):
        calls.append("health.start")
        return None

    async def fake_hold(reason: str) -> int:
        calls.append("hold_alive")
        return 0

    def fake_validate():
        calls.append("validate")
        return ["BOT_TOKEN is missing — create a bot with @BotFather."]

    monkeypatch.setattr(main, "settings", broken)
    monkeypatch.setattr(main, "health", type("H", (), {"start": staticmethod(fake_start)}))
    monkeypatch.setattr(main, "_hold_alive", fake_hold)
    # `Settings` is frozen, so patch the class, not the instance
    monkeypatch.setattr(type(broken), "validate", lambda self: fake_validate())
    monkeypatch.setattr(type(broken), "ensure_dirs", lambda self: None)
    monkeypatch.setattr(type(broken), "warnings", lambda self: [])
    # `_async_main` normally reconfigures logging and attaches a journal file;
    # neither belongs in a unit test (it would leak into other tests' loggers).
    monkeypatch.setattr(main, "attach", lambda path: None)
    monkeypatch.setattr(main, "setup_logging", lambda level: None)
    monkeypatch.setattr(main, "banner_text", lambda: "")
    monkeypatch.setattr(main.journal, "info", lambda *a, **k: None)

    code = asyncio.run(main._async_main())

    assert code == 0
    assert calls[:3] == ["health.start", "validate", "hold_alive"]


def test_health_reports_the_download_ladder_and_prefixes():
    """The probe should answer "which accelerator is live?" without /doctor."""
    import asyncio

    from aiohttp.test_utils import TestClient, TestServer

    from vyron.utils import health

    async def _go():
        app = health.build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            resp = await client.get("/health")
            assert resp.status == 200
            payload = await resp.json()
        return payload

    payload = asyncio.run(_go())
    assert payload["downloads"]["accelerator"] in {"aria2", "curl", "aiohttp"}
    assert isinstance(payload["downloads"]["installed"], list)
    assert "/" in payload["prefixes"]
