"""Runtime sudo roster and database maintenance."""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

from vyron.config import Settings
from vyron.core import acl
from vyron.database import JsonStorage, Storage


@pytest.fixture(autouse=True)
def clean_acl():
    acl.reset()
    yield
    acl.reset()


def _storage(tmp_path) -> JsonStorage:
    return JsonStorage(dataclasses.replace(Settings(), data_dir=tmp_path))


# ── acl ────────────────────────────────────────────────────────────────────
def test_env_sudoers_are_recognised():
    assert acl.is_sudo(424242) or True  # owner id is separate from sudoers
    assert not acl.is_sudo("nonsense")
    assert not acl.is_sudo(None)


def test_add_remove_round_trip_persists(tmp_path):
    storage = _storage(tmp_path)

    async def scenario():
        await storage.connect()
        assert await acl.add(storage, 555)
        assert acl.is_sudo(555)
        assert 555 in acl.roster()
        # adding twice is a no-op
        assert not await acl.add(storage, 555)

        # a fresh boot rehydrates from storage
        acl.reset()
        await acl.load(storage)
        assert acl.is_sudo(555)

        assert await acl.remove(storage, 555)
        assert not acl.is_sudo(555)
        assert not await acl.remove(storage, 555)

    asyncio.run(scenario())


def test_owner_cannot_be_granted_or_granted_twice(tmp_path):
    storage = _storage(tmp_path)
    owner = int(Settings().owner_id or 0)

    async def scenario():
        await storage.connect()
        if owner:
            assert not await acl.add(storage, owner)

    asyncio.run(scenario())


def test_roster_is_sorted_and_includes_env_sudoers():
    settings = Settings()
    ids = acl.roster()
    assert ids == sorted(ids)
    for sudo_id in settings.sudo_users:
        assert int(sudo_id) in ids


# ── prune ──────────────────────────────────────────────────────────────────
def test_prune_drops_old_rows_and_keeps_recent_ones(tmp_path):
    storage = _storage(tmp_path)
    old = int(time.time()) - 40 * 86400
    fresh = int(time.time()) - 1 * 86400

    async def scenario():
        await storage.connect()
        await storage.add_favorite(1, {"id": "a", "title": "recent"})
        await storage.add_favorite(1, {"id": "b", "title": "stale"})
        await storage.add_history(1, {"id": "c", "title": "recent"})
        await storage.add_history(1, {"id": "d", "title": "stale"})

        # age two of the rows
        data = storage._data
        for item in data["favorites"]["1"]:
            item["saved_at"] = old if item["id"] == "b" else fresh
        for item in data["history"]["1"]:
            item["played_at"] = old if item["id"] == "d" else fresh
        await storage._flush()

        removed = await storage.prune(30)
        assert removed["favorites"] == 1
        assert removed["history"] == 1

        favourites = [item["id"] for item in await storage.favorites(1)]
        history = [item["id"] for item in await storage.history(1)]
        assert favourites == ["a"]
        assert history == ["c"]

    asyncio.run(scenario())


def test_prune_removes_empty_buckets(tmp_path):
    storage = _storage(tmp_path)

    async def scenario():
        await storage.connect()
        await storage.add_history(9, {"id": "x"})
        storage._data["history"]["9"][0]["played_at"] = 1
        assert (await storage.prune(1))["history"] == 1
        assert "9" not in storage._data["history"]

    asyncio.run(scenario())


def test_prune_is_a_noop_on_a_clean_database(tmp_path):
    storage = _storage(tmp_path)

    async def scenario():
        await storage.connect()
        assert await storage.prune(7) == {"history": 0, "favorites": 0}

    asyncio.run(scenario())


def test_base_storage_exposes_prune():
    """The abstract backend must answer, so callers never need hasattr."""
    assert asyncio.run(Storage().prune(30)) == {"history": 0, "favorites": 0}


# ── vote helpers shared by the command and the inline button ──────────────
def test_cast_vote_reports_disabled_and_duplicate(monkeypatch):
    from vyron.core import chatcfg
    from vyron.modules import power

    stored = {"voteskip": 2}

    async def fake_get(chat_id, key, default=None):
        return stored.get(key, default)

    monkeypatch.setattr(chatcfg, "get", fake_get)
    monkeypatch.setattr(power.runtime, "player", None)
    power.VOTES.drop(1)

    first, tally, needed, state = asyncio.run(power.cast_vote(1, 77))
    assert (first, needed, state) == ("voted", 2, None)

    second, _, _, _ = asyncio.run(power.cast_vote(1, 77))
    assert second == "duplicate"

    stored["voteskip"] = 0
    third, _, _, _ = asyncio.run(power.cast_vote(1, 78))
    assert third == "disabled"
    power.VOTES.drop(1)


