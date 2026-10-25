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


def test_only_audio_less_sources_are_flagged_video():
    """A YouTube song has a video stream too — that must not make it video."""
    from vyron.core.search import YouTube

    song = YouTube._track_from_entry(
        None,
        {"id": "abcdefghijk", "title": "song", "vcodec": "avc1", "acodec": "mp4a"},
    )
    assert song is not None and song.is_video is False

    video_only = YouTube._track_from_entry(
        None,
        {"id": "abcdefghijk", "title": "silent clip", "vcodec": "avc1", "acodec": "none"},
    )
    assert video_only is not None and video_only.is_video is True

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

        def cached(self, track, *, video=False):
            return None

        async def audio(self, track, *, on_progress=None):
            self.tried.append("audio")
            raise RuntimeError("no audio stream")

        async def video(self, track, *, on_progress=None):
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
        def cached(self, track, *, video=False):
            return None

        async def audio(self, track, *, on_progress=None):
            raise RuntimeError("nope")

        async def video(self, track, *, on_progress=None):
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
        def cached(self, track, *, video=False):
            return None

        async def audio(self, track, *, on_progress=None):  # pragma: no cover - unused
            raise AssertionError("audio should be skipped")

        async def video(self, track, *, on_progress=None):
            return video_path

    _patch_runtime(monkeypatch, Downloader())
    client = _Client()
    track = Track(id="v3", title="clip", url="https://x/v.mp4")
    asyncio.run(play_module.deliver(client, -100, track, True))
    assert "video" in client.sent


def test_the_song_cover_is_handed_over_as_a_file_not_raw_bytes(monkeypatch, tmp_path):
    """`/song` lost the *whole* file when the cover had downloaded.

    The client's upload path accepts a path or a binary file object; raw
    ``bytes`` in `thumb` raise "Invalid file. Expected a file path as string or
    a binary (not text) file pointer" inside `send_audio`, which took the audio
    down with it. This pins the conversion at the call site.
    """
    audio_path = tmp_path / "song.mp3"
    audio_path.write_bytes(b"\x00" * 32)

    class Downloader:
        def cached(self, track, *, video=False):
            return None

        async def audio(self, track, *, on_progress=None):
            return audio_path

        async def video(self, track, *, on_progress=None):  # pragma: no cover
            raise AssertionError("the audio file was fine, video must not be tried")

    async def cover(url):
        return b"\xff\xd8\xff" + b"jpeg-bytes" * 4

    _patch_runtime(monkeypatch, Downloader())
    monkeypatch.setattr(play_module, "fetch_bytes", cover)
    client = _Client()
    track = Track(
        id="a9",
        title="s",
        url="https://x/s",
        thumbnail="https://i.ytimg.com/vi/a9/hqdefault.jpg",
    )

    asyncio.run(play_module.deliver(client, -100, track))

    assert "audio" in client.sent
    thumb = client.sent["audio"][2].get("thumb")
    assert thumb is not None and hasattr(thumb, "read"), "thumb must be a file pointer"
    assert getattr(thumb, "name", "").endswith(".jpg")
    assert thumb.read(2) == b"\xff\xd8"


def test_a_command_message_is_cleaned_up_in_groups_only():
    """Shizu's habit: the typed command does not stay above the answer."""
    from pyrogram.enums import ChatType

    calls: list[str] = []

    class Message:
        def __init__(self, chat_type):
            self.chat = SimpleNamespace(id=-100, type=chat_type)

        async def delete(self):
            calls.append("deleted")

    asyncio.run(play_module._tidy(None, Message(ChatType.SUPERGROUP)))
    assert calls == ["deleted"]

    asyncio.run(play_module._tidy(None, Message(ChatType.PRIVATE)))
    assert calls == ["deleted"], "a DM has no clutter to save"

    class NoRights(Message):
        async def delete(self):
            raise RuntimeError("not enough rights")

    asyncio.run(play_module._tidy(None, NoRights(ChatType.SUPERGROUP)))  # must not raise


def test_a_blocked_word_is_whole_words_only(monkeypatch):
    """`BLOCKED_WORDS` is an operator list, and "essex" is not "sex"."""
    from vyron import runtime as runtime_module

    monkeypatch.setattr(
        runtime_module.runtime,
        "settings",
        SimpleNamespace(blocked_word_list=("sex", "porn")),
        raising=False,
    )
    assert play_module._blocked("Sex on Fire") == "sex"
    assert play_module._blocked("essex live set") == ""
    assert play_module._blocked("pornography mix") == "", "only the exact word"
    assert play_module._blocked("let the world burn") == ""


def test_no_words_are_blocked_by_default():
    from vyron.config import settings

    assert "sex" not in settings.blocked_word_list


def test_the_working_card_makes_way_for_the_picture(monkeypatch):
    """One play, one message: the poster — not the poster plus a text twin."""
    from vyron import runtime as runtime_module

    state = SimpleNamespace(np_message_id=900)
    player = SimpleNamespace(queues=SimpleNamespace(get=lambda chat_id: state))
    monkeypatch.setattr(runtime_module.runtime, "player", player)

    deleted: list[tuple[int, int]] = []
    edits: list[str] = []

    class Client:
        async def delete_messages(self, chat_id, message_id):
            deleted.append((chat_id, message_id))
            return True

        async def send_message(self, **kwargs):  # pragma: no cover - not reached
            edits.append(kwargs.get("text", ""))
            return SimpleNamespace(id=1)

    asyncio.run(play_module._settle(Client(), -100, 55, "<b>started</b>"))
    assert deleted == [(-100, 55)]
    assert edits == []

    # No poster to hand over to: the card stays, with the answer written on it.
    state.np_message_id = None
    written: list[str] = []

    async def fake_edit(client, chat_id, message_id, markup, keyboard=None):
        written.append(markup)

    monkeypatch.setattr(play_module, "_edit", fake_edit)

    class EditOnly:
        pass

    asyncio.run(play_module._settle(EditOnly(), -100, 56, "<b>started</b>"))
    assert deleted == [(-100, 55)], "nothing to delete when there is no picture"
    assert written == ["<b>started</b>"]
