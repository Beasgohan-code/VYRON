"""Pure-logic tests: formatting, queue semantics, helpers."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from vyron.core.queue import ChatState, LoopMode, QueueManager, Track
from vyron.core import pending
from vyron.ui.progress import (
    BAR_FULL,
    KNOB,
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
    """Played is a solid block, the rest is light, and the playhead is a ring."""
    bar = progress_bar(30, 120, length=14)
    assert len(bar) == 14
    assert bar.count(KNOB) == 1
    assert bar[0] == BAR_FULL


def test_progress_bar_edges():
    assert progress_bar(0, 100, length=10).startswith(KNOB)
    finished = progress_bar(100, 100, length=10)
    assert finished.endswith(KNOB)
    assert progress_bar(0, 0, length=10).count(BAR_FULL) == 0
    assert progress_bar(9999, 10, length=10).endswith(KNOB)


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


def test_command_args_strips_whichever_prefix_was_typed():
    """The multi-prefix filter accepted `.play`; the parser did not.

    Production: `.play Wrong` reached the search engine as the query
    ".play Wrong", so the bot played five songs whose titles happened to
    contain the word "play" and told the listener it had searched for
    ".play". Every command with arguments was affected in chats that used a
    non-slash prefix.
    """
    from vyron.utils.commands import configured

    assert "." in configured(), "the dot prefix is on by default — that is the case that broke"
    for typed in (".play Wrong", "!play Wrong", "?play Wrong", "/play Wrong", "$play Wrong"):
        message = SimpleNamespace(text=typed, caption=None)
        assert command_args(message) == "Wrong", typed

    # …and the same for every other command shape: @botname, casing, spacing.
    assert command_args(SimpleNamespace(text=".play@VyronMusicBot Wrong", caption=None)) == "Wrong"
    assert command_args(SimpleNamespace(text=".PLAY Wrong", caption=None)) == "Wrong"
    assert command_args(SimpleNamespace(text=".play   Wrong  ", caption=None)) == "Wrong"
    assert command_args(SimpleNamespace(text=".seek 1:30", caption=None)) == "1:30"


def test_a_query_that_is_not_a_command_is_left_alone():
    """`.` is also just punctuation: `#1 hit` and `.nothing` are not commands."""
    assert command_args(SimpleNamespace(text="#1 hit parade", caption=None)) == "#1 hit parade"
    assert command_args(SimpleNamespace(text=".nothing Wrong", caption=None)) == ".nothing Wrong"


def test_a_command_with_no_arguments_is_empty():
    for typed in (".play", "/play", "/play@VyronMusicBot", ".PLAY"):
        assert command_args(SimpleNamespace(text=typed, caption=None)) == "", typed


def test_a_song_called_play_still_plays():
    """`.play .play` is "play the song called .play", not an empty query."""
    assert command_args(SimpleNamespace(text=".play .play", caption=None)) == ".play"


def test_the_commands_lock_covers_every_prefix():
    """A group that locked "commands" could still be spammed with `.play`."""
    from vyron.utils.helpers import is_command_text

    for typed in ("/play x", ".play x", "!play x", "?play x"):
        assert is_command_text(typed) is True, typed
    for typed in ("hello there", "#1 hit parade", ".nothing", "play"):
        assert is_command_text(typed) is False, typed


def test_prefixless_mode_strips_a_bare_command_word():
    from vyron.utils import commands

    commands.override(("/", ""))
    try:
        assert command_args(SimpleNamespace(text="play Wrong", caption=None)) == "Wrong"
        # A message that is not a command is untouched.
        assert command_args(SimpleNamespace(text="Wrong", caption=None)) == "Wrong"
    finally:
        commands.override(None)


# ── single-instance lease ───────────────────────────────────────────────────
def _lease_fresh():
    from vyron.core import lease

    lease._state.update(primary=True, holder=lease.instance_id(), since=0.0)
    return lease


def test_lease_makes_the_second_copy_a_standby(tmp_path):
    import asyncio
    import dataclasses

    from vyron.config import settings as base
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    lease = _lease_fresh()
    assert asyncio.run(lease.claim(storage)) is True
    assert lease.is_primary()

    # a different process id sees a fresh lease: it must stand down
    first = lease.instance_id()
    lease._ME = "ins_other"
    try:
        assert asyncio.run(lease.claim(storage)) is False
        assert not lease.is_primary()
        assert lease.status()["holder"] == first
    finally:
        lease._ME = first
        lease._state.update(primary=True, holder=first)


def test_lease_is_taken_over_once_it_goes_stale(tmp_path):
    import asyncio
    import dataclasses

    from vyron.config import settings as base
    from vyron.core import lease as lease_module
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    asyncio.run(storage.set_meta("instance", {"id": "ins_gone", "beat": 0.0}))
    assert asyncio.run(lease_module.claim(storage)) is True


def test_a_standby_takes_over_when_the_old_instance_stops_answering(tmp_path):
    """The redeploy trap: a new process used to stay a standby for ever.

    Render overlaps a deploy for a few seconds, so the incoming instance sees a
    fresh lease belonging to the process that is shutting down. `claim` ran once
    at boot; nothing ever asked again — a bot that answered every command and
    never played anything until the *next* deploy.
    """
    import asyncio
    import dataclasses
    import time

    from vyron.config import settings as base
    from vyron.core import lease
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    asyncio.run(storage.connect())

    promotions: list[int] = []

    async def hook():
        promotions.append(1)

    lease.on_promote(hook)
    me = lease.instance_id()
    try:
        # Another process holds a fresh lease: this one must stand down…
        asyncio.run(
            storage.set_meta("instance", {"id": "ins_old", "beat": time.time(), "since": 0.0})
        )
        assert asyncio.run(lease.claim(storage)) is False   # boot: stand down
        assert lease.is_primary() is False
        assert asyncio.run(lease.renew(storage)) is False    # still somebody else's
        assert promotions == []

        # …and take over by itself once that lease stops being refreshed.
        asyncio.run(
            storage.set_meta(
                "instance",
                {"id": "ins_old", "beat": time.time() - lease.LEASE_SECONDS - 1, "since": 0.0},
            )
        )
        assert asyncio.run(lease.renew(storage)) is True
        assert lease.is_primary() is True
        assert promotions == [1], "playback should have been resumed on promotion"
    finally:
        lease._promote_hooks.clear()
        lease._state.update(primary=True, holder=me)


def test_a_primary_renew_keeps_its_lease(tmp_path):
    import asyncio
    import dataclasses
    import time

    from vyron.config import settings as base
    from vyron.core import lease
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    asyncio.run(storage.connect())
    me = lease.instance_id()
    lease._state.update(primary=True, holder=me, since=0.0)

    assert asyncio.run(lease.renew(storage)) is True
    stored = asyncio.run(storage.get_meta("instance", {}))
    assert stored["id"] == me
    assert time.time() - float(stored["beat"]) < 5


def test_standby_refuses_to_stream():
    import asyncio

    async def scenario():
        from vyron.core import lease
        from vyron.core.player import Player

        assert Player._may_stream() is True
        lease._state.update(primary=False, holder="ins_other")
        try:
            assert Player._may_stream() is False
        finally:
            lease._state.update(primary=True, holder=lease.instance_id())

    asyncio.run(scenario())


# ── counter writes are coalesced, content writes are not ────────────────────
def test_counter_bumps_coalesce_but_a_save_is_immediate(tmp_path):
    import asyncio
    import dataclasses
    import json

    from vyron.config import settings as base
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))

    async def scenario():
        await storage.connect()
        await storage.save_playlist(1, {"id": "p1", "name": "kept", "tracks": []})
        # a real save is on disk before the call returns
        on_disk = json.loads((tmp_path / "vyron.json").read_text())
        assert on_disk["playlists"]["1"][0]["name"] == "kept"

        before = (tmp_path / "vyron.json").stat().st_mtime_ns
        for _ in range(25):
            await storage.bump("plays")
        assert storage._pending is True          # queued, not written 25 times
        assert (tmp_path / "vyron.json").stat().st_mtime_ns == before
        assert (await storage.counters())["plays"] == 25

        await storage.flush_pending()            # what shutdown calls
        assert storage._pending is False
        assert json.loads((tmp_path / "vyron.json").read_text())["counters"]["plays"] == 25

    asyncio.run(scenario())


def test_the_ytmusic_session_can_hold_every_concurrent_request():
    """Production logged "Connection pool is full" twice per boot."""
    from vyron.core import ytmusic

    session = ytmusic._session()
    if session is None:  # requests missing — nothing to size
        return
    adapter = session.get_adapter("https://music.youtube.com")
    assert adapter._pool_maxsize >= 32
    assert adapter._pool_connections >= 8
