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
        self.stream_url_calls: list[str] = []
        self.related_calls = 0
        self.suggestions: list[Track] = []
        self.searches: list[str] = []
        self.search_results: list[Track] = []

    async def stream_url(self, track, video=False):
        self.stream_url_calls.append(track.id)
        if track.id in self.broken:
            raise StreamError("unavailable")
        return f"https://cdn/{track.id}.m4a"

    async def stream_info(self, track, video=False):
        self.stream_info_calls.append(track.id)
        return SimpleNamespace(url=await self.stream_url(track, video=video))

    async def related(self, track, limit=3):
        self.related_calls += 1
        return list(self.suggestions)[:limit]

    async def search(self, query, limit=5, requester=(0, "")):
        self.searches.append(query)
        return list(self.search_results)


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
    play_from_disk=True,
    preheat_depth=2,
    preheat_seconds=25,
)


def make_player(*, assistant=None, calls=None, downloader=None, settings=None):
    calls = calls if calls is not None else FakeCalls()
    youtube = FakeYouTube()
    storage = FakeStorage()
    player = Player(
        bot=None,
        calls=calls,
        settings=settings or SETTINGS,
        storage=storage,
        youtube=youtube,
        assistant=assistant,
        downloader=downloader,
    )
    return player, calls, youtube, storage


def track(track_id: str, title: str | None = None, duration: int = 180, **extra) -> Track:
    return Track(
        id=track_id,
        title=title or track_id.title(),
        duration=duration,
        uploader=extra.pop("uploader", "Artist"),
        requested_by=7,
        requested_name="Rahul",
        **extra,
    )


def run(coro):
    return asyncio.run(coro)


def _async_return(value):
    async def inner(*args, **kwargs):
        return list(value) if isinstance(value, list) else value

    return inner


# ── which engine plays it ───────────────────────────────────────────────────
def test_a_direct_catalogue_track_streams_without_a_download():
    """JioSaavn/Audius hand out the audio: no file on disk, no wait."""
    downloaded: list[str] = []

    class Downloader:
        async def fetch(self, track, video=False, on_progress=None):
            downloaded.append(track.id)
            return __import__("pathlib").Path(f"/tmp/{track.id}.mp3")

    player, calls, _, _ = make_player(downloader=Downloader())
    catalogue = Track(
        id="jx1", title="Kesariya", duration=200, source="jiosaavn",
        url="https://cdn.jiosaavn/k.m4a",
    )

    run(player.play_track(11, catalogue))

    assert downloaded == []
    assert calls.played == ["https://cdn.jiosaavn/k.m4a"]


def test_a_walled_youtube_track_asks_the_resolver_instead_of_downloading(monkeypatch):
    """The walled path: one cached resolver answer, not ladder-then-download."""
    downloaded: list[str] = []

    class Downloader:
        async def fetch(self, track, video=False, on_progress=None):
            downloaded.append(track.id)
            return __import__("pathlib").Path(f"/tmp/{track.id}.mp3")

    player, calls, youtube, _ = make_player(downloader=Downloader())
    monkeypatch.setattr(Player, "_substitute_first", staticmethod(lambda track: True))

    run(player.play_track(12, track("yyyyyyyyyyy", "Song")))

    assert downloaded == []
    assert youtube.stream_info_calls == ["yyyyyyyyyyy"]
    assert calls.played == ["https://cdn/yyyyyyyyyyy.m4a"]


def test_an_unresolvable_track_still_tries_the_disk_before_failing(monkeypatch):
    """When every resolver is having a bad day, a cached file beats an error."""
    from pathlib import Path

    attempts: list[str] = []

    class Downloader:
        async def fetch(self, track, video=False, on_progress=None):
            attempts.append(track.id)
            if len(attempts) == 1:
                raise RuntimeError("first attempt: no bytes yet")
            path = Path("/tmp/cached-on-disk.mp3")
            await asyncio.to_thread(path.write_bytes, b"ID3")
            return path

    player, calls, youtube, _ = make_player(downloader=Downloader())

    from vyron.core.search import MediaError

    async def refuse(track, video=False):
        raise MediaError("no results")

    monkeypatch.setattr(youtube, "stream_info", refuse)

    run(player.play_track(13, Track(id="losttrack01", title="Lost", duration=90, source="youtube")))

    # disk first (failed), the resolver (failed), then the disk again (worked)
    assert attempts == ["losttrack01", "losttrack01"]
    assert calls.played == ["/tmp/cached-on-disk.mp3"]


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

