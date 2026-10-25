"""Callback router: the owner-credential buttons must actually do something.

A dead button is worse than no button, so these drive the real dispatcher with
a stubbed Telegram client and check the state that changed.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from pyrogram.enums import ChatType

from vyron.config import settings


class FakeChat:
    def __init__(self, kind: ChatType, chat_id: int) -> None:
        self.type = kind
        self.id = chat_id
        self.title = ""


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id
        self.first_name = "Owner"
        self.username = "owner"


class FakeMessage:
    def __init__(self, chat: FakeChat, message_id: int = 11) -> None:
        self.chat = chat
        self.id = message_id
        self.photo = None


class FakeQuery:
    def __init__(self, data: str, chat: FakeChat, user: FakeUser) -> None:
        self.data = data
        self.message = FakeMessage(chat)
        self.from_user = user
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.answers.append((text, show_alert))


class FakeClient:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def on_callback_query(self, *_args, **_kwargs):
        def decorator(fn):
            self.handlers["router"] = fn
            return fn

        return decorator


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Router + a real JSON storage + captured edits instead of Telegram."""
    from vyron.core import tokens
    from vyron.database import JsonStorage
    from vyron.modules import callbacks
    from vyron.runtime import runtime

    storage = JsonStorage(settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)
    tokens.reset_cache()

    edited: list[str] = []

    async def fake_edit(_client, _chat_id, _message_id, markup, **_kwargs):
        edited.append(markup)

    monkeypatch.setattr(callbacks.rich, "edit", fake_edit)

    client = FakeClient()
    callbacks.register(client)
    return client, tokens, edited


def _dispatch(client, data: str, *, chat_type=ChatType.PRIVATE, user_id=None):
    query = FakeQuery(
        data,
        FakeChat(chat_type, 424242),
        FakeUser(user_id if user_id is not None else settings.owner_id),
    )
    asyncio.run(client.handlers["router"](FakeClient(), query))
    return query


def test_revoke_asks_first_then_bumps_the_epoch(wired):
    client, tokens, edited = wired

    _dispatch(client, "v:token:revoke")
    assert "confirm" in edited[-1]
    assert tokens.cached_epoch(settings.owner_id) in (None, 0)

    _dispatch(client, "v:token:confirm")
    assert tokens.cached_epoch(settings.owner_id) == 1
    from vyron.ui.rich import to_plain_text

    assert "revoked" in to_plain_text(edited[-1]).lower()


def test_cancel_leaves_the_epoch_alone(wired):
    client, tokens, edited = wired
    _dispatch(client, "v:token:revoke")
    _dispatch(client, "v:token:cancel")
    assert tokens.cached_epoch(settings.owner_id) in (None, 0)
    assert "still valid" in edited[-1]


def test_rotate_issues_a_token_at_the_new_epoch(wired):
    client, tokens, edited = wired
    _dispatch(client, "v:token:rotate")
    assert tokens.cached_epoch(settings.owner_id) == 1
    from vyron.web import auth

    found = [
        part.split("vown_", 1)[1].split("<", 1)[0]
        for part in edited[-1].split("<code>")
        if "vown_" in part
    ]
    assert found, "the card must show the new token"
    who = auth.verify_owner_token("vown_" + found[0], settings.bot_token)
    assert who is not None and who.epoch == 1


def test_a_stranger_cannot_touch_owner_tokens(wired):
    client, tokens, edited = wired
    query = _dispatch(client, "v:token:revoke", user_id=999)
    assert edited == []
    assert query.answers and query.answers[-1][1] is True  # alert shown
    assert tokens.cached_epoch(settings.owner_id) in (None, 0)


def test_owner_tools_refuse_a_group_chat(wired):
    client, _tokens, edited = wired
    query = _dispatch(client, "v:token:revoke", chat_type=ChatType.SUPERGROUP)
    assert edited == []
    assert query.answers[-1][1] is True


