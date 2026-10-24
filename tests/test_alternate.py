"""The substitution tier: when YouTube refuses the server, play the song anyway.

The production failure this covers is not a per-video one. Every client in the
ladder answers `Failed to extract any player response`, which means the IP is
walled and no extractor option will help. What does help is the same song from
a catalogue that serves its own audio — provided the matching is strict enough
to never quietly play the wrong track.
"""
from __future__ import annotations

import asyncio

import pytest

from vyron.core import alternate
from vyron.core.queue import Track
from vyron.core.search import YouTube


@pytest.fixture(autouse=True)
def _clean_cache():
    alternate.reset_cache()
    yield
    alternate.reset_cache()


class FakeSettings:
    alternate_sources = "jiosaavn,audius"
    youtube_wall_window = 900
    stream_fallback = True
    stream_cache_ttl = 600
    video_quality = "720p"

    def __getattr__(self, name):  # any other knob reads as "unset"
        return ""


# ── matching ────────────────────────────────────────────────────────────────
def test_upload_noise_is_not_part_of_the_song_name():
    assert alternate.clean_title("Kesariya (Official Video) | Brahmastra") == "Kesariya Brahmastra"
    assert alternate.clean_title("Tum Hi Ho - Arijit Singh - Topic") == "Tum Hi Ho - Arijit Singh"
    assert alternate.clean_title("Believer [4K Remastered]") == "Believer"


def test_the_same_song_by_the_same_artist_and_length_is_accepted():
    wanted = Track(id="yt1", title="Kesariya (Official Video)", duration=268, uploader="Sony Music India")
    candidate = Track(
        id="saavn1", title="Kesariya", duration=268, uploader="Arijit Singh", source="jiosaavn"
    )

    assert alternate.score(wanted, candidate) >= alternate.ACCEPT_SCORE


def test_a_different_song_is_never_substituted():
    wanted = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")
    wrong = Track(id="saavn9", title="Raataan Lambiyan", duration=190, uploader="Jubin Nautiyal")

    assert alternate.score(wanted, wrong) == 0.0


def test_a_different_cut_of_the_same_song_is_rejected():
    """A 30-second preview or a 3-minute-longer remix is not what was asked."""
    wanted = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")
    preview = Track(id="saavn2", title="Kesariya", duration=30, uploader="Arijit Singh")
    remix = Track(id="saavn3", title="Kesariya", duration=420, uploader="Arijit Singh")

    assert alternate.score(wanted, preview) == 0.0
    assert alternate.score(wanted, remix) == 0.0


def test_a_lofi_variant_loses_to_the_original():
    wanted = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")
    original = Track(id="ok", title="Kesariya", duration=268, uploader="Arijit Singh")
    lofi = Track(id="lofi", title="Kesariya Lofi", duration=268, uploader="Arijit Singh")

    assert alternate.score(wanted, original) > alternate.score(wanted, lofi)


# ── the tier itself ─────────────────────────────────────────────────────────
def test_find_picks_the_best_candidate(monkeypatch):
    async def fake(name, query, limit):
        if name == "jiosaavn":
            return [
                Track(id="far", title="Kesariya", duration=120, url="https://cdn/far.mp3", source="jiosaavn"),
                Track(id="hit", title="Kesariya", duration=268, url="https://cdn/hit.mp3", source="jiosaavn"),
            ]
        return []

    monkeypatch.setattr(alternate, "_from_source", fake)
    wanted = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")

    found = asyncio.run(alternate.find(wanted, settings=FakeSettings()))
    assert found is not None and found.id == "hit"


def test_a_track_with_no_match_stays_unmatched(monkeypatch):
    async def fake(name, query, limit):
        return [Track(id="nope", title="Completely Different", duration=100, url="https://cdn/x.mp3")]

    monkeypatch.setattr(alternate, "_from_source", fake)
    wanted = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")

    assert asyncio.run(alternate.find(wanted, settings=FakeSettings())) is None


def test_the_stream_info_is_a_real_audio_url(monkeypatch):
    async def fake(name, query, limit):
        return [
            Track(
                id="hit",
                title="Kesariya",
                duration=268,
                url="https://aac.saavncdn.com/1/cover-320.mp3",
                source="jiosaavn",
            )
        ]

    monkeypatch.setattr(alternate, "_from_source", fake)
    wanted = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")

    info = asyncio.run(alternate.stream_info(wanted, settings=FakeSettings()))
    assert info is not None
    assert info.url.endswith(".mp3")
    assert info.mime == "audio/mpeg"
    assert info.source == "jiosaavn"


def test_a_direct_track_needs_no_lookup(monkeypatch):
    """JioSaavn/Audius tracks *are* audio: no search, no extraction."""

    async def explode(*args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("a direct track must not be searched again")

    monkeypatch.setattr(alternate, "search_all", explode)
    track = Track(
        id="saavn1", title="Kesariya", duration=268, url="https://cdn/x.mp3", source="jiosaavn"
    )

    info = asyncio.run(alternate.stream_info(track, settings=FakeSettings()))
    assert info is not None and info.url == "https://cdn/x.mp3"


# ── the wall ────────────────────────────────────────────────────────────────
def test_the_wall_is_remembered_from_youtubes_own_words():
    engine = YouTube.__new__(YouTube)
    engine.settings = FakeSettings()
    engine._wall_until = 0.0
    engine._wall_logged = False

    assert engine.walled() is False
    engine._note_wall("ERROR: [youtube] abc: Failed to extract any player response")
    assert engine.walled() is True
    assert engine.wall_seconds_left() > 0

    engine.clear_wall()
    assert engine.walled() is False


def test_a_per_video_error_does_not_trigger_the_wall():
    engine = YouTube.__new__(YouTube)
    engine.settings = FakeSettings()
    engine._wall_until = 0.0
    engine._wall_logged = False

    engine._note_wall("This video is private")
    assert engine.walled() is False


def test_a_walled_server_resolves_streams_by_substitution(monkeypatch):
    engine = YouTube.__new__(YouTube)
    engine.settings = FakeSettings()
    engine._wall_until = 0.0
    engine._wall_logged = False
    engine._stream_cache = {}
    engine._failures = {}
    engine._failure_reasons = {}
    engine._inflight = {}
    engine._client_hint = None
    engine._note_wall("Failed to extract any player response")

    called: list[str] = []

    async def fake_substitute(track, *, video=False, fresh=False):
        called.append(track.id)
        from vyron.core.search import StreamInfo

        return StreamInfo(url="https://cdn/copy.mp3", ext="mp3", mime="audio/mpeg", source="jiosaavn")

    monkeypatch.setattr(engine, "_substitute", fake_substitute)
    monkeypatch.setattr(YouTube, "_client_ladder", lambda self: (_ for _ in ()).throw(
        AssertionError("the client ladder must be skipped while walled")
    ))
    monkeypatch.setattr(YouTube, "_async_extract", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("yt-dlp must not run while walled")
    ))
    track = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh")

    info = asyncio.run(engine.stream_info(track))
    assert info.url == "https://cdn/copy.mp3"
    assert info.source == "jiosaavn"
    assert called == ["yt1"]
