"""Presence tests — what happens when the bot is added to or removed from a chat.

Two promises are tested here:

1. being **removed** drops everything the bot kept for that chat (queue, poster,
   stored per-chat settings) and gets the assistant out of the voice call;
2. being **added** answers with the group card instead of silence.
"""
from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace

from vyron.config import Settings


def member(status, uid=1, is_member=False):
    return SimpleNamespace(user=SimpleNamespace(id=uid), status=status, is_member=is_member)


def update(old, new, chat_id=-1001, from_id=7):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, title="Test Group"),
        from_user=SimpleNamespace(id=from_id, first_name="Rahul"),
        old_chat_member=old,
        new_chat_member=new,
    )


def client_with(uid=999):
    return SimpleNamespace(me=SimpleNamespace(id=uid))


ME = 999


# ── classification ─────────────────────────────────────────────────────────
def test_transition_reads_join_and_removal():
    from vyron.modules import presence

    assert presence.transition(update(member("LEFT"), member("MEMBER"))) == "joined"
    assert presence.transition(update(member("MEMBER"), member("LEFT"))) == "removed"
    assert presence.transition(update(member("MEMBER"), member("BANNED"))) == "removed"
    # promotion is not a presence change
    assert presence.transition(update(member("MEMBER"), member("ADMINISTRATOR"))) == ""


def test_restricted_member_is_judged_by_is_member():
    from vyron.modules import presence

    out = member("RESTRICTED", is_member=False)
    inside = member("RESTRICTED", is_member=True)
    assert presence.__dict__["_presence"](out) is False
    assert presence.__dict__["_presence"](inside) is True
    # being restricted is not being removed
    assert presence.transition(update(member("MEMBER"), inside)) == ""
    assert presence.transition(update(inside, out)) == "removed"


def test_status_handles_enums_and_plain_strings():
    from vyron.modules import presence

    assert presence._status(SimpleNamespace(status="member")) == "MEMBER"
    assert presence._status(SimpleNamespace(status=SimpleNamespace(name="OWNER"))) == "OWNER"
    # an unknown status must read as "not in the chat", never crash
    assert presence._status(SimpleNamespace(status=None)) == ""


def test_only_my_own_membership_counts():
    from vyron.modules import presence

    mine = update(member("LEFT", uid=ME), member("MEMBER", uid=ME))
    theirs = update(member("LEFT", uid=5), member("MEMBER", uid=5))
    assert presence.is_for_me(client_with(ME), mine) is True
    assert presence.is_for_me(client_with(ME), theirs) is False
    assert presence.is_for_me(SimpleNamespace(me=None), mine) is False


# ── behaviour ──────────────────────────────────────────────────────────────
def test_removal_abandons_the_chat(monkeypatch):
    from vyron.modules import presence
    from vyron.runtime import runtime

    abandoned: list[int] = []

    class FakePlayer:
        async def abandon(self, chat_id):
            abandoned.append(chat_id)

    monkeypatch.setattr(runtime, "player", FakePlayer(), raising=False)
    result = asyncio.run(
        presence.handle(client_with(ME), update(member("MEMBER", uid=ME), member("LEFT", uid=ME)))
    )
    assert result == "removed"
    assert abandoned == [-1001]


def test_removal_still_reports_when_the_player_fails(monkeypatch):
    from vyron.modules import presence
    from vyron.runtime import runtime

    class AngryPlayer:
        async def abandon(self, chat_id):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(runtime, "player", AngryPlayer(), raising=False)
    assert asyncio.run(
        presence.handle(client_with(ME), update(member("MEMBER", uid=ME), member("BANNED", uid=ME)))
    ) == "removed"


def test_join_sends_the_group_card(monkeypatch):
    from vyron.modules import presence, start as start_module
    from vyron.ui import rich

    sent: list[tuple[int, str]] = []

    async def fake_group_card(client, chat, user=None):
        return "<b>group card</b>"

    async def fake_send(client, chat_id, markup, **kwargs):
        sent.append((chat_id, markup))
        return None

    monkeypatch.setattr(start_module, "group_card", fake_group_card)
    monkeypatch.setattr(rich, "send", fake_send)

    result = asyncio.run(
        presence.handle(client_with(ME), update(member("LEFT", uid=ME), member("MEMBER", uid=ME)))
    )
    assert result == "joined"
    assert sent == [(-1001, "<b>group card</b>")]