# ── pickers: /suggest suggestions and saved playlists ──────────────────────
class FakePlayer:
    def __init__(self) -> None:
        from types import SimpleNamespace

        from vyron.core.queue import ChatState

        self.queued: list = []
        self.queues = SimpleNamespace(get=lambda chat_id: ChatState(chat_id=chat_id))

    async def enqueue(self, chat_id, track, **_kwargs):
        self.queued.append(track)
        return len(self.queued)


def test_a_suggestion_button_queues_the_track(wired, monkeypatch):
    from vyron.core import pending
    from vyron.core.queue import Track
    from vyron.runtime import runtime

    client, _tokens, _edited = wired
    player = FakePlayer()
    monkeypatch.setattr(runtime, "player", player)

    tracks = [Track(id="a", title="First", duration=100), Track(id="b", title="Second", duration=120)]
    pending.put(424242, 11, settings.owner_id, "lofi", tracks)

    query = _dispatch(client, "v:p:1")

    assert [track.id for track in player.queued] == ["b"]
    assert "Queued" in query.answers[-1][0]


def test_a_stale_suggestion_list_says_so(wired, monkeypatch):
    from vyron.runtime import runtime

    client, _tokens, _edited = wired
    monkeypatch.setattr(runtime, "player", FakePlayer())

    query = _dispatch(client, "v:p:4")

    assert query.answers[-1][1] is True  # alert
    assert "expired" in query.answers[-1][0].lower()


def test_queue_it_queues_a_saved_playlist(wired, monkeypatch):
    from vyron.core import playlists as store
    from vyron.core.queue import Track
    from vyron.runtime import runtime

    client, _tokens, _edited = wired
    player = FakePlayer()
    monkeypatch.setattr(runtime, "player", player)

    playlist = asyncio.run(store.create(settings.owner_id, "road trip"))
    asyncio.run(
        store.add_tracks(
            settings.owner_id,
            playlist["id"],
            [Track(id="x", title="One", duration=90), Track(id="y", title="Two", duration=95)],
        )
    )

    query = _dispatch(client, f"v:pl:{playlist['id']}")

    assert len(player.queued) == 2
    assert "Queued 2" in query.answers[-1][0]


def test_the_broad_router_steps_aside_for_dedicated_ones(wired):
    """`v:logs:` and `v:unblock:` own their ack — answering twice breaks them."""
    client, _tokens, _edited = wired

    logs = _dispatch(client, "v:logs:all")
    unblock = _dispatch(client, "v:unblock:123")

    assert logs.answers == []
    assert unblock.answers == []


# ── per-chat artwork from the settings panel ───────────────────────────────
def test_the_settings_panel_can_show_artwork(wired):
    client, _tokens, edited = wired

    query = _dispatch(client, "v:thumb:show")

    from vyron.ui.rich import to_plain_text

    assert "backdrop" in to_plain_text(edited[-1])
    assert "/thumbnail" in edited[-1]
    assert query.answers[-1][0]


def test_artwork_can_be_removed_from_the_panel(wired):
    from vyron.core import chatcfg
    from vyron.runtime import runtime

    client, _tokens, _edited = wired
    asyncio.run(chatcfg.set(424242, "thumbnail", "file-id"))

    _dispatch(client, "v:thumb:off")

    assert asyncio.run(chatcfg.get(424242, "thumbnail", "")) == ""
    assert runtime.storage is not None


