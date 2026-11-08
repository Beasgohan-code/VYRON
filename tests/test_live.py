"""The live channel: `/ws/room` is what makes the Mini App a player.

The app used to describe a voice chat from five-second polls of one document.
These tests drive the real socket against a real player state and check the
three things that matter to a listener: the clock is authoritative, a control
is a *request* whose answer everyone sees, and somebody who is not allowed to
drive the room is told so instead of silently ignored.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from vyron.core.queue import ChatState, Track
from vyron.web import live


class FakeCalls:
    """tgcalls, as far as the room is concerned: how many people are in the call."""

    def __init__(self, people: int = 3) -> None:
        self.people = people
        self.asked: list[int] = []

    async def get_participants(self, chat_id: int):
        self.asked.append(chat_id)
        return [object() for _ in range(self.people)]


def make_player(*, playing: bool = True, paused: bool = False):
    """A player with one real queue state and the methods the socket calls."""
    track = Track(id="yt1", title="Kesariya", duration=268, uploader="Arijit Singh",
                  requested_name="Asha", requested_by=42)
    state = ChatState(chat_id=-100, current=track, playing=playing)
    state.paused = paused
    state.queue = [Track(id="yt2", title="Tum Hi Ho", duration=260)]
    state.elapsed = lambda: 42.0

    class Player:
        def __init__(self) -> None:
            self.queues = type("Queues", (), {"get": staticmethod(lambda _chat: state)})()
            self.calls: list[tuple[str, object]] = []

        async def pause(self, chat_id):
            state.paused, state.playing = True, False
            self.calls.append(("pause", chat_id))
            return True

        async def resume(self, chat_id):
            state.paused, state.playing = False, True
            self.calls.append(("resume", chat_id))
            return True

        async def toggle(self, chat_id):
            return True

        async def skip(self, chat_id):
            state.queue.clear()
            state.current = Track(id="yt3", title="Channa Mereya", duration=280)
            self.calls.append(("skip", chat_id))
            return state.current

        async def stop(self, chat_id, **_kwargs):
            state.current, state.playing = None, False
            self.calls.append(("stop", chat_id))

        async def seek(self, chat_id, seconds):
            self.calls.append(("seek", seconds))
            return True

        async def set_volume(self, chat_id, volume):
            state.volume = volume
            self.calls.append(("volume", volume))
            return volume

        async def persist(self, chat_id):
            return None

    return Player(), state


#: The fixture's player and state, for tests that need to poke them.
HARNESS: dict[str, object] = {}


@pytest.fixture()
def app(monkeypatch):
    from aiohttp import web

    from vyron.runtime import runtime

    player, state = make_player()
    monkeypatch.setattr(runtime, "player", player, raising=False)
    monkeypatch.setattr(runtime, "calls", FakeCalls(), raising=False)
    monkeypatch.setattr(runtime, "bot", None, raising=False)
    monkeypatch.setattr(runtime, "version", "test", raising=False)
    live.HUB.rooms.clear()

    application = web.Application()
    live.register(application)
    HARNESS["player"] = player
    HARNESS["state"] = state
    return application


def _as_owner(monkeypatch):
    """A caller the socket accepts: the configured owner, signed in."""
    from vyron.config import settings
    from vyron.web import auth

    user = auth.WebUser(
        user_id=settings.owner_id, chat_id=-100, owner=True, name="Owner", source="test"
    )

    async def identify(_request, **_kwargs):
        return user

    monkeypatch.setattr(auth, "identify", identify)
    async def _may(client, _user, _chat):
        return True

    monkeypatch.setattr(live, "_may_control", _may)
    return user


async def _read(ws, *, want: str | None = None, timeout: float = 3.0) -> dict:
    """Read messages until one of type *want* arrives."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        message = await asyncio.wait_for(ws.receive(), timeout=timeout)
        if message.type is not WSMsgType.TEXT:
            raise AssertionError(f"unexpected frame {message.type}")
        payload = message.json()
        if want is None or payload.get("t") == want:
            return payload
    raise AssertionError(f"no {want!r} message within {timeout}s")


