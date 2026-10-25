"""Saved playlists, and the one thing only a channel needs.

`/pplay` queues a playlist where the person is. `/cpplay` is the same list
played into the *linked channel's* voice chat — the channel counterpart that
Shizu calls `/cpplay`. The queue must land on the channel, not on the group,
or the music plays to the wrong room.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pyrogram.enums import ChatType

from vyron.core.queue import Track
from vyron.modules import savedplaylists

GROUP = -1001234
CHANNEL = -1009999888877


class FakeMessage:
    def __init__(self, text: str, chat_id: int = GROUP) -> None:
        self.text = text
        self.command = text.split()[0].lstrip("/").split("@")[:1]
        self.chat = SimpleNamespace(id=chat_id, type=ChatType.SUPERGROUP)
        self.from_user = SimpleNamespace(id=42, first_name="Asha")
        self.id = 7
        self.reply_to_message = None

    async def delete(self) -> None:
        return None


class FakeClient:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on_message(self, *_args, **_kwargs):
        def decorator(fn):
            self.handlers[fn.__name__] = fn
            return fn

        return decorator


def _wire(monkeypatch, target):
    played: list[tuple[int, str]] = []
    queued: list[tuple[int, str]] = []

    class FakePlayer:
        async def play_track(self, chat_id, track, video=False):
            played.append((chat_id, track.id))

        async def enqueue(self, chat_id, track):
            queued.append((chat_id, track.id))
            return 1

    async def tracks(_uid, _name):
        return ("chill", [Track(id="a", title="A"), Track(id="b", title="B")])

    async def resolve(_client, _message):
        return target

    sent: list[str] = []

    async def send(_client, _chat_id, markup, **_kwargs):
        sent.append(markup)
        return SimpleNamespace(id=1)

    import vyron.modules.channel as channel

    monkeypatch.setattr(savedplaylists.runtime, "player", FakePlayer(), raising=False)
    monkeypatch.setattr(savedplaylists.store, "as_tracks", tracks)
    monkeypatch.setattr(channel, "resolve_target", resolve)
    monkeypatch.setattr(savedplaylists.rich, "send", send)
    return played, queued, sent


def test_cpplay_plays_in_the_linked_channel(monkeypatch):
    played, queued, sent = _wire(monkeypatch, CHANNEL)
    client = FakeClient()
    savedplaylists.register(client)

    asyncio.run(client.handlers["_play_saved"](client, FakeMessage("/cpplay chill")))

    assert played == [(CHANNEL, "a")], "the first track must start the channel stream"
    assert queued == [(CHANNEL, "b")], "the rest must queue on the channel"
    assert sent and "linked channel" in sent[-1]


def test_pplay_still_plays_where_the_command_was_typed(monkeypatch):
    played, queued, _sent = _wire(monkeypatch, None)
    client = FakeClient()
    savedplaylists.register(client)

    asyncio.run(client.handlers["_play_saved"](client, FakeMessage("/pplay chill")))

    assert played == []
    assert queued == [(GROUP, "a"), (GROUP, "b")]


def test_cpplay_without_a_channel_explains_instead_of_playing(monkeypatch):
    played, queued, sent = _wire(monkeypatch, None)
    client = FakeClient()
    savedplaylists.register(client)

    asyncio.run(client.handlers["_play_saved"](client, FakeMessage("/cpplay chill")))

    assert played == [] and queued == []
    assert sent and "No linked channel" in sent[-1]