def test_autoplay_prefers_the_mood_lane_over_related_videos():
    """Related videos are a *source*, not the winner: a Malayalam room must not
    get whatever YouTube's graph likes."""
    player, calls, youtube, storage = make_player()
    state = player.queues.get(10)
    state.current = Track(id="seed0000001", title="Kessoku Band - Guitar, Loneliness (Official Video)", duration=200, uploader="Anime")
    state.mood = "chill"
    state.language = "malayalam"
    state.autoplay = True
    youtube.search_results = [Track(id="fresh000001", title="Lofi Malayalam Chill Mix", duration=180, uploader="x")]
    youtube.suggestions = [Track(id="rel00000001", title="Gaming Montage", duration=600, uploader="x")]

    picked = run(player._autoplay_track(10, state))

    assert picked is not None and picked.id == "fresh000001"
    assert youtube.searches and "malayalam" in youtube.searches[0].lower()


def test_the_lane_pick_is_what_gets_prefetched():
    """Prefetching a raw related video made it jump the queue at track end."""
    player, calls, youtube, storage = make_player()
    state = player.queues.get(10)
    state.current = track("seed")
    state.playing = True
    state.mood = "chill"
    state.language = "malayalam"
    state.autoplay = True
    youtube.search_results = [Track(id="fresh000001", title="Lofi Malayalam Chill Mix", duration=180, uploader="x")]
    youtube.suggestions = [Track(id="rel00000001", title="Gaming Montage", duration=600, uploader="x")]

    run(player._prefetch_worker(10))

    assert state.prefetched is not None and state.prefetched.id == "fresh000001"


def test_autoplay_falls_back_to_related_videos_when_the_lane_is_empty():
    player, calls, youtube, storage = make_player()
    state = player.queues.get(10)
    state.current = Track(id="seed0000001", title="Song", duration=200, uploader="x")
    state.autoplay = True
    youtube.search_results = []
    youtube.suggestions = [Track(id="rel00000001", title="Neighbour", duration=200, uploader="x")]

    picked = run(player._autoplay_track(10, state))

    assert picked is not None and picked.id == "rel00000001"
    assert youtube.related_calls >= 1


def test_autoplay_mood_and_language_survive_a_persist_round_trip():
    player, calls, youtube, storage = make_player()
    state = player.queues.get(10)
    state.mood, state.language = "chill", "hindi"

    run(player.persist(10))

    assert storage.saved[10]["mood"] == "chill"
    assert storage.saved[10]["language"] == "hindi"


# ── disk playback ───────────────────────────────────────────────────────────
class FakeDownloader:
    def __init__(self, path, *, fail=False):
        self.path = path
        self.fail = fail
        self.calls: list[tuple[str, bool]] = []

    async def fetch(self, track, *, video=False, on_progress=None):
        self.calls.append((track.id, video))
        if self.fail:
            raise RuntimeError("every engine failed")
        return self.path


def test_playback_streams_the_downloaded_file(tmp_path):
    local = tmp_path / "track.mp3"
    local.write_bytes(b"ID3")
    downloader = FakeDownloader(local)
    player, calls, youtube, storage = make_player(downloader=downloader)

    run(player.play_track(10, track("abc12345678")))

    assert downloader.calls == [("abc12345678", False)]
    assert calls.played == [str(local)]
    assert youtube.stream_url_calls == []  # no remote URL was ever resolved


def test_playback_falls_back_to_the_stream_url_when_the_download_fails(tmp_path):
    downloader = FakeDownloader(tmp_path / "missing.mp3", fail=True)
    player, calls, youtube, storage = make_player(downloader=downloader)

    run(player.play_track(10, track("abc12345678")))

    assert downloader.calls and youtube.stream_url_calls == ["abc12345678"]
    assert calls.played == ["https://cdn/abc12345678.m4a"]


def test_disk_playback_can_be_switched_off(tmp_path):
    from types import SimpleNamespace

    local = tmp_path / "track.mp3"
    local.write_bytes(b"ID3")
    downloader = FakeDownloader(local)
    settings = SimpleNamespace(**{**vars(SETTINGS), "play_from_disk": False})
    player, calls, youtube, storage = make_player(downloader=downloader, settings=settings)

    run(player.play_track(10, track("abc12345678")))

    assert downloader.calls == []
    assert youtube.stream_url_calls == ["abc12345678"]


