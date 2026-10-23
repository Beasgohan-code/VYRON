"""Group administration: rules, chat identity, slow mode, approvals, zombies.

These are behavioural tests over the real handlers — no Telegram, no network.
`chatcfg` is swapped for an in-memory dict so the assertions stay about logic.
"""
from __future__ import annotations

import asyncio

import pytest
from pyrogram.enums import ChatMemberStatus, ChatType

pytest.importorskip("pyrogram")

from vyron.core import chatcfg
from vyron.modules import groupadmin
from vyron.ui import cards, rich
from vyron.utils.helpers import parse_duration

OWNER_ID = 424242
ADMIN_ID = 777001
MEMBER_ID = 999111
CHAT_ID = -1009876543210


# ── fakes ───────────────────────────────────────────────────────────────────
class FakeChat:
    def __init__(self, chat_id: int = CHAT_ID, title: str = "Listening Room") -> None:
        self.id = chat_id
        self.title = title
        self.type = ChatType.SUPERGROUP
        self.username = "listening_room"
        self.members_count = 1200
        self.admins_count = 3
        self.online_count = 42
        self.slow_mode_delay = 0
        self.description = "music all day"
        self.has_protected_content = False
        self.is_forum = False
        self.dc_id = 2
        self.invite_link = "https://t.me/+vyron"
        self.pinned_message = None
        self.linked_chat = None


class FakeUser:
    def __init__(self, user_id: int, name: str = "Someone", *, deleted: bool = False) -> None:
        self.id = user_id
        self.first_name = name
        self.last_name = None
        self.username = f"user{user_id}"
        self.is_bot = False
        self.is_deleted = deleted
        self.mention = f'<a href="tg://user?id={user_id}">{name}</a>'

    def __str__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FakeUser {self.id}>"


class FakeMessage:
    def __init__(
        self,
        text: str = "",
        *,
        chat: FakeChat | None = None,
        user: FakeUser | None = None,
        message_id: int = 10,
        reply: "FakeMessage | None" = None,
        new_members: list["FakeUser"] | None = None,
    ) -> None:
        self.text = text
        self.chat = chat or FakeChat()
        self.from_user = user
        self.id = message_id
        self.command = text.split()[0].lstrip("/").split("@")[0:1] if text.startswith("/") else []
        self.caption = None
        self.reply_to_message = reply
        self.link = "https://t.me/c/1/10"
        self.photo = None
        self.new_chat_members = new_members or []
        self._client = None


class FakeMember:
    def __init__(self, status: ChatMemberStatus) -> None:
        self.status = status


class FakeClient:
    """Records handlers and every Telegram call the module makes."""

    def __init__(self, *, admins: set[int] | None = None, bot_admin: bool = True) -> None:
        self.handlers: dict[str, object] = {}
        self.admins = {ADMIN_ID} if admins is None else set(admins)
        self.bot_admin = bot_admin
        self.calls: list[tuple[str, tuple]] = []
        self.me = FakeUser(1, "VyronMusicBot")
        self.me.is_bot = True
        self.members: list[FakeUser] = []

    def on_message(self, *_args, **_kwargs):
        def decorator(fn):
            self.handlers[fn.__name__] = fn
            return fn

        return decorator

    def record(self, name: str, *args) -> None:
        self.calls.append((name, args))

    async def get_chat_member(self, chat_id, user_id):
        self.record("get_chat_member", chat_id, user_id)
        if user_id == self.me.id:
            return FakeMember(
                ChatMemberStatus.ADMINISTRATOR if self.bot_admin else ChatMemberStatus.MEMBER
            )
        status = (
            ChatMemberStatus.ADMINISTRATOR
            if user_id in self.admins
            else ChatMemberStatus.MEMBER
        )
        return FakeMember(status)

    async def get_chat(self, chat_id):
        self.record("get_chat", chat_id)
        return FakeChat(chat_id)

    async def get_chat_members_count(self, chat_id):
        return 1200

    async def get_chat_members(self, chat_id, filter=None):  # noqa: A002 - pyrogram's kwarg
        self.record("get_chat_members", chat_id)
        for user in self.members:
            yield type("Member", (), {"user": user})()

    async def set_chat_title(self, chat_id, title):
        self.record("set_chat_title", chat_id, title)

    async def set_chat_description(self, chat_id, text):
        self.record("set_chat_description", chat_id, text)

    async def set_slow_mode(self, chat_id, seconds):
        self.record("set_slow_mode", chat_id, seconds)

    async def export_chat_invite_link(self, chat_id):
        self.record("export_chat_invite_link", chat_id)
        return "https://t.me/+vyron"

    async def revoke_chat_invite_link(self, chat_id, link):
        self.record("revoke_chat_invite_link", chat_id, link)

    async def restrict_chat_member(self, chat_id, user_id, privileges=None, until_date=None):
        self.record("restrict_chat_member", chat_id, user_id, privileges, until_date)

    async def ban_chat_member(self, chat_id, user_id):
        self.record("ban_chat_member", chat_id, user_id)

    async def unban_chat_member(self, chat_id, user_id):
        self.record("unban_chat_member", chat_id, user_id)

    async def send_message(self, chat_id, text, **kwargs):
        self.record("send_message", chat_id, text)

    def called(self, name: str) -> list[tuple]:
        return [args for call, args in self.calls if call == name]