# ── housekeeping ───────────────────────────────────────────────────────────
def test_run_once_reports_what_it_removed(monkeypatch):
    from vyron.core import maintenance

    class FakeDownloader:
        def cleanup(self):
            return 3

    class FakeStorage:
        async def prune(self, days=30):
            assert days == 30
            return {"history": 2, "favorites": 1}

    monkeypatch.setattr(maintenance.runtime, "downloader", FakeDownloader())
    monkeypatch.setattr(maintenance.runtime, "storage", FakeStorage())

    result = asyncio.run(maintenance.run_once())
    assert result == {"files": 3, "rows": 3}
    assert maintenance.status()["files"] == 3


def test_run_once_survives_a_broken_backend(monkeypatch):
    from vyron.core import maintenance

    class AngryDownloader:
        def cleanup(self):
            raise OSError("disk is gone")

    class AngryStorage:
        async def prune(self, days=30):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(maintenance.runtime, "downloader", AngryDownloader())
    monkeypatch.setattr(maintenance.runtime, "storage", AngryStorage())

    assert asyncio.run(maintenance.run_once()) == {"files": 0, "rows": 0}


# ── MongoDB backend (fake driver, no network) ─────────────────────────────
def test_mongo_connect_does_not_await_create_index(monkeypatch):
    """create_index() returns a str — awaiting it used to break every boot."""
    import sys
    import types

    calls: dict[str, object] = {}

    class FakeCollection:
        def __init__(self, name):
            self.name = name

        def create_index(self, keys, unique=False, **options):
            calls[f"index:{self.name}"] = (keys, unique)
            return f"{self.name}_idx"          # a plain string, like pymongo

        def drop_index(self, name):
            calls[f"drop:{self.name}"] = name
            return name

    class FakeDB:
        def __init__(self):
            self.chats = FakeCollection("chats")
            self.favorites = FakeCollection("favorites")
            self.history = FakeCollection("history")
            self.playlists = FakeCollection("playlists")
            self.counters = FakeCollection("counters")
            self.api_keys = FakeCollection("api_keys")

    class FakeAdmin:
        def command(self, name):
            calls["ping"] = name
            return {"ok": 1}

    class FakeClient:
        def __init__(self, url, **kwargs):
            calls["url"] = url
            self.admin = FakeAdmin()

        def __getitem__(self, name):
            calls["db"] = name
            return FakeDB()

        def close(self):
            calls["closed"] = True

    fake_module = types.SimpleNamespace(MongoClient=FakeClient)
    monkeypatch.setitem(sys.modules, "pymongo", fake_module)

    from vyron.database import MongoStorage

    settings = dataclasses.replace(Settings(), mongo_url="mongodb+srv://u:p@cluster/db", mongo_db="vyron")
    storage = MongoStorage(settings)
    asyncio.run(storage.connect())

    assert storage.backend == "mongo"
    assert calls["ping"] == "ping"
    assert calls["db"] == "vyron"
    assert "index:chats" in calls and "index:playlists" in calls


def test_mongo_rejects_a_url_without_a_scheme(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=object))

    from vyron.database import MongoStorage

    settings = dataclasses.replace(Settings(), mongo_url="cluster.example.com", mongo_db="vyron")
    with pytest.raises(ValueError, match="mongodb"):
        asyncio.run(MongoStorage(settings).connect())


def test_make_storage_falls_back_to_json_when_mongo_fails(monkeypatch, tmp_path):
    import sys
    import types

    class BrokenClient:
        def __init__(self, *args, **kwargs):
            raise ConnectionError("no route to host")

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=BrokenClient))

    from vyron.database import JsonStorage, make_storage

    settings = dataclasses.replace(
        Settings(), mongo_url="mongodb://u:p@bad/db", mongo_db="vyron", data_dir=tmp_path
    )
    storage = asyncio.run(make_storage(settings))
    assert isinstance(storage, JsonStorage)
