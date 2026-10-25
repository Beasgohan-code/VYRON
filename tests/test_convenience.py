"""Playlist JSON export/import format."""
from __future__ import annotations

import asyncio
import json

from vyron.core import playlists as store
from vyron.core.queue import Track
# ── playlist export round-trip ─────────────────────────────────────────────
def test_export_payload_round_trips_into_tracks(tmp_path):
    from vyron.runtime import runtime
    from vyron.database import JsonStorage
    from vyron.config import Settings
    import dataclasses

    storage = JsonStorage(dataclasses.replace(Settings(), data_dir=tmp_path))
    asyncio.run(storage.connect())
    runtime.storage = storage

    async def scenario():
        playlist = await store.create(1001, "Road Trip")
        added = await store.add_tracks(
            1001,
            playlist["id"],
            [
                Track(id="a", title="Highway", uploader="A", duration=200, url="https://x/a"),
                Track(id="b", title="Coast", uploader="B", duration=180, url="https://x/b"),
            ],
        )
        assert added == 2

        found = await store.find(1001, "road trip")
        assert found is not None
        payload = {
            "format": "vyron.playlist.v1",
            "name": found["name"],
            "tracks": [
                {
                    "title": entry["title"],
                    "uploader": entry.get("uploader", ""),
                    "duration": entry.get("duration", 0),
                    "id": entry.get("id"),
                    "url": entry.get("url"),
                }
                for entry in found["tracks"]
            ],
        }
        # simulate the file going through JSON
        restored = json.loads(json.dumps(payload))
        tracks = [Track(id=item["id"], title=item["title"], duration=item["duration"]) for item in restored["tracks"]]
        assert [track.title for track in tracks] == ["Highway", "Coast"]

        second = await store.create(1001, "Road Trip Copy")
        assert await store.add_tracks(1001, second["id"], tracks) == 2
        # a second import is all duplicates
        assert await store.add_tracks(1001, second["id"], tracks) == 0

    asyncio.run(scenario())