class Sent(list):
    def __init__(self) -> None:
        super().__init__()
        self.keyboards: list[object] = []

    def last_text(self) -> str:
        return rich.to_plain_text(self[-1]) if self else ""


@pytest.fixture()
def store(monkeypatch):
    """An in-memory chat config instead of Mongo/JSON."""
    data: dict[int, dict] = {}

    async def fake_get(chat_id, key, default=None):
        base = chatcfg.DEFAULTS.get(key)
        if default is None:
            default = base
        return data.get(chat_id, {}).get(key, default)

    async def fake_set(chat_id, key, value):
        data.setdefault(chat_id, {})[key] = value

    monkeypatch.setattr(chatcfg, "get", fake_get)
    monkeypatch.setattr(chatcfg, "set", fake_set)
    return data


@pytest.fixture()
def sent(monkeypatch):
    captured = Sent()

    async def fake_send(_client, _chat_id, markup, **kwargs):
        captured.append(markup)
        captured.keyboards.append(kwargs.get("markup_keyboard"))
        return type("Msg", (), {"id": len(captured), "delete": fake_delete})()

    async def fake_delete():
        return None

    async def fake_edit(_client, _chat_id, _message_id, markup):
        captured.append(markup)
        return None

    monkeypatch.setattr(groupadmin.rich, "send", fake_send)
    monkeypatch.setattr(groupadmin.rich, "edit", fake_edit)
    return captured


def _run(handler, client, message):
    asyncio.run(handler(client, message))


def _client_with_handlers(**kwargs) -> FakeClient:
    client = FakeClient(**kwargs)
    groupadmin.register(client)
    return client


# ── durations ───────────────────────────────────────────────────────────────
def test_parse_duration():
    assert parse_duration("10m") == 600
    assert parse_duration("2h") == 7200
    assert parse_duration("45") == 45
    assert parse_duration("off") == 0
    assert parse_duration("") is None
    assert parse_duration("soon") is None
    assert parse_duration("m") is None


# ── cards ───────────────────────────────────────────────────────────────────
def test_group_admin_card_lists_every_tool():
    markup = cards.group_admin_card(rules="be kind", slowmode=60, approved=2, locked=3)
    text = rich.to_plain_text(markup)
    for needle in ("/settitle", "/slowmode", "/zombies", "/approve", "/report", "/locks"):
        assert needle in text
    assert "set" in text  # rules present
    assert "<details" in markup  # collapsible sections in the rich lane


def test_chat_info_card_escapes_and_summarises():
    info = {
        "title": "<b>Chill</b>",
        "id": CHAT_ID,
        "members": 1200,
        "admins": 3,
        "slowmode": 90,
        "description": "music all day",
        "pinned": "rules",
    }
    markup = cards.chat_info_card(info)
    assert "&lt;b&gt;Chill&lt;/b&gt;" in markup  # untrusted text is escaped
    text = rich.to_plain_text(markup)
    assert "Chill" in text
    assert str(CHAT_ID) in text and "1.2K" in text
    assert "1m" in text  # 90s renders as a minute


