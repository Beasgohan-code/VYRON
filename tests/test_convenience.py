"""Sleep-timer parsing/registry and the playlist JSON export format."""
from __future__ import annotations

import asyncio
import json

import pytest

from vyron.core import playlists as store
from vyron.core.queue import Track
from vyron.core.timers import MAX_MINUTES, TimerBoard, humanise, parse_duration


# ── parsing ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("30", 30),
        (45, 45),
        ("10m", 10),
        ("2h", 120),
        ("1h30m", 90),
        ("90s", 2),          # rounds to the nearest minute
        ("1.5h", 90),
        ("OFF", None),
        ("cancel", None),
        ("0", None),         # 0 = switch it off
        ("", 0),
        ("banana", 0),
        ("-4", 0),
    ],
)
def test_parse_duration(raw, expected):
    assert parse_duration(raw) == expected


def test_parse_duration_is_capped():
    assert parse_duration("9999") == MAX_MINUTES
    assert parse_duration("100h") == MAX_MINUTES


def test_humanise():
    assert humanise(30) == "30m"
    assert humanise(60) == "1h"
    assert humanise(90) == "1h 30m"


# ── registry ───────────────────────────────────────────────────────────────
class FakeTask:
    def __init__(self):
        self.cancelled = False

    def done(self):
        return False

    def cancel(self):
        self.cancelled = True


def test_board_replaces_the_previous_timer_for_a_chat():
    board = TimerBoard()
    first = FakeTask()
    board.set(-1, 10, due=1000.0, task=first)
    board.set(-1, 20, due=2000.0, task=FakeTask())

    assert board.remaining(-1, 1000.0) == 1000
    assert first.cancelled is True
    assert len(board) == 1


def test_board_cancel_and_clear():
    board = TimerBoard()
    task = FakeTask()
    board.set(-1, 10, due=1000.0, task=task)

    assert board.cancel(-1) is True
    assert task.cancelled is True
    assert board.cancel(-1) is False
    assert board.remaining(-1, 1000.0) == 0

    board.set(-2, 5, due=2000.0, task=FakeTask())
    board.set(-3, 5, due=2000.0, task=FakeTask())
    board.clear()
    assert len(board) == 0


def test_board_can_drop_without_killing_the_task():
    board = TimerBoard()
    task = FakeTask()
    board.set(-1, 10, due=1000.0, task=task)
    board.cancel(-1, kill=False)
    assert task.cancelled is False


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
