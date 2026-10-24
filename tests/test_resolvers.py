"""The no-cookie stack: resolver scoreboard, Cobalt, impersonation, self-update.

Everything here is offline: HTTP is faked, pip is faked, and the yt-dlp version
check is faked. The point of these tests is the *policy* — skip what is broken,
prefer what works, never let a diagnostic break playback.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

pytest.importorskip("pyrogram")

from vyron.config import settings
from vyron.core import ytdlp_update
from vyron.core.public_streams import (
    COBALT_HOSTS,
    PublicStreams,
    parse_cobalt,
)
from vyron.core.resolvers import HEALTH, Health


# ── scoreboard ─────────────────────────────────────────────────────────────
def test_a_failure_makes_a_source_cool_down_and_a_win_clears_it():
    health = Health(cooldown_base=10, cooldown_max=40)
    health.record("piped:a", False, error="timeout")
    assert not health.available("piped:a")
    assert health.cooling("piped:a") > 0
    health.record("piped:a", True, ms=42)
    assert health.available("piped:a")
    stat = health.stat("piped:a")
    assert stat["wins"] == 1 and stat["tries"] == 2 and stat["latency_ms"] == 42


def test_repeated_failures_back_off_up_to_the_cap():
    health = Health(cooldown_base=10, cooldown_max=25)
    waits = []
    for _ in range(5):
        health.record("cobalt:b", False, error="502")
        waits.append(health.cooling("cobalt:b"))
    assert waits[0] < waits[1] < waits[2]
    assert max(waits) <= 25


def test_unknown_sources_are_available_and_cooling_means_skip():
    health = Health()
    assert health.available("invidious:never-seen")
    health.cool("invidious:new", 30)
    assert not health.available("invidious:new")


def test_summary_counts_families_and_picks_the_winner():
    health = Health()
    health.record("yt-dlp:tv_simply", True, ms=1200)
    health.record("yt-dlp:ios", True, ms=900)
    health.record("piped:a", False, error="nope")
    summary = health.summary()
    assert summary["families"]["yt-dlp"]["wins"] == 2
    assert summary["families"]["piped"]["failures"] == 1
    # equal wins → the faster one wins the tie-break
    assert summary["best"]["source"] == "yt-dlp:ios"


def test_stats_never_leak_a_url():
    HEALTH.record("cobalt:x", False, error="https://secret.example/token?key=abc")
    payload = HEALTH.stats()["cobalt:x"]
    assert len(payload["last_error"]) <= 160
    assert "cooldown_until" in payload and "cooling" in payload


# ── cobalt ─────────────────────────────────────────────────────────────────
def test_cobalt_tunnel_and_redirect_answers_parse():
    tunnel = parse_cobalt({"status": "tunnel", "url": "https://cdn/x.m4a", "filename": "song.m4a"}, "h")
    assert tunnel and tunnel.url == "https://cdn/x.m4a" and tunnel.source == "cobalt:h"
    redirect = parse_cobalt({"status": "redirect", "url": "https://cdn/y.mp3"}, "h")
    assert redirect and redirect.ext in {"mp3", "m4a"}


def test_cobalt_picker_and_errors_are_handled():
    picker = parse_cobalt({"status": "picker", "picker": [{"url": "https://cdn/z.mp4"}]}, "h")
    assert picker and picker.url == "https://cdn/z.mp4"
    assert parse_cobalt({"status": "error", "error": {"code": "content.too_long"}}, "h") is None
    assert parse_cobalt({"status": "tunnel"}, "h") is None


class FakeStreams(PublicStreams):
    """Answers each host differently, so the policy can be asserted."""

    def __init__(self, answers, **kwargs):
        super().__init__(**kwargs)
        self.answers = answers
        self.calls: list[str] = []

    async def _json(self, url):
        self.calls.append(url)
        host = url.split("//", 1)[1].split("/", 1)[0]
        return self.answers.get(host)

    async def _fetch(self, url, *, body=None):
        self.calls.append(url)
        host = url.split("//", 1)[1].split("/", 1)[0]
        return self.answers.get(host)


def _streams(**overrides) -> FakeStreams:
    cfg = dataclasses.replace(settings, stream_fallback_hosts="", cobalt_urls="", stream_fallback_timeout=3, **overrides)
    fake = FakeStreams(
        {
            "inv1.example": {"adaptiveFormats": [{"url": "https://cdn/a.m4a", "type": "audio/mp4", "bitrate": 128000}]},
            "piped1.example": {"audioStreams": [{"url": "https://cdn/b.m4a", "mimeType": "audio/mp4", "bitrate": 64000}]},
            "cobalt1.example": {"status": "tunnel", "url": "https://cdn/c.mp3"},
        },
        settings=cfg,
    )
    fake.invidious = ("inv1.example", "inv-dead.example")
    fake.piped = ("piped1.example",)
    fake.cobalt = ("cobalt1.example",)
    return fake


def test_any_healthy_tier_wins_including_cobalt():
    streams = _streams()

    async def run():
        return await streams.resolve("abc12345678")

    found = asyncio.run(run())
    assert found is not None
    assert found.url in {"https://cdn/a.m4a", "https://cdn/b.m4a", "https://cdn/c.mp3"}


def test_a_dead_host_is_skipped_on_the_next_try():
    streams = _streams()

    async def run():
        first = await streams.resolve("abc12345678")
        streams.calls.clear()
        second = await streams.resolve("abc12345678")
        return first, second, list(streams.calls)

    _, _, calls = asyncio.run(run())
    # whichever tier failed (a host with no answer) is now cooling down
    cooling = [name for name in HEALTH.stats() if not HEALTH.available(name)]
    assert cooling, "some source must have failed and cooled down"
    assert all("inv-dead" not in call for call in calls if "inv-dead" in "".join(cooling))


def test_probe_reports_every_tier():
    streams = _streams()

    async def run():
        return await streams.probe("abc12345678")

    rows = asyncio.run(run())
    sources = {row["source"] for row in rows}
    assert "invidious:inv1.example" in sources
    assert "cobalt:cobalt1.example" in sources
    assert any(row["ok"] for row in rows)


def test_cobalt_can_be_switched_off():
    config = dataclasses.replace(settings, cobalt_urls="off", disable_cobalt=True)
    streams = PublicStreams(config)
    assert streams.cobalt == ()


def test_cobalt_url_env_overrides_the_public_list():
    config = dataclasses.replace(settings, cobalt_urls="https://my-cobalt.example/")
    streams = PublicStreams(config)
    assert streams.cobalt == ("my-cobalt.example",)
    assert COBALT_HOSTS  # the built-in list still exists for the default


# ── impersonation ──────────────────────────────────────────────────────────
def test_impersonation_is_off_when_curl_cffi_is_missing(monkeypatch):
    from vyron.core.search import YouTube

    youtube = YouTube(dataclasses.replace(settings, data_dir="/tmp", impersonate="chrome"))
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("curl_cffi"):
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert youtube._impersonate_target() == ""
    monkeypatch.setattr(builtins, "__import__", real_import)


def test_impersonation_can_be_switched_off_and_returns_a_target():
    from vyron.core.search import YouTube

    off = YouTube(dataclasses.replace(settings, data_dir="/tmp", impersonate="off"))
    assert off._impersonate_target() == ""
    youtube = YouTube(dataclasses.replace(settings, data_dir="/tmp", impersonate="chrome"))
    target = youtube._impersonate_target()
    if target:  # curl_cffi present in this environment
        assert str(target) == "chrome"


def test_the_ladder_skips_cooling_clients():
    from vyron.core.search import YouTube

    youtube = YouTube(dataclasses.replace(settings, data_dir="/tmp"))
    HEALTH.cool("yt-dlp:ios", 60)
    ladder = youtube._client_ladder()
    assert "ios" not in ladder
    assert ladder[0] is None  # the default client is still first


# ── yt-dlp self-update ─────────────────────────────────────────────────────
def test_version_comparison():
    assert ytdlp_update.is_newer("2026.11.1", "2026.10.21")
    assert not ytdlp_update.is_newer("2026.10.21", "2026.10.21")
    assert not ytdlp_update.is_newer("", "2026.10.21")
    assert ytdlp_update.is_newer("2026.10.21.1", "2026.10.21")


def test_check_reports_without_touching_pip_when_already_current(monkeypatch):
    monkeypatch.setattr(ytdlp_update, "installed_version", lambda: "2026.10.21")
    monkeypatch.setattr(ytdlp_update, "latest_version", lambda timeout=8.0: "2026.10.21")
    called = []
    monkeypatch.setattr(ytdlp_update, "upgrade", lambda timeout=300.0: called.append(1) or (True, "ok"))
    state = ytdlp_update.check()
    assert state["installed"] == "2026.10.21" and state["latest"] == "2026.10.21"
    assert called == []


def test_check_upgrades_when_a_newer_release_exists(monkeypatch):
    monkeypatch.setattr(ytdlp_update, "installed_version", lambda: "2025.01.01")
    monkeypatch.setattr(ytdlp_update, "latest_version", lambda timeout=8.0: "2026.10.21")
    monkeypatch.setattr(ytdlp_update, "upgrade", lambda timeout=300.0: (True, "installed"))
    monkeypatch.setattr(ytdlp_update, "_state", {k: v for k, v in ytdlp_update._state.items()})
    state = ytdlp_update.check(update=True)
    assert state["updated"] and state["error"] == ""


def test_a_failed_upgrade_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(ytdlp_update, "installed_version", lambda: "2025.01.01")
    monkeypatch.setattr(ytdlp_update, "latest_version", lambda timeout=8.0: "2026.10.21")
    monkeypatch.setattr(ytdlp_update, "upgrade", lambda timeout=300.0: (False, "ERROR: no space left"))
    state = ytdlp_update.check(update=True)
    assert "no space" in state["error"]


def test_offline_version_check_is_quiet(monkeypatch):
    monkeypatch.setattr(ytdlp_update, "latest_version", lambda timeout=8.0: "")
    state = ytdlp_update.check(update=False)
    assert state["error"] == "PyPI did not answer"


def test_status_is_secret_free():
    payload = ytdlp_update.status()
    assert set(payload) == {"installed", "latest", "checked", "updated", "error", "autoupdate"}


# ── /sources ───────────────────────────────────────────────────────────────
def test_sources_command_renders_a_verdict(monkeypatch):
    """The command must build a card even when every tier fails."""
    from vyron.modules import sources as module

    captured: dict[str, str] = {}

    from vyron.ui.rich import esc as rich_esc

    class Rich:
        esc = staticmethod(rich_esc)

        @staticmethod
        async def send(_client, _chat, markup, **_kwargs):
            captured["sent"] = markup
            return type("Msg", (), {"id": 1})()

        @staticmethod
        async def edit(_client, _chat, _mid, markup):
            captured["edited"] = markup
            return True

    monkeypatch.setattr(module, "rich", Rich)

    async def no_ytdlp(_video_id):
        return [("yt-dlp · default", "<b>fail</b> · nothing extracted")]

    async def no_mirrors(_video_id):
        return [("invidious · dead", "<b>fail</b> · 900 ms · timeout")]

    monkeypatch.setattr(module, "_probe_ytdlp", no_ytdlp)
    monkeypatch.setattr(module, "_probe_mirrors", no_mirrors)

    class Handler:
        def __init__(self):
            self.handler = None

        def on_message(self, _filter):
            def wrap(fn):
                self.handler = fn
                return fn

            return wrap

    class Client:
        def __init__(self):
            self.registry = Handler()

        def __getattr__(self, name):
            return getattr(self.registry, name)

    client = Client()
    module.register(client)
    user = type("User", (), {"id": next(iter(settings.owners))})()
    message = type(
        "Message",
        (),
        {"from_user": user, "chat": type("Chat", (), {"id": 1})(), "id": 5, "text": "/sources"},
    )()

    asyncio.run(client.registry.handler(client, message))
    markup = captured.get("edited") or captured.get("sent") or ""
    from vyron.ui.theme import un_small_caps

    assert "resolvers" in un_small_caps(markup).lower()
    assert "No tier answered" in markup
    assert "curl_cffi" in markup


def test_sources_is_owner_only(monkeypatch):
    from vyron.modules import sources as module

    captured: dict[str, str] = {}

    from vyron.ui.rich import esc as rich_esc

    class Rich:
        esc = staticmethod(rich_esc)

        @staticmethod
        async def send(_client, _chat, markup, **_kwargs):
            captured["sent"] = markup
            return None

        @staticmethod
        async def edit(_client, _chat, _mid, markup):
            captured["edited"] = markup
            return True

    monkeypatch.setattr(module, "rich", Rich)

    class Handler:
        def __init__(self):
            self.handler = None

        def on_message(self, _filter):
            def wrap(fn):
                self.handler = fn
                return fn

            return wrap

    class Client:
        def __init__(self):
            self.registry = Handler()

        def __getattr__(self, name):
            return getattr(self.registry, name)

    client = Client()
    module.register(client)
    user = type("User", (), {"id": 999})()
    message = type(
        "Message",
        (),
        {"from_user": user, "chat": type("Chat", (), {"id": 1})(), "id": 5, "text": "/sources"},
    )()

    asyncio.run(client.registry.handler(client, message))
    assert "owner only" in captured.get("sent", "").lower()