def test_a_listener_gets_the_room_the_moment_it_connects(app, monkeypatch):
    _as_owner(monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                hello = await _read(ws, want="hello")
                assert hello["chat_id"] == -100
                assert hello["track"]["title"] == "Kesariya"
                assert hello["track"]["stream"] == "/api/stream/yt1"
                assert hello["position"] == pytest.approx(42.0, abs=0.5)
                assert hello["queue"][0]["title"] == "Tum Hi Ho"
                assert hello["you"]["can_control"] is True
                # participants minus the assistant itself
                assert hello["listen"] == 2

    asyncio.run(scenario())


def test_the_clock_is_pushed_between_states(app, monkeypatch):
    """`sync` is the message that lets the app interpolate instead of snap."""
    _as_owner(monkeypatch)
    monkeypatch.setattr(live, "TICK", 0.05)
    monkeypatch.setattr(live, "IDLE_TICK", 0.05)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                await _read(ws, want="hello")
                sync = await _read(ws, want="sync", timeout=3.0)
                assert "position" in sync and "server_time" in sync
                assert "track" not in sync, "the clock must stay cheap"
                assert sync["playing"] is True

    asyncio.run(scenario())


def test_a_control_is_a_request_and_the_answer_comes_back_with_the_state(app, monkeypatch):
    _as_owner(monkeypatch)
    monkeypatch.setattr(live, "TICK", 0.05)
    player = HARNESS["player"]

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                await _read(ws, want="hello")
                await ws.send_json({"t": "control", "action": "pause"})
                ack = await _read(ws, want="ack")
                assert ack["action"] == "pause" and ack["ok"] is True
                assert player.calls[0] == ("pause", -100)
                # …and every listener is told what the room is doing now
                state = await _read(ws, want="state")
                assert state["paused"] is True

    asyncio.run(scenario())


def test_someone_who_cannot_drive_the_room_is_told_so(app, monkeypatch):
    _as_owner(monkeypatch)

    async def _nope(_client, _user, _chat):
        return False

    monkeypatch.setattr(live, "_may_control", _nope)
    player = HARNESS["player"]

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                await _read(ws, want="hello")
                await ws.send_json({"t": "control", "action": "skip"})
                denied = await _read(ws, want="denied")
                assert denied["reason"] == "admins only"
                assert player.calls == [], "a refused tap must not move the room"

    asyncio.run(scenario())


def test_a_ping_is_answered_so_the_client_can_measure_latency(app, monkeypatch):
    _as_owner(monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                await _read(ws, want="hello")
                sent = time.time()
                await ws.send_json({"t": "ping", "id": 7})
                pong = await _read(ws, want="pong")
                assert pong["id"] == 7
                # the server's clock, not the browser's — an offset needs both
                assert abs(pong["server_time"] - sent) < 5

    asyncio.run(scenario())


def test_a_track_change_is_announced_as_an_event(app, monkeypatch):
    """The activity lane reads these; they are derived from the state diff, so
    every control path — bot command, button, app — produces the same events."""
    _as_owner(monkeypatch)
    monkeypatch.setattr(live, "TICK", 0.05)
    state = HARNESS["state"]

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                await _read(ws, want="hello")
                await asyncio.sleep(0.1)
                state.current = Track(id="yt9", title="Gerua", duration=300)
                event = await _read(ws, want="event")
                assert event["kind"] == "skip"
                assert event["track_id"] == "yt9"

    asyncio.run(scenario())


def test_a_room_without_a_socket_is_torn_down(app, monkeypatch):
    """One ticker per room, and it stops when nobody is watching."""
    _as_owner(monkeypatch)
    monkeypatch.setattr(live, "TICK", 0.05)
    monkeypatch.setattr(live, "EMPTY_GRACE", 0.05)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room?chat_id=-100") as ws:
                await _read(ws, want="hello")
                room = live.HUB.rooms[-100]
                ticker = room.task
                assert ticker is not None and not ticker.done()
            await asyncio.sleep(0.4)
            assert live.HUB.rooms == {}, "the ticker outlived its last listener"
            assert ticker.done(), "the clock kept ticking for nobody"

    asyncio.run(scenario())


def test_the_socket_can_be_asked_for_its_own_chat(app, monkeypatch):
    """No `?chat_id` — a group Mini App link carries exactly one."""
    _as_owner(monkeypatch)

    async def scenario():
        async with TestClient(TestServer(app)) as client:
            async with client.ws_connect("/ws/room") as ws:
                hello = await _read(ws, want="hello")
                assert hello["chat_id"] == -100

    asyncio.run(scenario())