def test_join_never_raises_when_the_card_fails(monkeypatch):
    from vyron.modules import presence, start as start_module

    async def broken(client, chat, user=None):
        raise RuntimeError("telegram said no")

    monkeypatch.setattr(start_module, "group_card", broken)
    assert asyncio.run(
        presence.handle(client_with(ME), update(member("LEFT", uid=ME), member("MEMBER", uid=ME)))
    ) == "joined"


# ── the cleanup itself ─────────────────────────────────────────────────────
def test_abandon_drops_the_queue_and_forgets_the_chat():
    from vyron.core.player import Player
    from vyron.core.queue import Track

    class FakeCalls:
        def __init__(self):
            self.left = []

        async def leave_call(self, chat_id):
            self.left.append(chat_id)

    class FakeYouTube:
        async def stream_url(self, track, video=False):  # pragma: no cover - unused
            return "https://cdn/x.m4a"

    class FakeStorage:
        def __init__(self):
            self.deleted = []
            self.meta = {}

        async def chat_settings(self, chat_id):
            return {}

        async def save_chat_settings(self, chat_id, data): ...

        async def delete_chat_settings(self, chat_id):
            self.deleted.append(chat_id)
            return True

        async def get_meta(self, key, default=None):
            return self.meta.get(key, default)

        async def set_meta(self, key, value):
            self.meta[key] = value

    settings = SimpleNamespace(
        default_volume=100,
        autoplay_default=False,
        max_queue_size=20,
        np_refresh_seconds=45,
        idle_leave_seconds=300,
        play_from_disk=True,
        preheat_depth=2,
        preheat_seconds=25,
        audio_quality="high",
        video_quality="720p",
    )
    calls = FakeCalls()
    storage = FakeStorage()
    player = Player(
        bot=None,
        calls=calls,
        settings=settings,
        storage=storage,
        youtube=FakeYouTube(),
    )
    state = player.queues.get(-1001)
    state.volume = 40
    state.current = Track(id="a", title="A", duration=100)
    state.queue.append(Track(id="b", title="B", duration=100))

    asyncio.run(player.abandon(-1001))

    assert player.queues.exists(-1001) is False
    assert calls.left == [-1001]
    assert storage.deleted == [-1001]
    assert -1001 not in player._settings_loaded
    # a later /play in that group starts from the defaults, not from volume 40
    assert player.queues.get(-1001).volume == 100


def test_abandon_on_a_chat_that_never_played_still_forgets_it():
    from vyron.core.player import Player

    class FakeStorage:
        def __init__(self):
            self.deleted = []

        async def delete_chat_settings(self, chat_id):
            self.deleted.append(chat_id)
            return False

        async def set_meta(self, key, value): ...

    settings = SimpleNamespace(
        default_volume=100,
        autoplay_default=False,
        max_queue_size=20,
    )
    storage = FakeStorage()
    player = Player(bot=None, calls=None, settings=settings, storage=storage, youtube=None)

    asyncio.run(player.abandon(-2002))

    assert storage.deleted == [-2002]
    assert player.queues.exists(-2002) is False


# ── storage backends ───────────────────────────────────────────────────────
def test_json_storage_forgets_a_chat(tmp_path):
    from vyron.database import JsonStorage

    settings = dataclasses.replace(Settings(), data_dir=str(tmp_path))
    storage = JsonStorage(settings)
    asyncio.run(storage.connect())
    asyncio.run(storage.save_chat_settings(-1001, {"volume": 40}))
    assert asyncio.run(storage.chat_settings(-1001)) == {"volume": 40}

    assert asyncio.run(storage.delete_chat_settings(-1001)) is True
    assert asyncio.run(storage.chat_settings(-1001)) == {}
    assert asyncio.run(storage.delete_chat_settings(-1001)) is False
    assert asyncio.run(storage.all_chat_ids()) == []


