# ---------------------------------------------------------------------------
#  One /play, one /cplay, one /song — the media kind is detected, not asked.
#
#  These pin the three decisions that used to be separate commands:
#    * a replied video streams as video, a voice note / audio file as audio;
#    * a link that only exists as video is streamed as video;
#    * /song sends audio, and falls back to the video file when the source
#      has no audio-only stream at all.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
from types import SimpleNamespace


from vyron.core.queue import Track
from vyron.modules import play as play_module
from vyron.utils.helpers import media_suffix, track_from_message


def _reply(**media):
    """A fake replied-to message carrying exactly one media attribute."""
    message = SimpleNamespace(**{name: None for name in ("audio", "voice", "video", "document")})
    for name, value in media.items():
        setattr(message, name, value)
    message.from_user = SimpleNamespace(id=7, first_name="Ann", last_name=None, username="ann")
    return SimpleNamespace(reply_to_message=message)


def test_a_replied_video_is_detected_as_video():
    track = track_from_message(_reply(video=SimpleNamespace(duration=30, file_id="vid1")))
    assert track is not None and track.is_video is True


def test_a_replied_document_with_a_video_mime_is_detected_as_video():
    doc = SimpleNamespace(file_name="clip.mp4", mime_type="video/mp4", file_id="doc1")
    track = track_from_message(_reply(document=doc))
    assert track is not None and track.is_video is True


def test_a_replied_audio_or_voice_note_is_audio():
    for media in (
        SimpleNamespace(file_id="a1", duration=200),
        SimpleNamespace(file_id="a2", mime_type="audio/ogg"),
    ):
        key = "audio" if hasattr(media, "duration") else "voice"
        track = track_from_message(_reply(**{key: media}))
        assert track is not None and track.is_video is False


def test_media_suffix_prefers_the_file_name():
    assert media_suffix(SimpleNamespace(file_name="song.flac", mime_type="audio/mpeg")) == ".flac"
    assert media_suffix(SimpleNamespace(file_name=None, mime_type="audio/mpeg")) == ".mpeg"


def test_full_extracts_flag_a_video_track():
    from vyron.core.search import YouTube

    resolved = YouTube._track_from_entry(
        None,
        {"id": "abcdefghijk", "title": "clip", "vcodec": "avc1", "width": 1280},
    )
    assert resolved is not None and resolved.is_video is True

    flat = YouTube._track_from_entry(None, {"id": "abcdefghijk", "title": "song"})
    assert flat is not None and flat.is_video is False


class _Client:
    def __init__(self):
        self.sent = {}

    async def send_audio(self, chat_id, path, **kwargs):
        self.sent["audio"] = (chat_id, path, kwargs)
        return SimpleNamespace(id=1)

    async def send_video(self, chat_id, path, **kwargs):
        self.sent["video"] = (chat_id, path, kwargs)
        return SimpleNamespace(id=2)

    async def delete_messages(self, *args, **kwargs):
        return True


def _patch_runtime(monkeypatch, downloader):
    from vyron import runtime as runtime_module

    monkeypatch.setattr(runtime_module.runtime, "downloader", downloader)
    monkeypatch.setattr(runtime_module.runtime, "storage", None)
    monkeypatch.setattr(runtime_module.runtime, "settings", runtime_module.runtime.settings)


def test_begin_uses_the_detected_kind_when_no_video_flag_is_given(monkeypatch):
    from vyron import runtime as runtime_module

    class FakePlayer:
        def __init__(self):
            self.calls = []

        async def enqueue(self, chat_id, track, *, video=False, play_now=False):
            self.calls.append((chat_id, track.id, video, play_now))
            return 1

    player = FakePlayer()
    monkeypatch.setattr(runtime_module.runtime, "calls", SimpleNamespace())
    monkeypatch.setattr(runtime_module.runtime, "player", player)

    video_track = Track(id="v1", title="clip", url="https://x/v.mp4", is_video=True)
    audio_track = Track(id="a1", title="song", url="https://x/a.m4a")
    assert asyncio.run(play_module.begin(_Client(), -100, video_track)) == "streamed"
    assert asyncio.run(play_module.begin(_Client(), -100, audio_track)) == "streamed"
    assert [call[2] for call in player.calls] == [True, False]


def test_song_falls_back_to_the_video_file_when_audio_is_impossible(monkeypatch, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"\x00" * 32)

    class Downloader:
        def __init__(self):
            self.tried = []

        async def audio(self, track):
            self.tried.append("audio")
            raise RuntimeError("no audio stream")

        async def video(self, track):
            self.tried.append("video")
            return video_path

    downloader = Downloader()
    _patch_runtime(monkeypatch, downloader)
    client = _Client()
    track = Track(id="v2", title="clip", url="https://x/v.mp4", is_video=True)

    asyncio.run(play_module.deliver(client, -100, track))
    assert downloader.tried == ["audio", "video"]
    assert "video" in client.sent and "audio" not in client.sent


def test_song_reports_an_error_when_neither_format_works(monkeypatch):
    class Downloader:
        async def audio(self, track):
            raise RuntimeError("nope")

        async def video(self, track):
            raise RuntimeError("nope either")

    _patch_runtime(monkeypatch, Downloader())
    client = _Client()
    track = Track(id="x", title="t", url="https://x/t")

    asyncio.run(play_module.deliver(client, -100, track))
    assert client.sent == {}


def test_deliver_accepts_an_explicit_video_choice(monkeypatch, tmp_path):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"\x00" * 32)

    class Downloader:
        async def audio(self, track):  # pragma: no cover - must not be used
            raise AssertionError("audio should be skipped")

        async def video(self, track):
            return video_path

    _patch_runtime(monkeypatch, Downloader())
    client = _Client()
    track = Track(id="v3", title="clip", url="https://x/v.mp4")
    asyncio.run(play_module.deliver(client, -100, track, True))
    assert "video" in client.sent
