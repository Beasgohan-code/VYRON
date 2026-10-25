"""Search speed: the catalogue lane wins the race, and a repeat is free.

Production searches were answering in ten to twenty seconds because the
YouTube half (a walled IP) ran *first* and only then did the catalogues get a
turn. These tests pin the new contract:

* both lanes start together,
* the playable one is returned as soon as it has a page,
* the other lane is cancelled rather than left running,
* the same query twice does not cost a second round-trip.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from vyron.core import search as search_module
from vyron.core.queue import Track
from vyron.core.search import CATALOGUE_GRACE, YouTube


class FakeAlternate:
    def __init__(self, tracks=None, delay: float = 0.0, raises: Exception | None = None):
        self.tracks = tracks or []
        self.delay = delay
        self.raises = raises
        self.calls = 0

    async def search_all(self, query, limit=6, *, settings=None, order=None):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raises:
            raise self.raises
        return list(self.tracks)[:limit]


class FakeYouTube(YouTube):
    """A YouTube engine whose two network halves are fakes."""

    def __init__(self, tracks=None, delay: float = 0.0, walled: bool = False):
        self.settings = type("S", (), {"search_results": 6, "music_sources": "jiosaavn,audius"})()
        self.delay = delay
        self._tracks = tracks or []
        self._walled = walled
        self.yt_calls = 0

    def walled(self) -> bool:
        return self._walled

    async def _search_youtube(self, query, fetch, count, requester):  # type: ignore[override]
        self.yt_calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return list(self._tracks)


def _track(ident: str, title: str, source: str = "jiosaavn") -> Track:
    return Track(id=ident, title=title, duration=200, source=source, url=f"https://cdn/{ident}.m4a")


@pytest.fixture(autouse=True)
def clean_cache():
    search_module.clear_search_cache()
    yield
    search_module.clear_search_cache()


def _run(engine, *args, **kwargs):
    return asyncio.run(engine.search(*args, **kwargs))


def test_the_playable_lane_wins_and_youtube_is_cancelled(monkeypatch):
    fast = [
        _track("a", "Kesariya"),
        _track("b", "Kesariya (Reprise)"),
        _track("c", "Kesariya Lofi"),
    ]
    monkeypatch.setattr(search_module.alternate, "search_all", FakeAlternate(fast).search_all)
    engine = FakeYouTube(tracks=[_track("yt1", "Kesariya", "youtube")], delay=5.0)

    started = time.monotonic()
    result = _run(engine, "Kesariya", limit=6)
    elapsed = time.monotonic() - started

    assert {track.id for track in result} == {"a", "b", "c"}
    assert elapsed < CATALOGUE_GRACE + 1.0, f"took {elapsed:.1f}s — YouTube was awaited"
    assert engine.yt_calls == 1, "YouTube should have been started, then abandoned"


def test_a_walled_youtube_is_still_asked_for_its_results(monkeypatch):
    """The wall is about streams, not about naming a song.

    Skipping the YouTube half once a stream had failed is what made every text
    query answer "No results" for hours afterwards: the catalogues alone were
    left doing the work, and they throttle.
    """
    fast = [_track("a", "Kesariya")]
    monkeypatch.setattr(search_module.alternate, "search_all", FakeAlternate(fast).search_all)
    engine = FakeYouTube(tracks=[_track("yt1", "Kesariya (Official)", "youtube")], walled=True)

    result = _run(engine, "Kesariya", limit=6)

    assert engine.yt_calls == 1, "a wall must not hide the whole catalogue from us"
    assert result[0].id == "a", "the playable lane still ranks first"
    assert {track.id for track in result} == {"a", "yt1"}


def test_thin_catalogues_fall_back_to_youtube(monkeypatch):
    """One match is not a page; YouTube gets the rest of the budget."""
    monkeypatch.setattr(
        search_module.alternate, "search_all", FakeAlternate([_track("a", "Kesariya")]).search_all
    )
    engine = FakeYouTube(
        tracks=[_track("yt1", "Tum Hi Ho", "youtube")], delay=0.05
    )

    result = _run(engine, "Kesariya", limit=6)

    assert engine.yt_calls == 1, "the YouTube lane was consulted"
    assert [track.id for track in result] == ["a", "yt1"], "both lanes, catalogue first"


def test_the_same_song_from_both_lanes_keeps_the_playable_copy(monkeypatch):
    """A walled YouTube id and the catalogue's copy are one song, not two."""
    monkeypatch.setattr(
        search_module.alternate,
        "search_all",
        FakeAlternate([_track("a", "Kesariya"), _track("b", "Tum Hi Ho")]).search_all,
    )
    engine = FakeYouTube(tracks=[_track("yt1", "Kesariya", "youtube")], delay=0.05)

    result = _run(engine, "Kesariya", limit=6)

    assert [track.id for track in result] == ["a", "b"]


