"""Moderation commands talk to Telegram with the *right* permission types.

Kurigram splits the old ``ChatPrivileges`` alias: restricting a member wants
``ChatPermissions`` (datetime ``until_date``), promoting wants
``ChatAdministratorRights``. Passing the wrong one raises ``TypeError`` at
runtime, so these fakes validate the call shape exactly like pyrogram does.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import ChatAdministratorRights, ChatPermissions

pytest.importorskip("pyrogram")

from vyron.modules import moderation

ADMIN_ID = 777001
MEMBER_ID = 999111
CHAT_ID = -1009876543210


class FakeChat:
    def __init__(self) -> None:
        self.id = CHAT_ID
        self.title = "Room"
        self.type = ChatType.SUPERGROUP


class FakeUser:
    def __init__(self, user_id: int, name: str = "User") -> None:
        self.id = user_id
        self.first_name = name
        self.last_name = None
        self.username = None
        self.is_bot = False
        self.mention = f'<a href="tg://user?id={user_id}">{name}</a>'


class FakeMessage:
    def __init__(self, text: str, *, user: FakeUser, reply: "FakeMessage | None" = None) -> None:
        self.text = text
        self.chat = FakeChat()
        self.from_user = user
        self.id = 5
        self.command = text.split()[0].lstrip("/").split("@")[0:1]
        self.caption = None
        self.reply_to_message = reply


class FakeMember:
    def __init__(self, admin: bool) -> None:
        self.status = ChatMemberStatus.ADMINISTRATOR if admin else ChatMemberStatus.MEMBER


class FakeClient:
    def __init__(self, *, admin: bool = True) -> None:
        self.admin = admin
        self.handlers: dict[str, object] = {}
        self.restrictions: list[tuple[int, object, object]] = []
        self.promotions: list[tuple[int, object]] = []
        self.bans: list[int] = []

    def on_message(self, *_args, **_kwargs):
        def decorator(fn):
            self.handlers[fn.__name__] = fn
            return fn

        return decorator

    async def get_chat_member(self, chat_id, user_id):
        return FakeMember(self.admin)

    async def restrict_chat_member(self, chat_id, user_id, privileges=None, until_date=None):
        # exactly what pyrogram enforces
        assert isinstance(privileges, ChatPermissions), type(privileges)
        assert until_date is None or isinstance(until_date, datetime), type(until_date)
        self.restrictions.append((user_id, privileges, until_date))

    async def promote_chat_member(self, chat_id, user_id, privileges=None):
        assert isinstance(privileges, ChatAdministratorRights), type(privileges)
        self.promotions.append((user_id, privileges))

    async def ban_chat_member(self, chat_id, user_id):
        self.bans.append(user_id)

    async def unban_chat_member(self, chat_id, user_id):
        self.bans.append(-user_id)

    async def send_message(self, *args, **kwargs):
        return None


@pytest.fixture()
def sent(monkeypatch):
    captured: list[str] = []

    async def fake_send(_client, _chat_id, markup, **kwargs):
        captured.append(markup)
        return type("Msg", (), {"id": len(captured), "delete": _noop})()

    async def _noop():
        return None

    monkeypatch.setattr(moderation.rich, "send", fake_send)
    return captured


def _run(handler, client, message):
    asyncio.run(handler(client, message))


def test_tmute_sets_a_real_expiry(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)

    client = FakeClient(admin=True)
    moderation.register(client)

    target = FakeUser(MEMBER_ID, "Spammer")
    reply = FakeMessage("spam", user=target)
    before = datetime.now(timezone.utc)
    _run(
        client.handlers["_mute"],
        client,
        FakeMessage("/tmute 10m", user=FakeUser(ADMIN_ID, "Admin"), reply=reply),
    )

    assert len(client.restrictions) == 1
    user_id, permissions, until = client.restrictions[0]
    assert user_id == MEMBER_ID
    assert permissions.can_send_messages is False
    assert until is not None and until > before
    delta = (until - before).total_seconds()
    assert 590 <= delta <= 610


def test_plain_mute_has_no_expiry(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)

    client = FakeClient(admin=True)
    moderation.register(client)
    reply = FakeMessage("spam", user=FakeUser(MEMBER_ID))

    _run(
        client.handlers["_mute"],
        client,
        FakeMessage("/mute", user=FakeUser(ADMIN_ID, "Admin"), reply=reply),
    )
    assert client.restrictions[0][2] is None


def test_unmute_restores_sending(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)

    client = FakeClient(admin=True)
    moderation.register(client)
    reply = FakeMessage("hi", user=FakeUser(MEMBER_ID))

    _run(
        client.handlers["_unmute"],
        client,
        FakeMessage("/unmute", user=FakeUser(ADMIN_ID, "Admin"), reply=reply),
    )
    assert client.restrictions[0][1].can_send_messages is True


def test_promote_uses_administrator_rights(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)

    client = FakeClient(admin=True)
    moderation.register(client)
    reply = FakeMessage("hi", user=FakeUser(MEMBER_ID))

    _run(
        client.handlers["_promote"],
        client,
        FakeMessage("/promote", user=FakeUser(ADMIN_ID, "Admin"), reply=reply),
    )
    user_id, rights = client.promotions[0]
    assert user_id == MEMBER_ID and rights.can_delete_messages is True


# ── the `d` variants: delete the message that earned it ────────────────────
def _offender():
    """A replied message that remembers being deleted."""
    message = FakeMessage("buy followers cheap", user=FakeUser(MEMBER_ID, "Spammer"))
    message.deleted = False

    async def _delete():
        message.deleted = True

    message.delete = _delete
    return message


def test_dban_removes_the_message_then_bans(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)
    client = FakeClient(admin=True)
    moderation.register(client)

    offender = _offender()
    _run(
        client.handlers["_ban"],
        client,
        FakeMessage("/dban", user=FakeUser(ADMIN_ID, "Admin"), reply=offender),
    )

    assert offender.deleted is True, "the spam is still standing"
    assert client.bans == [MEMBER_ID]
    assert "gone too" in sent[-1]


def test_plain_ban_leaves_the_message_alone(monkeypatch, sent):
    """None of the moderation commands may delete anything by surprise."""
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)
    client = FakeClient(admin=True)
    moderation.register(client)

    offender = _offender()
    _run(
        client.handlers["_ban"],
        client,
        FakeMessage("/ban", user=FakeUser(ADMIN_ID, "Admin"), reply=offender),
    )

    assert offender.deleted is False
    assert client.bans == [MEMBER_ID]


def test_a_message_that_cannot_be_deleted_still_bans(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)
    client = FakeClient(admin=True)
    moderation.register(client)

    offender = _offender()

    async def too_old():
        raise RuntimeError("message is too old to delete")

    offender.delete = too_old
    _run(
        client.handlers["_ban"],
        client,
        FakeMessage("/dban", user=FakeUser(ADMIN_ID, "Admin"), reply=offender),
    )

    assert client.bans == [MEMBER_ID], "a failed delete cancelled the ban"


def test_dkick_and_dwarn_are_the_same_handler(monkeypatch, sent):
    from vyron.core import acl

    monkeypatch.setattr(acl, "is_sudo", lambda _uid: False)
    client = FakeClient(admin=True)
    moderation.register(client)

    kicked = _offender()
    _run(
        client.handlers["_kick"],
        client,
        FakeMessage("/dkick", user=FakeUser(ADMIN_ID, "Admin"), reply=kicked),
    )
    assert kicked.deleted is True
    assert client.bans == [MEMBER_ID, -MEMBER_ID]

    warned = _offender()
    _run(
        client.handlers["_warn"],
        client,
        FakeMessage("/dwarn", user=FakeUser(ADMIN_ID, "Admin"), reply=warned),
    )
    assert warned.deleted is True
    assert "gone too" in sent[-1]
