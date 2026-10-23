"""Player engine tests — the parts that decide what plays next and when.

The fakes are deliberately small: the player only needs a call client, a
YouTube resolver and a storage object, so a real Telegram is not involved.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pytgcalls.exceptions import NoActiveGroupCall

from vyron.core.player import Player, StreamError
from vyron.core.queue import ChatState, LoopMode, Track


class FakeCalls:
    def __init__(self) -> None:
        self.played: list[str] = []
        self.volume: list[int] = []
        self.left: list[int] = []
        self.paused: list[int] = []
        self.fail_first_with: Exception | None = None

    async def play(self, chat_id, stream, config=None):
        if self.fail_first_with is not None:
            error, self.fail_first_with = self.fail_first_with, None
            raise error
        self.played.append(str(stream._media_path))

    async def change_volume_call(self, chat_id, volume):
        self.volume.append(int(volume))
        return volume

    async def pause(self, chat_id):
        self.paused.append(chat_id)

    async def resume(self, chat_id):
        return True

    async def leave_call(self, chat_id):
        self.left.append(chat_id)


class FakeYouTube:
    def __init__(self) -> None:
        self.broken: set[str] = set()
        self.stream_info_calls: list[str] = []
        self.related_calls = 0
        self.suggestions: list[Track] = []

    async def stream_url(self, track, video=False):
        if track.id in self.broken:
            raise StreamError("unavailable")
        return f"https://cdn/{track.id}.m4a"

    async def stream_info(self, track, video=False):
        self.stream_info_calls.append(track.id)
        return SimpleNamespace(url=await self.stream_url(track, video=video))

    async def related(self, track, limit=3):
        self.related_calls += 1
        return list(self.suggestions)[:limit]


class FakeStorage:
    def __init__(self) -> None:
        self.counters = {"tracks": 0}
        self.history: list[dict] = []
        self.saved: dict = {}
        self.meta: dict = {}

    async def chat_settings(self, chat_id):
        return {}

    async def save_chat_settings(self, chat_id, data):
        self.saved[chat_id] = data

    async def bump(self, key, amount=1):
        self.counters[key] = self.counters.get(key, 0) + amount

    async def add_history(self, user_id, track):
        self.history.append(track)

    async def get_meta(self, key, default=None):
        return self.meta.get(key, default)

    async def set_meta(self, key, value):
        self.meta[key] = value


class FakeAssistant:
    def __init__(self) -> None:
        self.invoked: list[object] = []

    async def resolve_peer(self, chat_id):
        return SimpleNamespace(chat_id=chat_id)

    async def invoke(self, request):
        self.invoked.append(request)
        return True


SETTINGS = SimpleNamespace(
    default_volume=100,
    autoplay_default=True,
    audio_quality="high",
    video_quality="720p",
    max_queue_size=20,
    np_refresh_seconds=45,
    idle_leave_seconds=300,
)


def make_player(*, assistant=None, calls=None) -> tuple[Player, FakeCalls, FakeYouTube, FakeStorage]:
    calls = calls if calls is not None else FakeCalls()
    youtube = FakeYouTube()
    storage = FakeStorage()
    player = Player(
        bot=None,
        calls=calls,
        settings=SETTINGS,
        storage=storage,
        youtube=youtube,
        assistant=assistant,
    )
    return player, calls, youtube, storage


def track(track_id: str, title: str | None = None, duration: int = 180) -> Track:
    return Track(
        id=track_id,
        title=title or track_id.title(),
        duration=duration,
        uploader="Artist",
        requested_by=7,
        requested_name="Rahul",
    )


def run(coro):
    return asyncio.run(coro)


# ── starting ────────────────────────────────────────────────────────────────
def test_play_track_starts_the_stream_and_counts_once():
    player, calls, _, storage = make_player()

    run(player.play_track(10, track("abc")))

    assert calls.played == ["https://cdn/abc.m4a"]
    assert player.queues.get(10).playing is True
    assert storage.counters["tracks"] == 1
    assert len(storage.history) == 1


def test_enqueue_starts_over_a_ghost_track():
    """A dead current track must not turn /play into a silent queue write."""
    player, calls, _, _ = make_player()
    state = player.queues.get(10)
    state.current = track("dead")
    state.playing = False
    state.started_at = 0.0

    position = run(player.enqueue(10, track("fresh")))

    assert position == 1
    assert calls.played == ["https://cdn/fresh.m4a"]
    assert state.current is not None and state.current.id == "fresh"
    assert state.queue == []


def test_enqueue_queues_while_something_is_playing():
    player, calls, _, _ = make_player()
    run(player.play_track(10, track("one")))

    position = run(player.enqueue(10, track("two")))

    assert position == 1
    assert [item.id for item in player.queues.get(10).queue] == ["two"]
    assert calls.played == ["https://cdn/one.m4a"]


def test_enqueue_rejects_duplicates():
    player, _, _, _ = make_player()
    run(player.play_track(10, track("one")))

    assert run(player.enqueue(10, track("one"))) == -1


def test_force_play_clears_the_queue():
    player, calls, _, _ = make_player()
    run(player.play_track(10, track("one")))
    run(player.enqueue(10, track("two")))
    run(player.enqueue(10, track("three")))

    run(player.force_play(10, track("forced")))

    state = player.queues.get(10)
    assert state.current is not None and state.current.id == "forced"
    assert state.queue == []
    assert calls.played[-1] == "https://cdn/forced.m4a"


# ── seek ────────────────────────────────────────────────────────────────────
def test_seek_restarts_without_counting_a_second_play():
    player, calls, _, storage = make_player()
    run(player.play_track(10, track("abc", duration=200)))
    before = player.queues.get(10)

    changed = run(player.seek(10, 90))

    state = player.queues.get(10)
    assert changed is True
    assert len(calls.played) == 2
    assert storage.counters["tracks"] == 1          # still one play
    assert len(storage.history) == 1                # no duplicate history row
    assert state.offset == 90
    assert state.elapsed() >= 90
    assert before.current is state.current


def test_seek_clamps_to_the_end_of_the_track():
    player, _, _, _ = make_player()
    run(player.play_track(10, track("abc", duration=100)))

    run(player.seek(10, 10_000))

    assert player.queues.get(10).offset == 99


# ── advancing ───────────────────────────────────────────────────────────────
def test_skip_advances_the_queue():
    player, calls, _, _ = make_player()
    run(player.play_track(10, track("one")))
    run(player.enqueue(10, track("two")))

    nxt = run(player.skip(10))

    assert nxt is not None and nxt.id == "two"
    assert player.queues.get(10).current.id == "two"
    assert calls.played[-1] == "https://cdn/two.m4a"


def test_skip_walks_past_a_broken_track():
    player, calls, youtube, _ = make_player()
    run(player.play_track(10, track("one")))
    run(player.enqueue(10, track("bad")))
    run(player.enqueue(10, track("good")))
    youtube.broken.add("bad")

    nxt = run(player.skip(10))

    assert nxt is not None and nxt.id == "good"
    assert player.queues.get(10).current.id == "good"
    assert "https://cdn/bad.m4a" not in calls.played


def test_skip_loop_one_restarts_the_same_track():
    player, calls, _, storage = make_player()
    state = run(player.restore_settings(10))
    state.loop = LoopMode.ONE
    run(player.play_track(10, track("one")))

    nxt = run(player.skip(10, natural=True))

    assert nxt is not None and nxt.id == "one"
    assert calls.played == ["https://cdn/one.m4a", "https://cdn/one.m4a"]
    assert storage.counters["tracks"] == 1  # looping is not a new play


def test_skip_with_an_empty_queue_stops_and_leaves():
    player, calls, _, _ = make_player()
    state = player.queues.get(10)
    state.current = track("one")
    state.playing = True
    state.autoplay = False

    nxt = run(player.skip(10))

    assert nxt is None
    assert state.current is None
    assert calls.left == [10]


# ── voice chat bootstrap ────────────────────────────────────────────────────
def test_voice_chat_is_opened_when_missing():
    calls = FakeCalls()
    calls.fail_first_with = NoActiveGroupCall()
    assistant = FakeAssistant()
    player, _, _, _ = make_player(calls=calls, assistant=assistant)

    run(player.play_track(10, track("one")))

    assert assistant.invoked, "the assistant should have created the voice chat"
    assert calls.played == ["https://cdn/one.m4a"]
    assert player.queues.get(10).playing is True


def test_missing_voice_chat_without_an_assistant_is_a_clear_error():
    calls = FakeCalls()
    calls.fail_first_with = NoActiveGroupCall()
    player, _, _, _ = make_player(calls=calls, assistant=None)

    with pytest.raises(StreamError) as info:
        run(player.play_track(10, track("one")))

    assert "voice chat" in str(info.value).lower()


# ── autoplay + prefetch ─────────────────────────────────────────────────────
def test_autoplay_uses_the_prefetched_suggestion():
    player, _, youtube, _ = make_player()
    state = run(player.restore_settings(10))
    state.current = track("one")
    state.playing = True
    state.prefetched = track("hint")

    picked = run(player._autoplay_track(10, state))

    assert picked is not None and picked.id == "hint"
    assert youtube.related_calls == 0
    assert state.prefetched is None


def test_prefetch_warms_the_next_queued_track():
    player, _, youtube, _ = make_player()
    run(player.play_track(10, track("one")))
    run(player.enqueue(10, track("two")))

    run(player._prefetch_worker(10))

    assert "two" in youtube.stream_info_calls


def test_prefetch_keeps_a_related_suggestion_ready():
    player, _, youtube, _ = make_player()
    youtube.suggestions = [track("next-hit")]
    state = run(player.restore_settings(10))
    state.current = track("one")
    state.playing = True

    run(player._prefetch_worker(10))

    assert state.prefetched is not None and state.prefetched.id == "next-hit"
    assert youtube.related_calls == 1


# ── stream-end guards ───────────────────────────────────────────────────────
def test_duplicate_stream_end_is_ignored():
    state = ChatState(chat_id=1, current=track("abc"), playing=True)

    assert Player.duplicate_stream_end(state, 100.0) is False
    assert Player.duplicate_stream_end(state, 100.5) is True
    assert Player.duplicate_stream_end(state, 105.0) is False


# ── persistence ─────────────────────────────────────────────────────────────
def test_snapshot_records_queue_and_modes():
    player, _, _, storage = make_player()
    state = run(player.restore_settings(10))
    state.loop = LoopMode.ALL
    state.always_on = True
    state.effects = ["bass"]
    run(player.play_track(10, track("one")))
    run(player.enqueue(10, track("two")))

    snap = player.snapshot()

    assert snap["10"]["loop"] == "all"
    assert snap["10"]["always_on"] is True
    assert snap["10"]["effects"] == ["bass"]
    assert snap["10"]["current"]["id"] == "one"
    assert [item["id"] for item in snap["10"]["queue"]] == ["two"]


def test_restore_puts_the_remembered_track_back_at_the_front():
    player, calls, _, storage = make_player()
    storage.meta["queues"] = {
        "10": {
            "current": track("one").to_dict(),
            "queue": [track("two").to_dict(), track("three").to_dict()],
            "loop": "one",
            "autoplay": False,
            "volume": 140,
            "always_on": True,
            "effects": ["nightcore"],
        }
    }

    restored = run(player.restore_queues())

    state = player.queues.get(10)
    assert restored == 1
    assert state.current is None and state.playing is False
    assert [item.id for item in state.queue] == ["one", "two", "three"]
    assert state.loop is LoopMode.ONE
    assert state.autoplay is False
    assert state.volume == 140
    assert state.always_on is True
    assert state.effects == ["nightcore"]
    assert calls.played == []            # nothing starts by itself


def test_resume_always_on_only_wakes_247_chats():
    player, calls, _, storage = make_player()
    storage.meta["queues"] = {
        "10": {"queue": [track("a").to_dict()], "always_on": True},
        "20": {"queue": [track("b").to_dict()], "always_on": False},
    }
    run(player.restore_queues())

    started = run(player.resume_always_on())

    assert started == 1
    assert calls.played == ["https://cdn/a.m4a"]
    assert player.queues.get(20).playing is False