def test_the_video_button_replays_the_track_with_its_picture(wired, monkeypatch):
    """/play starts audio on purpose; one tap should bring the picture back."""
    from vyron.core.player import ChatState
    from vyron.core.queue import Track
    from vyron.runtime import runtime

    client, _tokens, edited = wired
    state = ChatState(
        chat_id=424242,
        current=Track(id="yt1", title="Believer", duration=200, source="youtube"),
        playing=True,
    )
    state.elapsed = lambda: 42.0

    played: list[dict] = []

    class Player:
        def __init__(self):
            self.queues = types.SimpleNamespace(get=lambda _chat: state)

        async def play_track(self, _chat, track, **kwargs):
            played.append({"track": track, **kwargs})
            state.is_video = bool(kwargs.get("video"))
            return "streamed"

    monkeypatch.setattr(runtime, "player", Player(), raising=False)

    _dispatch(client, "v:video")

    assert played and played[0]["video"] is True
    assert played[0]["seek"] == 42  # continues, does not restart
    # the card that replaced it is the started card again
    assert "ɴᴏᴡ ꜱᴛʀᴇᴀᴍɪɴɢ" in edited[-1] or "now streaming" in edited[-1].lower()


def _picker_state(monkeypatch, tracks):
    """Wire a real pending search + a stub player, and return the edits list."""
    from vyron.core import pending
    from vyron.runtime import runtime

    state = types.SimpleNamespace(current=tracks[0], queue=[], is_video=False)

    class Player:
        def __init__(self):
            self.queues = types.SimpleNamespace(get=lambda _chat: state)
            self.added: list[dict] = []

        async def enqueue(self, _chat, track, **kwargs):
            self.added.append({"track": track, **kwargs})
            return len(self.added) + 1

    player = Player()
    monkeypatch.setattr(runtime, "player", player, raising=False)
    pending.put(424242, 11, 1, "believer", list(tracks), mode="play")
    return player


def test_the_search_expiry_message_is_not_a_crash(wired, monkeypatch):
    """No pending search (expired, or a restarted process) is a toast, not a crash."""
    from vyron.runtime import runtime

    client, _tokens, _edited = wired
    state = types.SimpleNamespace(current=None, queue=[], is_video=False)
    monkeypatch.setattr(
        runtime,
        "player",
        types.SimpleNamespace(queues=types.SimpleNamespace(get=lambda _chat: state)),
        raising=False,
    )
    query = _dispatch(client, "v:pick:3")
    assert query.answers[-1][1] is True  # a toast, because there is no search
    assert "expired" in query.answers[-1][0].lower()


def test_other_results_reopens_the_picker(wired, monkeypatch):
    from vyron.core.queue import Track

    client, _tokens, edited = wired
    tracks = [
        Track(id="1", title="Believer", uploader="Imagine Dragons", duration=204),
        Track(id="2", title="Believer live", uploader="Imagine Dragons", duration=240),
    ]
    _picker_state(monkeypatch, tracks)

    _dispatch(client, "v:pick:list")

    from vyron.ui.rich import to_plain_text

    assert "results" in to_plain_text(edited[-1]).lower()
    assert 'data="v:pick:1"' in edited[-1]


def test_queueing_a_result_does_not_interrupt_the_song(wired, monkeypatch):
    from vyron.core.queue import Track

    client, _tokens, _edited = wired
    tracks = [
        Track(id="1", title="Believer", uploader="Imagine Dragons", duration=204),
        Track(id="2", title="Thunder", uploader="Imagine Dragons", duration=190),
    ]
    player = _picker_state(monkeypatch, tracks)

    query = _dispatch(client, "v:pick:q1")

    assert player.added[0]["track"].id == "2"
    assert player.added[0].get("index") is None  # appended, not jumped
    assert "Queued" in query.answers[-1][0]


def test_play_next_puts_the_result_at_the_front(wired, monkeypatch):
    from vyron.core.queue import Track

    client, _tokens, _edited = wired
    tracks = [
        Track(id="1", title="Believer", uploader="Imagine Dragons", duration=204),
        Track(id="2", title="Thunder", uploader="Imagine Dragons", duration=190),
    ]
    player = _picker_state(monkeypatch, tracks)

    query = _dispatch(client, "v:pick:n1")

    assert player.added[0]["index"] == 0
    assert "next" in query.answers[-1][0].lower()
