"""Playback after a YouTube wall: the right engine for the right track.

Two production failures are pinned here.

1. The downloader treated "YouTube is refusing this host" as "yt-dlp is
   useless" — so a SoundCloud substitute, which yt-dlp downloads perfectly,
   was skipped and the voice chat stayed silent.
2. A substitute's `url` for SoundCloud/Bandcamp is a *page*, not audio. Fetching
   it as bytes wrote HTML into a .mp3 and the stream failed later, on the
   listener's side, where it looks like the bot refusing to play.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from vyron.core.downloader import _is_youtube
from vyron.core.queue import Track


def _settings(tmp_path):
    from vyron.config import settings as real

    return dataclasses.replace(
        real,
        data_dir=tmp_path,
        downloads_dir=tmp_path / "downloads",
        max_download_mb=50,
        stream_fallback=False,
        play_from_disk=True,
    )


@pytest.fixture()
def downloader(tmp_path):
    from vyron.core.downloader import Downloader

    instance = Downloader(_settings(tmp_path))
    instance.settings.ensure_dirs()
    return instance


def test_the_wall_test_knows_which_tracks_are_youtube():
    assert _is_youtube(Track(id="dQw4w9WgXcQ", title="x")) is True
    assert _is_youtube(Track(id="abc", title="x", source="ytmusic")) is True
    assert _is_youtube(Track(id="1800914883", title="x", source="soundcloud")) is False
    assert _is_youtube(Track(id="jx-9Yg", title="x", source="jiosaavn")) is False
    assert _is_youtube(Track(id="abc", title="x", source="audius")) is False


def test_a_soundcloud_track_is_downloaded_even_when_youtube_is_walled(downloader, monkeypatch, tmp_path):
    """The wall is about YouTube, not about yt-dlp."""
    called: list[str] = []

    def fake_ytdlp(track, *, video, on_progress=None, dest=None):
        called.append(track.id)
        target = dest or downloader.audio_path(track)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3" + b"0" * 64)
        return target

    monkeypatch.setattr(downloader, "_youtube_walled", lambda: True)
    monkeypatch.setattr(downloader, "_download_ytdlp", fake_ytdlp)

    track = Track(id="1800914883", title="Let the world burn", source="soundcloud",
                  url="https://soundcloud.com/x/let-the-world-burn")

    path = asyncio.run(downloader.fetch(track))

    assert called == ["1800914883"]
    assert path.exists()


def test_a_youtube_track_still_skips_the_ladder_when_walled(downloader, monkeypatch):
    from vyron.core.downloader import DownloadError

    monkeypatch.setattr(downloader, "_youtube_walled", lambda: True)
    monkeypatch.setattr(
        downloader, "_download_ytdlp", lambda *a, **k: pytest.fail("yt-dlp should not run")
    )
    async def no_mirror(*args, **kwargs):
        raise DownloadError("no mirror had a downloadable URL")

    monkeypatch.setattr(downloader, "_download_direct", no_mirror)

    async def no_substitute(*args, **kwargs):
        return None

    monkeypatch.setattr("vyron.core.alternate.find", no_substitute)

    track = Track(id="dQw4w9WgXcQ", title="Song", source="youtube")
    with pytest.raises(DownloadError):
        asyncio.run(downloader.fetch(track))


def test_a_page_url_substitute_is_extracted_not_fetched(downloader, monkeypatch):
    """SoundCloud gives a page. Writing it to .mp3 is how playback died."""
    from vyron.core import alternate
    from vyron.core.downloader import DownloadError

    def boom(*args, **kwargs):
        raise DownloadError("yt-dlp gave up")

    monkeypatch.setattr(downloader, "_youtube_walled", lambda: False)
    monkeypatch.setattr(downloader, "_download_ytdlp", boom)
    monkeypatch.setattr(downloader, "_download_direct", boom)
    monkeypatch.setattr(
        downloader, "_download_stream", lambda *a, **k: pytest.fail("a page is not audio")
    )

    found = Track(id="1800914883", title="Let the world burn", source="soundcloud",
                  url="https://soundcloud.com/x/let-the-world-burn")

    async def substitute(*args, **kwargs):
        return found

    seen: list[str] = []

    def fake_ytdlp(track, *, video, on_progress=None):
        seen.append(f"{track.source}:{track.id}")
        target = downloader.audio_path(track)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3" + b"0" * 64)
        return target

    monkeypatch.setattr(alternate, "find", substitute)
    # The original is refused; the substitute is extracted with yt-dlp.
    def first_then_ok(track, *, video, on_progress=None):
        if track.source == "youtube":
            raise DownloadError("original refused")
        return fake_ytdlp(track, video=video, on_progress=on_progress)

    monkeypatch.setattr(downloader, "_download_ytdlp", first_then_ok)

    track = Track(id="dQw4w9WgXcQ", title="Let the world burn", source="youtube")
    path = asyncio.run(downloader.fetch(track))

    assert seen == ["soundcloud:1800914883"]
    assert path.exists()


def test_a_direct_catalogue_substitute_is_streamed_not_extracted(downloader, monkeypatch):
    """JioSaavn/Audius hand out the audio file itself: no extraction step."""
    from vyron.core import alternate
    from vyron.core.downloader import DownloadError

    monkeypatch.setattr(downloader, "_youtube_walled", lambda: True)
    monkeypatch.setattr(
        downloader, "_download_direct", lambda *a, **k: (_ for _ in ()).throw(DownloadError("no mirror"))
    )

    found = Track(id="jx9Yg", title="Kesariya", source="jiosaavn", url="https://cdn.example/k.m4a")

    async def substitute(*args, **kwargs):
        return found

    streamed: list[str] = []

    async def fake_stream(track, *, on_progress=None):
        streamed.append(track.id)
        target = downloader.audio_path(track)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3" + b"0" * 64)
        return target

    monkeypatch.setattr(alternate, "find", substitute)
    monkeypatch.setattr(downloader, "_download_stream", fake_stream)

    track = Track(id="dQw4w9WgXcQ", title="Kesariya", source="youtube")
    path = asyncio.run(downloader.fetch(track))

    assert streamed == ["jx9Yg"]
    assert path.exists()


# ── what the chat is told when it fails ────────────────────────────────────
def test_a_standby_failure_explains_itself_and_promises_a_takeover():
    from vyron.modules.play import _stream_failure_text

    text = _stream_failure_text(
        RuntimeError("This instance is a standby — another copy of the bot owns the voice chat.")
    )
    assert "Another copy has the voice chat" in text
    assert "takes playback over" in text
    assert "standby" not in text.split("<blockquote>")[1], "raw engine text in the chat"


def test_an_engine_chain_is_not_pasted_into_the_chat():
    from vyron.modules.play import _stream_failure_text

    text = _stream_failure_text(RuntimeError("yt-dlp: refused · mirror: refused · substitute: none"))
    assert "Could not reach the audio" in text
    assert "/sources" in text          # where the owner looks
    assert "/song" in text             # what the listener can do instead


# ── the two audio engines run at once ──────────────────────────────────────
def test_a_slow_mirror_does_not_hold_up_a_catalogue_copy(downloader, monkeypatch):
    """Mirror *and* catalogue copy, in parallel — never one after the other.

    A dead Invidious instance used to add its whole timeout to a download that
    JioSaavn could have answered immediately.
    """
    import time as _time

    from vyron.core import alternate
    from vyron.core.downloader import DownloadError

    monkeypatch.setattr(downloader, "_youtube_walled", lambda: True)
    stopped: list[str] = []

    async def slow_mirror(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            stopped.append("mirror")
            raise
        raise DownloadError("the mirror never answered")

    found = Track(id="jx9Yg", title="Kesariya", source="jiosaavn", url="https://cdn/k.m4a")

    async def substitute(*args, **kwargs):
        return found

    async def fake_stream(track, *, on_progress=None):
        target = downloader.audio_path(track)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"ID3" + b"0" * 64)
        return target

    monkeypatch.setattr(downloader, "_download_direct", slow_mirror)
    monkeypatch.setattr(alternate, "find", substitute)
    monkeypatch.setattr(downloader, "_download_stream", fake_stream)

    track = Track(id="dQw4w9WgXcQ", title="Kesariya", source="youtube")
    started = _time.monotonic()
    path = asyncio.run(downloader.fetch(track))
    elapsed = _time.monotonic() - started

    assert path.exists()
    assert elapsed < 5, f"the catalogue copy waited for the mirror ({elapsed:.1f}s)"
    assert stopped == ["mirror"], "the losing engine must be cancelled"


def test_both_engines_failing_reports_both_reasons(downloader, monkeypatch):
    from vyron.core.downloader import DownloadError

    monkeypatch.setattr(downloader, "_youtube_walled", lambda: True)

    async def no_mirror(*args, **kwargs):
        raise DownloadError("no mirror had a downloadable URL")

    monkeypatch.setattr(downloader, "_download_direct", no_mirror)

    async def no_copy(*args, **kwargs):
        raise DownloadError("the catalogues had no copy")

    monkeypatch.setattr(downloader, "_catalogue_copy", no_copy)

    track = Track(id="dQw4w9WgXcQ", title="Song", source="youtube")
    with pytest.raises(DownloadError) as caught:
        asyncio.run(downloader.fetch(track))
    message = str(caught.value)
    assert "mirror" in message and "substitute" in message


# ── a file on disk beats a URL that can expire ────────────────────────────
def test_a_cached_file_is_played_instead_of_a_stream_url(tmp_path):
    """The reliability model of every bot that "just works": a local file.

    A signed URL can 403 halfway through a song; a file cannot. What made this
    worth changing is that the file is already there — either cached from an
    earlier play or fetched by the prefetch — so it is also the *faster* lane.
    """
    from vyron.core import player as player_module

    cached = tmp_path / "youtube-abc.mp3"
    cached.write_bytes(b"ID3" + b"0" * 64)

    class Downloader:
        def cached(self, track, *, video=False):
            return cached

        async def fetch(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("a cached file must not be downloaded again")

    class Youtube:
        async def stream_info(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("a cached file must not be resolved again")

    class Calls:
        def __init__(self):
            self.played = []

        async def play(self, chat_id, stream, **kwargs):
            self.played.append(stream)

    instance = player_module.Player.__new__(player_module.Player)
    instance.tracks_played = 0
    instance._recovered_at = {}
    instance.storage = None
    instance.schedule_save = lambda *args, **kwargs: None
    instance._schedule_prefetch = lambda *args, **kwargs: None
    instance.settings = type(
        "S",
        (),
        {
            "play_from_disk": False,
            "preheat_depth": 0,
            "preheat_seconds": 0,
            "audio_quality": "high",
            "video_quality": "720p",
        },
    )()
    instance.downloader = Downloader()
    instance.youtube = Youtube()
    instance.calls = Calls()
    instance._in_call = set()
    class _State:
        effects = None
        is_video = False
        offset = 0.0

        def __getattr__(self, name):  # touch(), reset_stream(), … are no-ops here
            return lambda *args, **kwargs: None

    instance.queues = type("Q", (), {"get": staticmethod(lambda chat: _State())})()

    track = Track(id="abc", title="Wrong", source="youtube", duration=187)
    asyncio.run(instance._start_stream(-100, track, video=False))

    played = instance.calls.played
    assert played and isinstance(played[0], player_module.MediaStream)
    assert str(cached) in repr(played[0].__dict__), "it must hand ntgcalls the file"
