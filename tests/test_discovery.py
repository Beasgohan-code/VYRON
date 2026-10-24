"""Charts / playlists / artwork — no network, no Telegram."""
from __future__ import annotations

import asyncio

import pytest

from vyron.core import playlists as store
from vyron.core.charts import MIXES, MOODS, Charts, _track
from vyron.core.queue import ChatState, Track
from vyron.core.search import YouTube
from vyron.runtime import runtime


def _tracks(n: int = 3) -> list[Track]:
    return [
        Track(id=f"id{i}", title=f"Track {i}", duration=180 + i, uploader=f"Artist {i}", thumbnail=None)
        for i in range(n)
    ]


# ── charts ─────────────────────────────────────────────────────────────────
def test_mixes_and_moods_are_well_formed():
    assert len(MIXES) >= 6
    assert all(spec["title"] and spec["queries"] for spec in MIXES.values())
    assert MOODS and all(isinstance(query, str) for query in MOODS.values())


def test_track_payload_shape():
    payload = _track(_tracks(1)[0], 3)
    assert payload["index"] == 3
    assert payload["query"] == "Track 0 Artist 0"
    assert payload["url"].endswith("id0")


def test_charts_cache_and_invalidate(monkeypatch):
    class FakeYouTube:
        def __init__(self):
            self.calls = 0

        async def search(self, query, limit=10, **kwargs):
            self.calls += 1
            return _tracks(2)

    fake = FakeYouTube()
    charts = Charts(fake, ttl=60)

    async def scenario():
        first = await charts.mood("lofi", limit=2)
        second = await charts.mood("lofi", limit=2)
        assert len(first) == 2 and first == second
        assert fake.calls == 1  # second call served from cache
        charts.invalidate("mood:lofi")
        await charts.mood("lofi", limit=2)
        assert fake.calls == 2

    asyncio.run(scenario())


def test_charts_unknown_keys_are_empty():
    charts = Charts(YouTube.__new__(YouTube), ttl=1)

    async def scenario():
        assert await charts.mix("nope") == []
        assert await charts.mood("nope") == []

    asyncio.run(scenario())


def test_charts_survive_media_errors(monkeypatch):
    class BrokenYouTube:
        async def search(self, *args, **kwargs):
            from vyron.core.search import MediaError

            raise MediaError("offline")

    charts = Charts(BrokenYouTube(), ttl=30)

    async def scenario():
        assert await charts.mood("lofi") == []

    asyncio.run(scenario())


# ── playlists ──────────────────────────────────────────────────────────────
class FakeStorage:
    backend = "fake"

    def __init__(self):
        self.data: dict[str, list[dict]] = {}

    async def playlists(self, user_id):
        return [dict(item) for item in self.data.get(str(user_id), [])]

    async def save_playlist(self, user_id, playlist):
        items = self.data.setdefault(str(user_id), [])
        for index, item in enumerate(items):
            if item["id"] == playlist["id"]:
                items[index] = dict(playlist)
                return
        items.append(dict(playlist))

    async def delete_playlist(self, user_id, playlist_id):
        items = self.data.get(str(user_id), [])
        kept = [item for item in items if item["id"] != playlist_id]
        self.data[str(user_id)] = kept
        return len(kept) != len(items)


@pytest.fixture()
def fake_storage(monkeypatch):
    storage = FakeStorage()
    monkeypatch.setattr(runtime, "storage", storage)
    return storage


def test_clean_name():
    assert store.clean_name("  chill / nights!!  ") == "chill  nights"
    assert store.clean_name("") == "Untitled"
    assert len(store.clean_name("x" * 100)) == 40


def test_playlist_lifecycle(fake_storage):
    async def scenario():
        entry = await store.create(1, "Road trip")
        assert entry["name"] == "Road trip"
        added = await store.add_tracks(1, entry["id"], _tracks(3))
        assert added == 3
        # duplicates are ignored
        assert await store.add_tracks(1, entry["id"], _tracks(3)) == 0

        name, tracks = await store.as_tracks(1, "road trip")
        assert name == "Road trip" and len(tracks) == 3
        assert tracks[0].title == "Track 0"

        summary = store.summary((await store.list_playlists(1))[0])
        assert summary["count"] == 3 and summary["duration"] == 180 + 181 + 182

        assert await store.remove_track(1, entry["id"], "id1") is True
        assert len((await store.as_tracks(1, "Road trip"))[1]) == 2

        assert await store.delete(1, entry["id"]) is True
        assert await store.list_playlists(1) == []

    asyncio.run(scenario())


def test_playlist_limit(monkeypatch, fake_storage):
    monkeypatch.setattr(store, "MAX_PLAYLISTS", 2)

    async def scenario():
        await store.create(2, "a")
        await store.create(2, "b")
        with pytest.raises(ValueError):
            await store.create(2, "c")

    asyncio.run(scenario())


def test_playlist_track_cap(monkeypatch, fake_storage):
    monkeypatch.setattr(store, "MAX_TRACKS", 3)

    async def scenario():
        entry = await store.create(3, "cap")
        assert await store.add_tracks(3, entry["id"], _tracks(6)) == 3

    asyncio.run(scenario())


# ── artwork ────────────────────────────────────────────────────────────────
def test_now_playing_artwork_degrades_gracefully():
    from vyron.utils import thumbnails

    state = ChatState(chat_id=1)
    state.current = Track(id="x", title="Song", duration=200, uploader="Artist")
    state.playing = True
    if not thumbnails.PIL_AVAILABLE:
        assert thumbnails.render(state, state.current) is None
        return
    raw = thumbnails.render(state, state.current)
    assert raw and raw[:2] == b"\xff\xd8"  # JPEG magic
    assert len(raw) > 5_000
    assert thumbnails.render(state, None) is None
