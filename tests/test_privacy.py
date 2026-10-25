"""User data export and deletion — /mydata and /forgetme."""
from __future__ import annotations

import asyncio
import dataclasses
import json

from vyron.config import Settings
from vyron.database import JsonStorage


def _storage(tmp_path) -> JsonStorage:
    storage = JsonStorage(dataclasses.replace(Settings(), data_dir=tmp_path))
    asyncio.run(storage.connect())
    return storage


def _seed(storage: JsonStorage, user_id: int) -> None:
    async def scenario():
        await storage.add_history(user_id, {"id": "h1", "title": "One"})
        await storage.add_history(user_id, {"id": "h2", "title": "Two"})
        await storage.add_favorite(user_id, {"id": "f1", "title": "Fav"})
        await storage.save_playlist(user_id, {"id": "p1", "name": "Mine", "tracks": []})
        # somebody else's data must survive untouched
        await storage.add_history(user_id + 1, {"id": "x", "title": "Other"})

    asyncio.run(scenario())


def test_export_contains_only_my_data(tmp_path):
    storage = _storage(tmp_path)
    _seed(storage, 500)

    data = asyncio.run(storage.export_user(500))

    assert data["user_id"] == 500
    assert [item["id"] for item in data["history"]] == ["h2", "h1"]
    assert [item["id"] for item in data["favorites"]] == ["f1"]
    assert [item["id"] for item in data["playlists"]] == ["p1"]
    # A stranger's track never leaks into the document.
    assert "Other" not in json.dumps(data)


def test_export_is_json_serialisable_and_empty_for_strangers(tmp_path):
    storage = _storage(tmp_path)
    data = asyncio.run(storage.export_user(999))
    assert data["history"] == [] and data["favorites"] == [] and data["playlists"] == []
    assert json.loads(json.dumps(data))["user_id"] == 999


def test_forget_removes_everything_but_leaves_others_alone(tmp_path):
    storage = _storage(tmp_path)
    _seed(storage, 500)

    removed = asyncio.run(storage.forget_user(500))

    assert removed == {"history": 2, "favorites": 1, "playlists": 1}
    after = asyncio.run(storage.export_user(500))
    assert after["history"] == [] and after["favorites"] == [] and after["playlists"] == []
    # The other user is intact.
    other = asyncio.run(storage.export_user(501))
    assert [item["id"] for item in other["history"]] == ["x"]

    # Deleting twice is a no-op, not an error.
    assert asyncio.run(storage.forget_user(500)) == {
        "history": 0,
        "favorites": 0,
        "playlists": 0,
    }


def test_forget_survives_a_restart(tmp_path):
    storage = _storage(tmp_path)
    _seed(storage, 500)
    asyncio.run(storage.forget_user(500))

    reopened = _storage(tmp_path)
    after = asyncio.run(reopened.export_user(500))
    assert after["history"] == [] and after["favorites"] == [] and after["playlists"] == []


def test_the_delete_card_needs_a_second_tap():
    from vyron.ui import cards

    markup = cards.confirm_card(
        "Delete your data?",
        "History, favourites and playlists are removed.",
        confirm="v:forget:yes",
        danger=True,
        confirm_label="Yes, delete it",
    )
    assert "v:forget:yes" in markup
    # Nothing destructive is wired to the first tap.
    assert "v:forget:ask" not in markup
