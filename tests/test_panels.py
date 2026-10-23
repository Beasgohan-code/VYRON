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