def test_results_that_share_nothing_with_the_query_do_not_count(monkeypatch):
    """`.play Wrong` came back as five songs with "play" in the title.

    A catalogue answers *something* for any string, so "the page is full" has
    to mean "full of things that mention what was asked for" — otherwise the
    off-topic page wins the race and YouTube is never consulted.
    """
    off_topic = [
        _track("a", "Ready to play"),
        _track("b", "Tokyo Machine - PLAY"),
        _track("c", "Play"),
    ]
    monkeypatch.setattr(search_module.alternate, "search_all", FakeAlternate(off_topic).search_all)
    engine = FakeYouTube(tracks=[_track("yt1", "Wrong", "youtube")], delay=0.05)

    result = _run(engine, "Wrong", limit=6)

    assert engine.yt_calls == 1, "the off-topic page should not have ended the search"
    assert [track.id for track in result][0] == "yt1", "the real match ranks first"


def test_a_broken_catalogue_does_not_break_the_search(monkeypatch):
    monkeypatch.setattr(
        search_module.alternate,
        "search_all",
        FakeAlternate(raises=RuntimeError("jiosaavn is down")).search_all,
    )
    engine = FakeYouTube(tracks=[_track("yt1", "Kesariya", "youtube")])

    result = _run(engine, "Kesariya", limit=6)

    assert [track.id for track in result] == ["yt1"]


def test_the_same_query_is_answered_from_cache(monkeypatch):
    fake = FakeAlternate([_track("a", "Kesariya")])
    monkeypatch.setattr(search_module.alternate, "search_all", fake.search_all)
    engine = FakeYouTube(tracks=[])

    first = _run(engine, "Kesariya", limit=6)
    second = _run(engine, "  KESARIYA ", limit=6)

    assert [track.id for track in first] == ["a"]
    assert [track.id for track in second] == ["a"]
    assert fake.calls == 1, "the second search should have hit the cache"


def test_a_cached_answer_credits_the_person_who_asked(monkeypatch):
    monkeypatch.setattr(
        search_module.alternate, "search_all", FakeAlternate([_track("a", "Kesariya")]).search_all
    )
    engine = FakeYouTube(tracks=[])

    first = _run(engine, "Kesariya", limit=6, requester=(111, "Asha"))
    second = _run(engine, "Kesariya", limit=6, requester=(222, "Ravi"))

    assert (first[0].requested_by, first[0].requested_name) == (111, "Asha")
    assert (second[0].requested_by, second[0].requested_name) == (222, "Ravi")


def test_an_expired_cache_entry_is_not_served(monkeypatch):
    fake = FakeAlternate([_track("a", "Kesariya")])
    monkeypatch.setattr(search_module.alternate, "search_all", fake.search_all)
    monkeypatch.setattr(search_module, "SEARCH_TTL", -1.0)
    engine = FakeYouTube(tracks=[])

    _run(engine, "Kesariya", limit=6)
    _run(engine, "Kesariya", limit=6)

    assert fake.calls == 2