def test_zombies_and_approved_cards():
    zombies = rich.to_plain_text(cards.zombies_card([("Ghost", "17")], scanned=10, kicked=1))
    assert "Ghost" in zombies and "1" in zombies
    clean = rich.to_plain_text(cards.zombies_card([], scanned=42))
    assert "All clean" in clean

    empty = rich.to_plain_text(cards.approved_card([]))
    assert "Nobody yet" in empty
    listed = rich.to_plain_text(cards.approved_card([("DJ", "5")]))
    assert "DJ" in listed and "1 exempt" in listed


# ── handlers ────────────────────────────────────────────────────────────────
def test_rules_are_public_and_settable_by_admins(store, sent):
    client = _client_with_handlers()
    chat = FakeChat()
    member = FakeUser(MEMBER_ID, "Member")
    admin = FakeUser(ADMIN_ID, "Admin")

    # a member can read…
    _run(client.handlers["_rules"], client, FakeMessage("/rules", chat=chat, user=member))

    # …but not write
    _run(
        client.handlers["_setrules"],
        client,
        FakeMessage("/setrules be kind", chat=chat, user=member),
    )
    assert chatcfg.DEFAULTS["rules"] == ""
    assert "ask an admin" in sent.last_text().lower()
    assert "rules" not in store.get(CHAT_ID, {})

    # an admin can
    _run(
        client.handlers["_setrules"],
        client,
        FakeMessage("/setrules be kind · no spam", chat=chat, user=admin),
    )
    assert store[CHAT_ID]["rules"].startswith("be kind")
    assert "be kind" in sent.last_text()

    _run(client.handlers["_rules"], client, FakeMessage("/rules", chat=chat, user=member))
    assert "be kind" in sent.last_text()

    _run(client.handlers["_clearrules"], client, FakeMessage("/clearrules", chat=chat, user=admin))
    assert store[CHAT_ID]["rules"] == ""
    _run(client.handlers["_rules"], client, FakeMessage("/rules", chat=chat, user=member))
    assert "No rules yet." in sent.last_text()


def test_chat_info_reads_the_real_chat(store, sent):
    client = _client_with_handlers()
    message = FakeMessage("/chatinfo", user=FakeUser(MEMBER_ID))

    _run(client.handlers["_info"], client, message)

    text = sent.last_text()
    assert "Listening Room" in text and str(CHAT_ID) in text
    assert client.called("get_chat")


def test_settitle_and_slowmode_talk_to_telegram(store, sent):
    client = _client_with_handlers()
    admin = FakeUser(ADMIN_ID, "Admin")
    chat = FakeChat()

    _run(
        client.handlers["_settitle"],
        client,
        FakeMessage("/settitle Night Shift", chat=chat, user=admin),
    )
    assert client.called("set_chat_title") == [(CHAT_ID, "Night Shift")]

    _run(client.handlers["_slowmode"], client, FakeMessage("/slowmode 30s", chat=chat, user=admin))
    assert client.called("set_slow_mode") == [(CHAT_ID, 30)]
    assert store[CHAT_ID]["slowmode"] == 30

    _run(client.handlers["_slowmode"], client, FakeMessage("/slowmode off", chat=chat, user=admin))
    assert client.called("set_slow_mode")[-1] == (CHAT_ID, 0)

    # invalid input never reaches Telegram
    before = len(client.called("set_slow_mode"))
    _run(client.handlers["_slowmode"], client, FakeMessage("/slowmode soon", chat=chat, user=admin))
    assert len(client.called("set_slow_mode")) == before


def test_approve_and_unapprove_track_users(store, sent):
    client = _client_with_handlers()
    admin = FakeUser(ADMIN_ID, "Admin")
    target = FakeUser(MEMBER_ID, "Trusted")
    reply = FakeMessage("hi", user=target)
    chat = FakeChat()

    _run(client.handlers["_approve"], client, FakeMessage("/approve", chat=chat, user=admin, reply=reply))
    assert store[CHAT_ID]["approved"] == [MEMBER_ID]

    _run(client.handlers["_approved_list"], client, FakeMessage("/approved", chat=chat, user=admin))
    assert str(MEMBER_ID) in sent.last_text()

    # repeated approvals are idempotent
    _run(client.handlers["_approve"], client, FakeMessage("/approve", chat=chat, user=admin, reply=reply))
    assert store[CHAT_ID]["approved"] == [MEMBER_ID]

    _run(
        client.handlers["_unapprove"],
        client,
        FakeMessage("/unapprove", chat=chat, user=admin, reply=reply),
    )
    assert store[CHAT_ID]["approved"] == []


