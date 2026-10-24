"""Pure-logic tests: formatting, queue semantics, helpers."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from vyron.core.queue import ChatState, LoopMode, QueueManager, Track
from vyron.core import pending
from vyron.ui.progress import (
    compact_number,
    fmt_duration,
    human_size,
    human_time,
    parse_duration,
    percentage,
    progress_bar,
    truncate,
)
from vyron.utils.helpers import command_args, parse_seek


# ── durations ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1:02:03", 3723),
        ("3:45", 225),
        ("95", 95),
        (95, 95),
        (None, 0),
        ("", 0),
        ("0:05", 5),
        ("junk", 0),
        (-4, 0),
    ],
)
def test_parse_duration(raw, expected):
    assert parse_duration(raw) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0:00"), (5, "0:05"), (65, "1:05"), (3600, "1:00:00"), (3725, "1:02:05")],
)
def test_fmt_duration(seconds, expected):
    assert fmt_duration(seconds) == expected


def test_human_helpers():
    assert human_time(45) == "45s"
    assert human_time(125) == "2m 5s"
    assert human_time(7300) == "2h 1m"
    assert human_size(1536).endswith("KB")
    assert compact_number(1500) == "1.5K"
    assert compact_number(2_400_000) == "2.4M"


# ── progress bar ────────────────────────────────────────────────────────────
def test_progress_bar_shape():
    bar = progress_bar(30, 120, length=14)
    assert len(bar) == 14
    assert bar.count("◉") == 1
    assert bar[0] == "█"


def test_progress_bar_edges():
    assert progress_bar(0, 100, length=10).startswith("◉")
    finished = progress_bar(100, 100, length=10)
    assert finished.endswith("◉")
    assert progress_bar(0, 0, length=10).count("█") == 0
    assert progress_bar(9999, 10, length=10).endswith("◉")


def test_percentage_clamps():
    assert percentage(50, 100) == 50
    assert percentage(200, 100) == 100
    assert percentage(5, 0) == 0


def test_truncate():
    assert truncate("hello", 10) == "hello"
    assert len(truncate("x" * 50, 10)) == 10
    assert truncate("  a   b  ", 10) == "a b"


# ── loop modes ──────────────────────────────────────────────────────────────
def test_loop_mode_cycle():
    assert LoopMode.parse("ALL") is LoopMode.ALL
    assert LoopMode.parse("nonsense") is LoopMode.OFF
    assert LoopMode.OFF.next() is LoopMode.ONE
    assert LoopMode.ONE.next() is LoopMode.ALL
    assert LoopMode.ALL.next() is LoopMode.OFF


# ── queue ───────────────────────────────────────────────────────────────────
def _track(media_id: str, duration: int = 100) -> Track:
    return Track(id=media_id, title=f"Song {media_id}", duration=duration)


def test_add_dedupe_and_limit():
    qm = QueueManager(default_volume=80)
    assert qm.add(1, _track("a")) == 1
    assert qm.add(1, _track("b")) == 2
    assert qm.add(1, _track("a")) == -1          # duplicate
    assert qm.size(1) == 2
    assert qm.add(1, _track("c"), max_size=2) == 0  # full
    assert qm.get(1).volume == 80


def test_pop_remove_move():
    qm = QueueManager()
    for media_id in "abcd":
        qm.add(1, _track(media_id))
    assert qm.pop_next_for(1).id == "a"
    assert qm.remove(1, 99) is None
    assert qm.remove(1, 1).id == "b"
    assert qm.move(1, 1, 2) is True
    assert [t.id for t in qm.get(1).queue] == ["d", "c"]
    assert qm.move(1, 5, 1) is False


def test_loop_all_rotation_and_clear():
    qm = QueueManager()
    state = qm.get(1)
    state.current = _track("now")
    state.queue = [_track("next")]
    qm.rotate_current_to_end(1)
    assert [t.id for t in state.queue] == ["next", "now"]
    assert qm.clear(1) == 2
    assert state.queue == []
    assert state.current is not None  # keep_current default


def test_shuffle_preserves_membership():
    qm = QueueManager()
    for index in range(10):
        qm.add(1, _track(str(index)))
    before = {t.id for t in qm.get(1).queue}
    qm.shuffle(1)
    assert {t.id for t in qm.get(1).queue} == before


def test_state_elapsed_math():
    state = ChatState(chat_id=1, current=_track("a", 300), playing=True)
    state.started_at = time.monotonic() - 30
    assert 29 <= state.elapsed() <= 31
    state.paused = True
    state.offset = 42
    state.paused_at = time.monotonic()
    assert state.elapsed() == 42
    assert state.remaining() == 258


def test_track_roundtrip():
    track = _track("xyz")
    track.uploader = "Artist"
    track.requested_by = 7
    clone = Track.from_dict(track.to_dict())
    assert clone == track
    assert clone.watch_url == "https://youtu.be/xyz"


# ── pending searches ────────────────────────────────────────────────────────
def test_pending_cache():
    entry = pending.put(1, 10, 99, "query", [_track("a")], mode="download", video=True)
    assert pending.get(1, 10) is entry
    assert entry.mode == "download" and entry.video is True
    assert pending.take(1, 10) is entry
    assert pending.get(1, 10) is None


# ── helper parsing ──────────────────────────────────────────────────────────
def test_parse_seek():
    assert parse_seek("90", 0, 300) == 90
    assert parse_seek("1:30", 0, 300) == 90
    assert parse_seek("+15", 60, 300) == 75
    assert parse_seek("-15", 60, 300) == 45
    assert parse_seek("999", 0, 300) == 299
    assert parse_seek("-999", 10, 300) == 0


def test_command_args():
    message = SimpleNamespace(text="/play@VyronMusicBot believer", caption=None)
    assert command_args(message) == "believer"
    message = SimpleNamespace(text=None, caption="/song faded")
    assert command_args(message) == "faded"