# ── assistant membership ────────────────────────────────────────────────────
def test_assistant_join_falls_back_to_an_invite_link(monkeypatch):
    from vyron import runtime as runtime_module

    calls = {"join": [], "export": 0, "member": 0}

    class Assistant:
        async def get_chat_member(self, chat_id, who):
            calls["member"] += 1
            raise RuntimeError("USER_NOT_PARTICIPANT")

        async def join_chat(self, target):
            calls["join"].append(target)
            if isinstance(target, int):
                raise RuntimeError("CHANNEL_PRIVATE")
            return True

    class Bot:
        async def export_chat_invite_link(self, chat_id):
            calls["export"] += 1
            return "https://t.me/+invite"

    monkeypatch.setattr(runtime_module.runtime, "assistant", Assistant())
    monkeypatch.setattr(runtime_module.runtime, "bot", Bot())

    player, _, _, _ = make_player()
    assert run(player.ensure_assistant(-100)) is True
    # The `t.me/+Hash` form is rewritten to the spelling every client accepts.
    assert calls["join"] == [-100, "https://t.me/joinchat/invite"]
    assert calls["export"] == 1


def test_assistant_already_joined_is_a_no_op(monkeypatch):
    from vyron import runtime as runtime_module

    joined = {"n": 0}

    class Assistant:
        async def get_chat_member(self, chat_id, who):
            return SimpleNamespace(status="member")

        async def join_chat(self, target):  # pragma: no cover - must not run
            joined["n"] += 1

    monkeypatch.setattr(runtime_module.runtime, "assistant", Assistant())
    player, _, _, _ = make_player()
    assert run(player.ensure_assistant(-100)) is True
    assert joined["n"] == 0


def test_without_an_assistant_everything_still_reports_cleanly(monkeypatch):
    from vyron import runtime as runtime_module

    monkeypatch.setattr(runtime_module.runtime, "assistant", None)
    player, _, _, _ = make_player()
    assert run(player._assistant_joined(-100)) is False
    assert run(player.ensure_assistant(-100)) is False


# ── mid-song recovery ───────────────────────────────────────────────────────
def _end_event(chat_id: int = 10):
    return SimpleNamespace(chat_id=chat_id, stream_type="AUDIO")


def test_an_early_stream_end_resumes_the_same_song(monkeypatch):
    """A 403 at 0:40 is a drop, not "the song finished"."""
    player, calls, youtube, storage = make_player()
    song = track("abc", duration=240, title="Kesariya", uploader="Arijit Singh")
    run(player.play_track(10, song))
    state = player.queues.get(10)
    state.started_at -= 40                      # pretend we are 40 s in

    fresh = track("xyz", duration=240, title="Kesariya", uploader="Arijit Singh", source="jiosaavn")
    monkeypatch.setattr(
        "vyron.core.sources.fallback_search",
        _async_return([fresh]),
    )
    youtube.search_results = [track("yt2", duration=240, title="Kesariya")]

    run(player.on_stream_end(None, _end_event()))

    state = player.queues.get(10)
    assert state.current.id == "xyz"            # another source, same song
    assert state.offset >= 30                   # resumed where it stopped
    assert len(calls.played) == 2
    assert storage.counters["tracks"] == 1      # a recovery is not a new play


def test_a_finished_song_still_advances(monkeypatch):
    player, calls, _, _ = make_player()
    run(player.play_track(10, track("abc", duration=200)))
    run(player.enqueue(10, track("next", duration=120)))
    state = player.queues.get(10)
    state.started_at -= 199                     # the song is over

    monkeypatch.setattr("vyron.core.sources.fallback_search", _async_return([]))
    run(player.on_stream_end(None, _end_event()))

    assert player.queues.get(10).current.id == "next"


def test_recovery_is_rate_limited_per_chat(monkeypatch):
    player, calls, youtube, _ = make_player()
    monkeypatch.setattr("vyron.core.sources.fallback_search", _async_return([]))
    youtube.search_results = [track("yt2", duration=240, title="same")]

    async def scenario():
        first = await player._recover_stream(10, SimpleNamespace(current=track("abc", duration=240), is_video=False), 40)
        second = await player._recover_stream(10, SimpleNamespace(current=track("abc", duration=240), is_video=False), 40)
        return first, second

    first, second = run(scenario())
    assert first is True and second is False


# ── queue warming ───────────────────────────────────────────────────────────
def test_preheat_resolves_the_next_two_tracks():
    player, _, youtube, _ = make_player()
    run(player.play_track(10, track("one", duration=180)))
    run(player.enqueue(10, track("two")))
    run(player.enqueue(10, track("three")))
    run(player.enqueue(10, track("four")))
    youtube.stream_info_calls.clear()

    run(player._prefetch_worker(10))

    assert youtube.stream_info_calls == ["two", "three"]     # depth 2, not more