def test_a_walled_youtube_gets_a_glance_not_the_deadline(monkeypatch):
    """Its names are worth 0.6 s, not six: nothing it finds can be played here."""
    monkeypatch.setattr(
        search_module.alternate, "search_all", FakeAlternate([_track("a", "Kesariya")]).search_all
    )
    engine = FakeYouTube(tracks=[_track("yt1", "Kesariya (Official)", "youtube")], delay=4.0, walled=True)

    started = time.monotonic()
    result = _run(engine, "Kesariya", limit=6)
    elapsed = time.monotonic() - started

    assert [track.id for track in result] == ["a"]
    assert elapsed < search_module.WALLED_GLANCE + 1.0, f"took {elapsed:.1f}s"


# ── a walled IP must not re-prove the wall on every track ──────────────────
class WalledYouTube(YouTube):
    """The IP is refused: yt-dlp cannot work, a mirror and a catalogue can."""

    def __init__(self, *, mirror=None, substitute=None, mirror_delay=0.0, sub_delay=0.0):
        self.settings = type(
            "S", (), {"video_quality": "720p", "stream_failure_ttl": 60}
        )()
        self._mirror = mirror
        self._substitute_result = substitute
        self.mirror_delay = mirror_delay
        self.sub_delay = sub_delay
        self.mirror_calls = 0
        self.sub_calls = 0
        self.ladder_calls = 0
        self._stream_cache = {}
        self._failures = {}
        self._failure_reasons = {}
        self._client_hint = None
        self._wall_until = 0.0
        self._wall_logged = False

    def walled(self) -> bool:
        return True

    async def _public_fallback(self, track, *, video=False):  # type: ignore[override]
        self.mirror_calls += 1
        if self.mirror_delay:
            await asyncio.sleep(self.mirror_delay)
        return self._mirror

    async def _substitute(self, track, *, video=False, fresh=False):  # type: ignore[override]
        self.sub_calls += 1
        if self.sub_delay:
            await asyncio.sleep(self.sub_delay)
        return self._substitute_result

    async def _async_extract(self, *args, **kwargs):  # type: ignore[override]
        self.ladder_calls += 1
        raise RuntimeError("Failed to extract any player response")


def _stream(source: str):
    from vyron.core.search import StreamInfo

    return StreamInfo(url=f"https://cdn/{source}.m4a", source=source, expires_at=time.time() + 600)


def test_a_walled_ip_asks_the_mirror_before_the_yt_dlp_ladder():
    engine = WalledYouTube(mirror=_stream("invidious"))
    result = asyncio.run(engine._resolve_stream(_track("yt-1", "Song")))

    assert result.source == "invidious"
    assert engine.mirror_calls == 1
    # The whole point: proving the wall again costs two socket timeouts, and it
    # is the difference between a 2-second tap and a 15-second one.
    assert engine.ladder_calls == 0


def test_the_catalogue_and_the_mirror_are_asked_together():
    # Mirror is slow, the catalogue is quick: the quick one answers, and the
    # slow lane is cancelled instead of being awaited for the rest of the budget.
    engine = WalledYouTube(
        mirror=_stream("invidious"), substitute=_stream("jiosaavn"),
        mirror_delay=5.0, sub_delay=0.0,
    )
    started = time.perf_counter()
    result = asyncio.run(engine._resolve_stream(_track("yt-2", "Song")))
    took = time.perf_counter() - started

    assert result.source == "jiosaavn"
    assert took < 2.0, f"both lanes were not raced ({took:.1f}s)"
    assert engine.mirror_calls == 1 and engine.sub_calls == 1


def test_when_neither_lane_answers_the_ladder_is_still_tried():
    from vyron.core.search import MediaError

    engine = WalledYouTube(mirror=None, substitute=None)
    with pytest.raises(MediaError):
        asyncio.run(engine._resolve_stream(_track("yt-3", "Song")))
    assert engine.ladder_calls >= 1