def test_zombies_finds_and_kicks_deleted_accounts(store, sent):
    client = _client_with_handlers()
    client.members = [
        FakeUser(1, "Alive"),
        FakeUser(2, "Ghost", deleted=True),
        FakeUser(3, "Phantom", deleted=True),
    ]
    admin = FakeUser(ADMIN_ID, "Admin")

    _run(client.handlers["_zombies"], client, FakeMessage("/zombies", user=admin))

    text = sent.last_text()
    assert "2 deleted" in text and "Ghost" in text
    assert client.called("ban_chat_member") == []  # listing alone never kicks

    client.calls.clear()
    _run(client.handlers["_zombies"], client, FakeMessage("/zombies kick", user=admin))
    assert len(client.called("ban_chat_member")) == 2
    assert len(client.called("unban_chat_member")) == 2
    assert "kicked" in sent.last_text().lower()


def test_group_panel_is_admin_only(store, sent):
    client = _client_with_handlers(admins=set())
    member = FakeUser(MEMBER_ID, "Member")

    _run(client.handlers["_panel"], client, FakeMessage("/gadmin", user=member))
    assert "ask an admin" in sent.last_text().lower()

    client = _client_with_handlers()
    _run(client.handlers["_panel"], client, FakeMessage("/gadmin", user=FakeUser(ADMIN_ID, "Admin")))
    text = sent.last_text()
    assert "/settitle" in text and "/zombies" in text and "admin rights ok" in text


def test_invite_and_revoke(store, sent):
    client = _client_with_handlers()
    admin = FakeUser(ADMIN_ID, "Admin")

    _run(client.handlers["_invite"], client, FakeMessage("/invitelink", user=admin))
    assert "https://t.me/+vyron" in sent.last_text()

    _run(client.handlers["_revoke"], client, FakeMessage("/revokeinvite", user=admin))
    assert client.called("revoke_chat_invite_link") == [(CHAT_ID, "https://t.me/+vyron")]
    assert "can no longer join" in sent.last_text()


# ── captcha ─────────────────────────────────────────────────────────────────
class FakeQuery:
    def __init__(self, user: FakeUser, chat: FakeChat) -> None:
        self.from_user = user
        self.message = FakeMessage(chat=chat, user=user)
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


def test_captcha_gate_mutes_then_verifies(store, sent):
    client = _client_with_handlers()
    admin = FakeUser(ADMIN_ID, "Admin")
    chat = FakeChat()

    _run(client.handlers["_captcha_toggle"], client, FakeMessage("/captcha on", chat=chat, user=admin))
    assert store[CHAT_ID]["captcha"] is True

    newcomer = FakeUser(MEMBER_ID, "Newbie")
    _run(
        client.handlers["_gate"],
        client,
        FakeMessage(chat=chat, user=newcomer, new_members=[newcomer]),
    )
    restrict = client.called("restrict_chat_member")
    assert restrict and restrict[0][1] == MEMBER_ID
    assert restrict[0][2].can_send_messages is False
    assert "human" in sent.last_text().lower()

    # somebody else cannot solve it for them
    stranger = FakeQuery(FakeUser(555000, "Stranger"), chat)
    asyncio.run(groupadmin.verify_captcha(client, stranger, CHAT_ID, str(MEMBER_ID)))
    assert stranger.answers and stranger.answers[0][1] is True
    assert client.called("restrict_chat_member")[-1][2].can_send_messages is False

    # the new member can
    good = FakeQuery(newcomer, chat)
    asyncio.run(groupadmin.verify_captcha(client, good, CHAT_ID, str(MEMBER_ID)))
    assert client.called("restrict_chat_member")[-1][2].can_send_messages is True
    assert "verified" in good.answers[-1][0].lower()