def test_preheat_does_nothing_while_paused_or_idle():
    player, _, youtube, _ = make_player()
    run(player.play_track(10, track("one")))
    run(player.enqueue(10, track("two")))
    player.queues.get(10).paused = True
    youtube.stream_info_calls.clear()

    run(player._prefetch_worker(10))
    assert youtube.stream_info_calls == []

    player.queues.get(10).playing = False
    player.queues.get(10).paused = False
    run(player._prefetch_worker(10))
    assert youtube.stream_info_calls == []


def test_preheat_respects_its_time_budget():
    """A slow extraction must not keep a preheat pass alive forever."""
    slow_settings = SimpleNamespace(
        **{**vars(SETTINGS), "preheat_depth": 3, "preheat_seconds": 0.01}
    )
    player, _, youtube, _ = make_player(settings=slow_settings)
    run(player.play_track(10, track("one", duration=180)))
    run(player.enqueue(10, track("two")))
    run(player.enqueue(10, track("three")))
    youtube.stream_info_calls.clear()

    original = youtube.stream_info

    async def slower(candidate, video=False):
        import asyncio as _asyncio

        await _asyncio.sleep(0.02)
        return await original(candidate, video=video)

    youtube.stream_info = slower
    run(player._prefetch_worker(10))
    # the first warm-up costs more than the whole budget, so it is the last one
    assert youtube.stream_info_calls == ["two"]


# ── a restored queue resumes where it stopped (#9) ──────────────────────────
def test_queue_snapshot_remembers_the_position():
    player, _, _, storage = make_player()
    state = player.queues.get(10)
    state.current = track("abc", "Kesariya", duration=268)
    state.queue = [track("def", "Next", duration=200)]
    state.offset = 34.0        # not playing: elapsed() is the stored offset

    snap = player.snapshot()["10"]
    assert snap["position"] == 34.0

    fresh, _, _, fresh_storage = make_player()
    fresh_storage.meta["queues"] = {"10": snap}
    run(fresh.restore_queues())
    restored = fresh.queues.get(10)
    assert restored.current is None and restored.playing is False
    assert restored.queue[0].id == "abc"
    assert restored.offset == 34.0


def test_a_position_near_the_end_starts_over():
    player, _, _, storage = make_player()
    storage.meta["queues"] = {
        "10": {
            "current": track("abc", "Short", duration=200).to_dict(),
            "queue": [],
            "position": 195.0,          # 5 s from the end
        }
    }
    run(player.restore_queues())
    assert player.queues.get(10).offset == 185.0    # clamped to duration - 15


def test_resume_always_on_seeks_to_the_restored_position():
    player, calls, _, storage = make_player()
    storage.meta["queues"] = {
        "10": {
            "current": track("abc", "Kesariya", duration=268).to_dict(),
            "queue": [],
            "always_on": True,
            "position": 61.0,
        }
    }
    run(player.restore_queues())
    state = player.queues.get(10)
    assert state.offset == 61.0

    run(player.resume_always_on())
    assert calls.played == ["https://cdn/abc.m4a"]
    # the stream really started at 61 s, not at 0 s…
    assert state.offset == 61.0 and state.playing is True
    # …and a second pass does nothing (the chat is already playing)
    assert run(player.resume_always_on()) == 0


def test_a_substituted_stream_is_not_announced_as_video():
    """A catalogue audio URL must not be handed to ntgcalls as a video track."""
    from vyron.core.player import _is_video_stream

    from vyron.core.search import StreamInfo

    assert _is_video_stream(StreamInfo(url="u", ext="mp4", mime="video/mp4")) is True
    assert _is_video_stream(StreamInfo(url="u", ext="mp3", mime="audio/mpeg")) is False
    # a mime-less answer falls back to the extension
    assert _is_video_stream(StreamInfo(url="u", ext="webm", mime="")) is True
    assert _is_video_stream(StreamInfo(url="u", ext="m4a", mime="")) is False