def test_mongo_storage_forgets_a_chat(monkeypatch):
    import sys
    import types

    deleted: list[dict] = []

    class FakeChats:
        def delete_one(self, query):
            deleted.append(query)
            return SimpleNamespace(deleted_count=1)

    class FakeClient:
        def __init__(self, *args, **kwargs): ...

        def __getitem__(self, name):
            return SimpleNamespace(chats=FakeChats())

        def close(self): ...

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=FakeClient))

    from vyron.database import MongoStorage

    settings = dataclasses.replace(
        Settings(), mongo_url="mongodb+srv://u:p@cluster/db", mongo_db="vyron"
    )
    storage = MongoStorage(settings)
    storage._db = SimpleNamespace(chats=FakeChats())

    assert asyncio.run(storage.delete_chat_settings(-1001)) is True
    assert deleted == [{"chat_id": -1001}]


# ── the assistant, which is the account that actually joins the call ───────
ASSISTANT = 4242


def with_assistant(monkeypatch, uid=ASSISTANT):
    from vyron.runtime import runtime

    monkeypatch.setattr(
        runtime, "assistant", SimpleNamespace(me=SimpleNamespace(id=uid)), raising=False
    )


def test_the_assistant_is_told_apart_from_the_bot(monkeypatch):
    from vyron.modules import presence

    with_assistant(monkeypatch)
    ours = update(member("LEFT", uid=ASSISTANT), member("MEMBER", uid=ASSISTANT))
    mine = update(member("LEFT", uid=ME), member("MEMBER", uid=ME))
    theirs = update(member("LEFT", uid=5), member("MEMBER", uid=5))
    assert presence.subject_of(client_with(ME), ours) == "assistant"
    assert presence.subject_of(client_with(ME), mine) == "bot"
    assert presence.subject_of(client_with(ME), theirs) == ""
    # an update about the bot is never mistaken for the assistant
    assert presence.is_for_assistant(mine) is False


def test_without_an_assistant_nothing_is_attributed_to_one(monkeypatch):
    from vyron.modules import presence
    from vyron.runtime import runtime

    monkeypatch.setattr(runtime, "assistant", None, raising=False)
    ours = update(member("LEFT", uid=ASSISTANT), member("MEMBER", uid=ASSISTANT))
    assert presence.is_for_assistant(ours) is False
    assert presence.subject_of(client_with(ME), ours) == ""


def test_kicking_the_assistant_clears_the_queue_and_says_why(monkeypatch):
    from vyron.modules import presence
    from vyron.runtime import runtime
    from vyron.ui import cards

    abandoned: list[int] = []
    cards_sent: list[tuple] = []

    class FakePlayer:
        async def abandon(self, chat_id):
            abandoned.append(chat_id)

    def fake_warn(text):
        return f"<b>warn</b>{text}"

    async def fake_send(client, chat_id, markup, **kwargs):
        cards_sent.append((chat_id, markup))
        return None

    with_assistant(monkeypatch)
    monkeypatch.setattr(runtime, "player", FakePlayer(), raising=False)
    monkeypatch.setattr(cards, "warn_card", fake_warn)
    from vyron.ui import rich

    monkeypatch.setattr(rich, "send", fake_send)

    result = asyncio.run(
        presence.handle(
            client_with(ME),
            update(member("MEMBER", uid=ASSISTANT), member("BANNED", uid=ASSISTANT)),
        )
    )
    assert result == "removed"
    assert abandoned == [-1001]
    assert len(cards_sent) == 1
    chat_id, text = cards_sent[0]
    assert chat_id == -1001
    assert "assistant" in text or "voice account" in text


def test_kicking_the_assistant_never_raises_when_messaging_fails(monkeypatch):
    from vyron.modules import presence
    from vyron.ui import rich

    async def broken(client, chat_id, markup, **kwargs):
        raise RuntimeError("chat is gone")

    with_assistant(monkeypatch)
    monkeypatch.setattr(rich, "send", broken)
    assert asyncio.run(
        presence.handle(
            client_with(ME),
            update(member("MEMBER", uid=ASSISTANT), member("LEFT", uid=ASSISTANT)),
        )
    ) == "removed"


def test_the_assistant_joining_is_only_a_log_line(monkeypatch):
    from vyron.modules import presence

    with_assistant(monkeypatch)
    result = asyncio.run(
        presence.handle(
            client_with(ME),
            update(member("LEFT", uid=ASSISTANT), member("MEMBER", uid=ASSISTANT)),
        )
    )
    assert result == "joined"
