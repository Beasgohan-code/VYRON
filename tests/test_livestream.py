"""Live log stream (SSE) and the cached Home payload.

Both exist because of one production log: a Render deployment where the Mini App
took 27 s to paint and the audio failed 45 s later. The stream shows what is
happening while it happens; the cache keeps the first paint cheap.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pyrogram")

from aiohttp.test_utils import TestClient, TestServer

from vyron.core.charts import Charts
from vyron.core.journal import Journal, journal
from vyron.core.queue import Track
from vyron.utils.health import build_app
from vyron.web import server as web_server


# ── journal fan-out ────────────────────────────────────────────────────────
def test_a_subscriber_receives_every_event():
    book = Journal()

    async def run():
        subscription = book.subscribe(limit=10)
        book.info("test", "first")
        book.warn("test", "second")
        return subscription, [await asyncio.wait_for(subscription.queue.get(), timeout=1) for _ in range(2)]

    subscription, events = asyncio.run(run())
    assert [event["message"] for event in events] == ["first", "second"]
    assert events[1]["level"] == "warn"
    book.unsubscribe(subscription)
    assert book.subscribers == 0


def test_a_slow_subscriber_drops_old_events_instead_of_blocking():
    book = Journal()

    async def run():
        subscription = book.subscribe(limit=20)
        for index in range(60):
            book.info("test", f"event {index}")
        await asyncio.sleep(0)
        drained = []
        while not subscription.queue.empty():
            drained.append(subscription.queue.get_nowait())
        return subscription, drained

    subscription, drained = asyncio.run(run())
    assert subscription.dropped > 0
    assert len(drained) == subscription.queue.maxsize
    assert drained[-1]["message"] == "event 59"
    book.unsubscribe(subscription)


# ── SSE endpoint ───────────────────────────────────────────────────────────
def test_the_log_stream_is_owner_only():
    async def run():
        app = build_app(with_webapp=True)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/logs/stream")
            return response.status, await response.json()

    status, payload = asyncio.run(run())
    assert status == 403 and payload["error"] == "owner only"


def test_the_log_stream_replays_then_tails(monkeypatch):
    monkeypatch.setattr(web_server, "_is_owner", lambda _user: True)
    journal.info("test", "before the stream")

    async def run():
        app = build_app(with_webapp=True)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/logs/stream?level=all")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/event-stream")

            first = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=3)
            assert b"retry" in first

            async def until(needle: bytes, *, limit: int = 200) -> bytes:
                for _ in range(limit):
                    chunk = await asyncio.wait_for(response.content.readuntil(b"\n\n"), timeout=5)
                    if needle in chunk:
                        return chunk
                raise AssertionError(f"{needle!r} never arrived")

            assert b"before the stream" in await until(b"before the stream")

            journal.warn("test", "after the stream")
            live = await until(b"after the stream")
            assert b"event: log" in live and b"warn" in live

    asyncio.run(run())


def test_the_live_page_ships_a_viewer():
    async def run():
        app = build_app(with_webapp=True)
        async with TestClient(TestServer(app)) as client:
            page = await client.get("/logs/live")
            return page.status, await page.text()

    status, html = asyncio.run(run())
    assert status == 200
    assert "api/logs/stream" in html and "EventSource" in html


# ── cached Home ────────────────────────────────────────────────────────────
class CountingYouTube:
    def __init__(self):
        self.searches = 0

    async def search(self, query, limit=None, requester=(0, "")):
        self.searches += 1
        return [
            Track(id=f"{abs(hash(query)) % 10**8:08d}abc"[:11], title=query, duration=120, uploader="x")
        ]

    async def playlist(self, url, limit=None):
        raise RuntimeError("no trending playlist in tests")


def test_home_is_built_once_and_then_served_from_cache():
    youtube = CountingYouTube()
    charts = Charts(youtube, ttl=60)

    async def run():
        first = await charts.home(mixes=2, trending=4)
        before = youtube.searches
        second = await charts.home(mixes=2, trending=4)
        return first, second, before, youtube.searches

    first, second, before, after = asyncio.run(run())
    assert first["generated_at"] and second["generated_at"] == first["generated_at"]
    assert after == before  # the second call touched nothing


def test_home_returns_partial_shelves_when_a_source_fails():
    charts = Charts(CountingYouTube(), ttl=60)

    async def slow(*_args, **_kwargs):
        await asyncio.sleep(5)
        return []

    async def run():
        charts.mix = slow  # a mix that never answers in time
        charts.shelf_timeout = 0.1
        return await asyncio.wait_for(charts._build_home(mixes=2, trending=4), timeout=3)

    payload = asyncio.run(run())
    assert "trending" in payload
    assert payload["shelves"] == []  # empty, not an exception


def test_home_primes_in_the_background():
    charts = Charts(CountingYouTube(), ttl=60)

    async def run():
        charts.prime()
        await asyncio.sleep(0.05)
        return charts._home_cache is not None

    assert asyncio.run(run())