# ── the end of a session ───────────────────────────────────────────────────
def test_the_queue_running_out_leaves_the_call_and_says_so(monkeypatch):
    """A finished queue is the assistant's cue to leave the voice chat.

    Radio mode used to be on by default, so `_autoplay_track` always found
    something and the bot never let go of the call: the queue was finished but
    nobody left. The card now says the session ended and offers "again" and
    "radio" instead of expecting a typed command.
    """
    sent: list[str] = []

    class Bot:
        async def send_rich_message(self, **kwargs):  # pragma: no cover
            sent.append(str(kwargs))
            return SimpleNamespace(id=1)

        async def send_message(self, **kwargs):
            sent.append(kwargs.get("text", ""))
            return SimpleNamespace(id=1)

        async def delete_messages(self, chat_id, message_id):
            return True

    player, calls, youtube, _ = make_player()
    player.bot = Bot()
    state = player.queues.get(10)
    run(player.play_track(10, track("one")))
    state.np_message_id = 999          # a poster is on screen
    youtube.search_results = []
    youtube.suggestions = []

    skipped = run(player.skip(10, natural=True))

    assert skipped is None
    assert calls.left == [10], "the assistant must leave when nothing is left"
    assert state.current is None and state.queue == []
    assert state.np_message_id is None
    body = "\n".join(sent)
    # The heading is small-caps, so the buttons are what identify the card.
    assert "Play again" in body and "Radio" in body
    assert "left the voice chat" in body


def test_stop_keeps_the_call_when_the_chat_asked_for_247():
    player, calls, _, _ = make_player()
    state = player.queues.get(10)
    state.always_on = True
    run(player.play_track(10, track("one")))

    run(player.stop(10, leave=not state.always_on))

    assert calls.left == []
    assert state.current is None


def test_radio_mode_is_off_unless_someone_chose_it():
    """An old saved `"autoplay": true` was the *default*, not a decision."""
    player, _, _, storage = make_player(settings=SimpleNamespace(**{**SETTINGS.__dict__, "autoplay_default": False}))
    storage.meta["chat_settings"] = {
        "10": {"autoplay": True},                      # written by the old default
        "11": {"autoplay": False},                     # a real decision
        "12": {"autoplay": True, "autoplay_set": True},  # chosen with /autoplay
    }

    class S:
        def __init__(self):
            self.data = storage.meta["chat_settings"]

        async def chat_settings(self, chat_id):
            return self.data.get(str(chat_id), {})

    player.storage = S()
    assert run(player.restore_settings(10)).autoplay is False
    assert run(player.restore_settings(11)).autoplay is False
    chosen = run(player.restore_settings(12))
    assert chosen.autoplay is True and chosen.autoplay_set is True


# ── effects ─────────────────────────────────────────────────────────────────
def test_switching_a_filter_on_is_heard_in_the_song_that_is_playing():
    """ntgcalls takes ``-af`` at stream start, so a live change re-opens the
    stream where it is: same song, same second, same one play."""
    player, calls, _, storage = make_player()
    run(player.play_track(10, track("abc", duration=200)))
    player.queues.get(10).started_at -= 42          # 42 s into the song
    filters: list = []

    async def play(chat_id, stream, config=None):
        filters.append(stream._ffmpeg_parameters)
        calls.played.append(str(stream._media_path))

    calls.play = play
    player.queues.get(10).effects = ["bass"]

    changed = run(player.reapply_effects(10))

    state = player.queues.get(10)
    assert changed is True
    assert filters == ['-ss 42 -af "bass=g=12:f=110:w=0.6"']
    assert state.current is not None and state.current.id == "abc"
    assert storage.counters["tracks"] == 1          # not a second play
    assert len(storage.history) == 1
    assert state.offset >= 42


def test_an_effects_change_with_nothing_playing_does_not_touch_the_call():
    player, calls, _, _ = make_player()
    player.queues.get(10).current = track("abc")

    assert run(player.reapply_effects(10)) is False
    assert calls.played == []


# ── the first play in a group that has never met the assistant ──────────────
def test_inviting_the_assistant_still_makes_the_track_current(monkeypatch):
    """The invite retry used to `return` before the bookkeeping.

    That is the path where audio started but `state.current` was never set: no
    poster, no clock, no play counted — the "the picture is not there when it
    plays" report, on the very first `/play` in a group.
    """
    from pytgcalls.exceptions import NotInCallError

    from vyron.runtime import runtime

    player, calls, _, storage = make_player()
    calls.fail_first_with = NotInCallError()

    class Assistant:
        def __init__(self):
            self.joined: list[object] = []

        async def get_chat_member(self, chat_id, user):
            raise RuntimeError("USER_NOT_PARTICIPANT")

        async def join_chat(self, target):
            self.joined.append(target)

    assistant = Assistant()
    monkeypatch.setattr(runtime, "assistant", assistant, raising=False)

    run(player.play_track(10, track("abc")))

    state = player.queues.get(10)
    assert assistant.joined, "the assistant is invited into the chat"
    assert calls.played == ["https://cdn/abc.m4a"]
    assert state.current is not None and state.current.id == "abc"
    assert state.playing is True
    assert state.started_at > 0
    assert storage.counters["tracks"] == 1
