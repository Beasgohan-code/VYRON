"""Two safety nets: URLs that point at the host, and secrets in log lines."""
from __future__ import annotations

import asyncio
import logging

import pytest

from vyron.core import urlguard
from vyron.core.redact import RedactFilter, scrub


# ── SSRF guard ──────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clear_cache():
    urlguard.reset_cache()
    yield
    urlguard.reset_cache()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/admin",
        "http://localhost/secret",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:9/",
        "http://10.0.0.5/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:pass@example.com/x",
        "http://redis.internal:6379/",
    ],
)
def test_urls_that_must_never_be_fetched(url):
    with pytest.raises(urlguard.BlockedURL):
        urlguard.check_sync(url)


def test_public_urls_pass_and_private_dns_is_caught():
    async def fake_resolver(host, port):
        if host == "evil.example":
            return [(2, 1, 6, "", ("10.1.2.3", 0))]
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    async def scenario():
        assert await urlguard.check("https://music.youtube.com/watch?v=x", resolver=fake_resolver)
        with pytest.raises(urlguard.BlockedURL):
            await urlguard.check("https://evil.example/song.mp3", resolver=fake_resolver)

    asyncio.run(scenario())


def test_a_configured_self_hosted_mirror_is_allowed(monkeypatch):
    import dataclasses

    from vyron.config import settings

    local = dataclasses.replace(settings, cobalt_urls="http://cobalt:9000")
    assert "cobalt" in urlguard.allowed_hosts(local)

    async def scenario():
        return await urlguard.check_user_url("http://cobalt:9000/api/json", settings=local)

    # an explicitly configured mirror bypasses the private-range refusal
    assert asyncio.run(scenario()) == "http://cobalt:9000/api/json"


# ── redaction ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "dirty, hidden",
    [
        ("key vyrn_abcdefghijklmnopqrstuvwxyz012345 leaked", "vyrn_abcdefghij"),
        ("owner vown_abcdefghijklmnop signed in", "vown_abcdefghij"),
        ("telegram 8123456789:AAHfakefakefakefakefakefakefakefake1 crashed", "AAHfakefake"),
        ("mongodb+srv://user:pw@cluster.mongodb.net/vyron", "user:pw"),
        ("https://api.test/x?api_key=supersecret&y=1", "supersecret"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "eyJhbGciOiJIUzI1NiJ9"),
        ("STRING_SESSION=1BVtsOK4Bu" + "a" * 140, "BVtsOK4Bu"),
    ],
)
def test_scrub_removes_the_secret_but_keeps_the_sentence(dirty, hidden):
    cleaned = scrub(dirty)
    assert hidden not in cleaned
    assert cleaned  # we never blank the whole line


def test_scrub_leaves_ordinary_text_alone():
    text = "playing Kesariya for 3 listeners in chat 12345"
    assert scrub(text) == text


def test_filter_rewrites_the_record_before_it_is_written():
    record = logging.LogRecord(
        "vyron.test", logging.INFO, __file__, 1, "auth failed for %s", ("vyrn_" + "z" * 40,), None
    )
    assert RedactFilter().filter(record) is True
    assert "vyrn_zzzz" not in record.getMessage()
    assert "auth failed" in record.getMessage()
