"""Secrets never reach a group, and search results behave like results.

These are behavioural tests on the real handlers: a signed owner token is a
credential, so `/start` and `/app` must only ever embed one in a DM.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest
from pyrogram.enums import ChatType

from vyron.config import settings
from vyron.core.queue import Track
from vyron.core.search import YouTube
from vyron.utils.helpers import is_private_chat


# ── fakes ───────────────────────────────────────────────────────────────────
class FakeChat:
    def __init__(self, kind: ChatType, chat_id: int, title: str = "") -> None:
        self.type = kind
        self.id = chat_id
        self.title = title


class FakeUser:
    def __init__(self, user_id: int, first_name: str = "Owner") -> None:
        self.id = user_id
        self.first_name = first_name
        self.username = "owner"


class FakeMessage:
    def __init__(self, chat: FakeChat, user: FakeUser | None = None, message_id: int = 1) -> None:
        self.chat = chat
        self.from_user = user
        self.id = message_id
        self.text = ""
        self.command: list[str] = []
        self._client = None
        self.reply_to_message = None


class FakeClient:
    """Collects the handlers a module registers so tests can call them."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on_message(self, *_args, **_kwargs):
        def decorator(fn):
            self.handlers[fn.__name__] = fn
            return fn

        return decorator


@pytest.fixture()
def webapp_configured(monkeypatch):
    """Both the module and the card layer read the settings singleton."""
    from vyron.modules import start
    from vyron.ui import cards

    patched = dataclasses.replace(settings, webapp_url="https://vyron.test", webapp=True)
    assert patched.webapp_ready
    monkeypatch.setattr(start, "settings", patched)
    monkeypatch.setattr(cards, "settings", patched)
    return patched


@pytest.fixture()
def sent(monkeypatch):
    """Capture cards instead of talking to Telegram."""
    from vyron.modules import start

    captured: list[str] = []

    async def fake_send(_client, _chat_id, markup, **_kwargs):
        captured.append(markup)
        return None

    monkeypatch.setattr(start.rich, "send", fake_send)
    return captured


def _run(handler, message):
    asyncio.run(handler(FakeClient(), message))


# ── private-chat detection ──────────────────────────────────────────────────
def test_is_private_chat_understands_enums_and_stub_chats():
    assert is_private_chat(FakeChat(ChatType.PRIVATE, 42))
    assert not is_private_chat(FakeChat(ChatType.SUPERGROUP, -1001))
    assert not is_private_chat(FakeChat(ChatType.GROUP, -55))
    # a bare object with only an id still works (positive id == DM)
    assert is_private_chat(type("Stub", (), {"id": 7})())
    assert not is_private_chat(type("Stub", (), {"id": -7})())
    assert not is_private_chat(None)


# ── /start ──────────────────────────────────────────────────────────────────
def test_start_in_a_group_never_carries_an_owner_token(webapp_configured, sent):
    from vyron.modules import start

    client = FakeClient()
    start.register(client)
    message = FakeMessage(FakeChat(ChatType.SUPERGROUP, -1001234, "Listening Room"), FakeUser(424242))
    _run(client.handlers["_start"], message)

    assert sent, "the card should still be sent"
    card = sent[-1]
    assert "vown_" not in card
    assert "Owner" not in card or "owner console" not in card.lower()


def test_start_in_a_dm_does_carry_the_owner_console(webapp_configured, sent):
    from vyron.modules import start

    client = FakeClient()
    start.register(client)
    message = FakeMessage(FakeChat(ChatType.PRIVATE, 424242), FakeUser(424242))
    _run(client.handlers["_start"], message)

    card = sent[-1]
    assert "vown_" in card
    assert "Owner" in card


# ── /app ────────────────────────────────────────────────────────────────────
def test_app_command_hides_the_token_in_groups(webapp_configured, sent):
    from vyron.modules import start

    client = FakeClient()
    start.register(client)
    message = FakeMessage(FakeChat(ChatType.GROUP, -4242), FakeUser(424242))
    _run(client.handlers["_webapp"], message)

    assert sent and "vown_" not in sent[-1]


def test_app_command_hands_the_owner_a_token_in_a_dm(webapp_configured, sent):
    from vyron.modules import start

    client = FakeClient()
    start.register(client)
    message = FakeMessage(FakeChat(ChatType.PRIVATE, 424242), FakeUser(424242))
    _run(client.handlers["_webapp"], message)

    assert "vown_" in sent[-1]


# ── ordinary users never get one ─────────────────────────────────────────────
def test_a_stranger_gets_no_token_even_in_a_dm(webapp_configured, sent):
    from vyron.modules import start

    client = FakeClient()
    start.register(client)
    message = FakeMessage(FakeChat(ChatType.PRIVATE, 999), FakeUser(999, "Stranger"))
    _run(client.handlers["_start"], message)

    assert "vown_" not in sent[-1]


# ── ranking ─────────────────────────────────────────────────────────────────
def _track(vid: str, title: str, *, duration: int = 210, uploader: str = "", views: int = 0) -> Track:
    return Track(id=vid, title=title, duration=duration, uploader=uploader, views=views)


def test_ranking_pushes_shorts_and_loops_down():
    yt = YouTube(dataclasses.replace(settings, data_dir="/tmp"))
    tracks = [
        _track("aaaaaaaaaaa", "Believer - Imagine Dragons (1 hour loop)", duration=3600),
        _track("bbbbbbbbbbb", "Believer #shorts", duration=22),
        _track("ccccccccccc", "Believer", uploader="Imagine Dragons", views=2_000_000),
        _track("ddddddddddd", "Someone Else", duration=200),
    ]
    ranked = yt.rank("believer", tracks)
    assert ranked[0].id == "ccccccccccc"
    assert ranked[-1].id in {"bbbbbbbbbbb", "ddddddddddd"}


def test_ranking_drops_duplicate_titles_and_ids():
    yt = YouTube(dataclasses.replace(settings, data_dir="/tmp"))
    tracks = [
        _track("dupdupdupd1", "Same Song", duration=200),
        _track("dupdupdupd2", "Same Song", duration=201),
        _track("dupdupdupd1", "Same Song", duration=200),
    ]
    ranked = yt.rank("same song", tracks)
    assert len(ranked) == 1


def test_ranking_keeps_platform_order_on_a_tie():
    yt = YouTube(dataclasses.replace(settings, data_dir="/tmp"))
    tracks = [
        _track(f"tie{index:08d}", f"Song {word}", duration=180)
        for index, word in enumerate(("one", "two", "three", "four"))
    ]
    ranked = yt.rank("song", tracks)
    assert [track.id for track in ranked] == [track.id for track in tracks]
