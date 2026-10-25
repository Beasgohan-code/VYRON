"""Live-card edits must survive deleted or uneditable messages."""
from __future__ import annotations

import asyncio

import pytest
from pyrogram.errors import ChatWriteForbidden, MessageIdInvalid, MessageNotModified

from vyron.ui import rich


@pytest.fixture(autouse=True)
def _clean():
    rich._DEAD.clear()
    rich._PHOTO_SENT.clear()
    rich._RICH_SENT.clear()
    yield
    rich._DEAD.clear()


class Client:
    def __init__(self, exc=None):
        self.exc = exc
        self.calls: list[dict] = []

    async def edit_message_text(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return type("Msg", (), {"id": kwargs.get("message_id")})()

    async def edit_message_caption(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return type("Msg", (), {"id": kwargs.get("message_id")})()


def test_a_deleted_card_is_only_attempted_once():
    client = Client(MessageIdInvalid())
    for _ in range(4):
        asyncio.run(rich.edit(client, -100, 7, "<b>progress</b>"))
    assert len(client.calls) == 1
    assert rich._dead(-100, 7) is True


def test_a_new_card_in_the_same_chat_still_edits():
    dead = Client(MessageIdInvalid())
    asyncio.run(rich.edit(dead, -100, 7, "<b>x</b>"))

    fresh = Client()
    asyncio.run(rich.edit(fresh, -100, 8, "<b>x</b>"))
    assert len(fresh.calls) == 1


def test_not_modified_never_buries_a_card():
    client = Client(MessageNotModified())
    asyncio.run(rich.edit(client, -100, 9, "<b>x</b>"))
    assert rich._dead(-100, 9) is False
    asyncio.run(rich.edit(client, -100, 9, "<b>x</b>"))
    assert len(client.calls) == 2


def test_losing_write_permission_buries_the_card():
    client = Client(ChatWriteForbidden())
    asyncio.run(rich.edit(client, -100, 10, "<b>x</b>"))
    assert rich._dead(-100, 10) is True


def test_caption_edits_are_guarded_too():
    rich._remember_photo(-100, 11)
    client = Client(MessageIdInvalid())
    asyncio.run(rich.edit(client, -100, 11, "<b>x</b>"))
    asyncio.run(rich.edit(client, -100, 11, "<b>x</b>"))
    assert len(client.calls) == 1


class _Recording:
    """A client that records every send — and would raise like Telegram does."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def send_rich_message(self, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("rich", kwargs))
        raise AssertionError("a card addressed to peer 0 must not be sent")

    async def send_message(self, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("html", kwargs))
        raise AssertionError("a card addressed to peer 0 must not be sent")

    async def send_photo(self, **kwargs):  # pragma: no cover - must not run
        self.calls.append(("photo", kwargs))
        raise AssertionError("a picture addressed to peer 0 must not be sent")


def test_a_card_addressed_to_nobody_is_not_sent_at_all():
    """"Peer id invalid: 0" was a card sent to chat 0.

    An owner token, or a queue restored without its chat, resolves to chat 0 —
    and the client answers that with an error on the log line, after the
    bitmap/poster was already built. Nothing can arrive at peer 0, so nothing
    is attempted, and the caller keeps its normal `None`.
    """
    card = "<b>Hello</b>"
    client = _Recording()
    assert asyncio.run(rich.send(client, 0, card)) is None
    assert asyncio.run(rich.send(client, None, card)) is None
    assert asyncio.run(rich.send_photo(client, 0, b"jpg-bytes", card)) is None
    assert client.calls == []
