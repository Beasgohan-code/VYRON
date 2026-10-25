"""`/vplay` and `/vsong` — the two commands auto-detection cannot replace.

A music video has an audio stream too, so "does this have sound?" can never
answer "stream the picture". Before these commands existed there was no way to
ask for video at all: `/play <youtube link>` always played the audio, and the
`video` flag only ever became true for a source with no audio whatsoever.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pyrogram.enums import ChatType

from vyron.core.queue import Track
from vyron.modules import play as play_module

CHAT = -100555


class FakeClient:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on_message(self, *_args, **_kwargs):
        def decorator(fn):
            self.handlers[fn.__name__] = fn
            return fn

        return decorator


def message(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        command=text.split()[0].lstrip("/").split("@")[:1],
        chat=SimpleNamespace(id=CHAT, type=ChatType.SUPERGROUP),
        from_user=SimpleNamespace(id=11, first_name="Asha", last_name=None, username="asha"),
        id=21,
        reply_to_message=None,
        _client=None,
    )


def _wire(monkeypatch, *, tracks, played):
    """A player + a search that record the video flag they were given."""

    class FakePlayer:
        queues: dict = {}

        async def enqueue(self, chat_id, track, *, video=False, play_now=False):
            played.append((track.id, video, play_now))
            return 1

        async def ensure_assistant(self, chat_id):   # prejoin
            return True

        async def play_track(self, chat_id, track, *, video=False, seek=0):
            played.append((track.id, video, True))

    class FakeYouTube:
        async def search(self, query, limit=None, requester=None):
            return list(tracks)

        async def resolve(self, query, requester=None):
            return tracks[0]

    sent: list[str] = []

    async def fake_send(_client, _chat_id, markup, **_kwargs):
        sent.append(markup)
        return SimpleNamespace(id=50)

    async def fake_edit(*_args, **_kwargs):
        return None

    def fake_args(msg):
        parts = (msg.text or "").split(maxsplit=1)
        return parts[1].strip() if len(parts) > 1 else ""

    monkeypatch.setattr(play_module.runtime, "player", FakePlayer(), raising=False)
    monkeypatch.setattr(play_module.runtime, "youtube", FakeYouTube(), raising=False)
    monkeypatch.setattr(play_module.runtime, "calls", SimpleNamespace(), raising=False)
    monkeypatch.setattr(play_module, "command_args", fake_args)
    monkeypatch.setattr(play_module, "_thinking", _noop_thinking)
    monkeypatch.setattr(play_module, "_edit", fake_edit)
    monkeypatch.setattr(play_module, "_tidy", lambda *a, **k: asyncio.sleep(0))
    monkeypatch.setattr(play_module.rich, "send", fake_send)
    monkeypatch.setattr(play_module, "may_request", lambda *a, **k: _yes())
    return sent


async def _yes():
    return True


async def _noop_thinking(*_args, **_kwargs):
    return SimpleNamespace(id=50)


def _run(client, text, handler="_play_cmd"):
    asyncio.run(client.handlers[handler](None, message(text)))


@pytest.fixture()
def song():
    # a normal YouTube song: it *has* a video stream, but is_video is False
    return Track(id="song1", title="Past Lives", url="https://youtu.be/song1")


def test_vplay_streams_the_video(monkeypatch, song):
    played: list[tuple] = []
    _wire(monkeypatch, tracks=[song], played=played)
    client = FakeClient()
    play_module.register(client)

    _run(client, "/vplay past lives")

    assert played == [("song1", True, True)], played


def test_play_still_streams_the_same_song_as_audio(monkeypatch, song):
    played: list[tuple] = []
    _wire(monkeypatch, tracks=[song], played=played)
    client = FakeClient()
    play_module.register(client)

    _run(client, "/play past lives")

    assert played == [("song1", False, True)], played


def test_a_video_link_streams_as_video_under_vplay(monkeypatch, song):
    played: list[tuple] = []

    class FakeYouTube:
        async def search(self, query, limit=None, requester=None):
            return [song]

        async def resolve(self, query, requester=None):
            return song

    _wire(monkeypatch, tracks=[song], played=played)
    monkeypatch.setattr(play_module.runtime, "youtube", FakeYouTube(), raising=False)
    client = FakeClient()
    play_module.register(client)

    _run(client, "/vplay https://youtu.be/song1")

    assert played == [("song1", True, True)], played


def test_vplay_search_remembers_the_kind_for_the_picker(monkeypatch):
    """Without this, tapping a result in the picker streams audio again."""
    from vyron.core import pending

    played: list[tuple] = []
    pending._CACHE.clear()
    tracks = [
        Track(id=f"t{i}", title=f"Past Lives {i}", url=f"https://youtu.be/t{i}")
        for i in range(4)
    ]
    _wire(monkeypatch, tracks=tracks, played=played)
    # a query that is *not* a confident match → the picker, not autoplay
    monkeypatch.setattr(play_module, "_should_autoplay", lambda *a, **k: False)
    client = FakeClient()
    play_module.register(client)

    _run(client, "/vplay past lives")

    entry = pending._CACHE.get((CHAT, 50))
    assert entry is not None, "no picker state was remembered"
    assert entry.video is True
    pending._CACHE.clear()


def _command_table() -> dict[str, list[str]]:
    """`test_commands._commands()`, loaded from its file rather than imported.

    `from tests.test_commands import …` depends on the repository winning the
    name `tests` against any installed package that ships one — on CI's Python
    3.11 job it did not, and the job failed on an *import*, not an assertion.
    A test that can only run in one module layout is a test that lies.
    """
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).with_name("test_commands.py")
    spec = importlib.util.spec_from_file_location("_vyron_command_table", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._commands()


def test_vplay_is_registered_on_the_play_handler(monkeypatch):
    """One implementation: `/vplay` must not be a second `/play` that drifts."""
    from vyron.modules import play as module

    source = module.__file__
    assert source
    client = FakeClient()
    module.register(client)
    # the same handler answers both names, which is what the command table says
    found = _command_table()
    assert set(found["vplay"]) & set(found["play"])


def test_vsong_sends_the_video_file(monkeypatch, song):
    sent: list[tuple] = []

    async def fake_deliver(client, chat_id, track, want_video=None, **kwargs):
        sent.append((track.id, want_video))

    _wire(monkeypatch, tracks=[song], played=[])
    monkeypatch.setattr(play_module, "deliver", fake_deliver)
    client = FakeClient()
    play_module.register(client)

    _run(client, "/vsong past lives", "_download_cmd")

    assert sent == [("song1", True)], sent


def test_song_still_sends_audio(monkeypatch, song):
    sent: list[tuple] = []

    async def fake_deliver(client, chat_id, track, want_video=None, **kwargs):
        sent.append((track.id, want_video))

    _wire(monkeypatch, tracks=[song], played=[])
    monkeypatch.setattr(play_module, "deliver", fake_deliver)
    client = FakeClient()
    play_module.register(client)

    _run(client, "/song past lives", "_download_cmd")

    assert sent == [("song1", False)], sent
