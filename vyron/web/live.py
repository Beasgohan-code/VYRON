# ---------------------------------------------------------------------------
#  VYRON — live rooms
#
#  The Mini App used to describe a voice chat from 5-second polls of one
#  document: fine for a settings screen, useless for a player. This is the
#  other half — a WebSocket per room that carries:
#
#      state   the whole room, whenever something actually changed
#      sync    the clock, once a second, when something is playing
#      event   what just happened ("Asha skipped the track")
#      pong    the answer a ping needs to estimate one-way latency
#
#  Why a socket and not a faster poll: sync has to describe *now*. A poll can
#  only tell you where the room was when the request left, and the answer is
#  already a round trip stale by the time it renders. With a socket the client
#  keeps an offset between its own clock and the server's, and can therefore
#  draw the playhead between messages instead of snapping it every tick.
#
#  The server stays the only authority. A client that taps pause sends a
#  request; the room's real state comes back as a `state` message, and every
#  other listener sees it at the same moment. Nothing here trusts a client's
#  idea of where the track is.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from aiohttp import WSMsgType, web

from vyron.runtime import runtime
from vyron.web.auth import WebUser

logger = logging.getLogger(__name__)

#: How often the clock is pushed while a track is playing. One second is the
#: slowest cadence that still lets a client interpolate smoothly: it is only a
#: correction, because the client advances the playhead itself between ticks.
TICK = 1.0
#: …and while nothing is playing, when there is no clock to keep.
IDLE_TICK = 5.0
#: How often the listener count is asked for. `get_participants` is a group-call
#: round trip, so it is deliberately slower than the clock and never awaited by
#: the sync loop itself.
PEOPLE_EVERY = 6.0
#: A room with no subscribers is torn down; one that is merely quiet is not.
EMPTY_GRACE = 30.0

MAX_MESSAGE = 4096

#: Sockets that are leaving. `HUB.leave` waits out `EMPTY_GRACE`, so it cannot
#: be awaited by the handler itself — but a task nobody holds a reference to may
#: be collected before it runs, so they are kept here until they finish.
_LEAVING: set[asyncio.Task] = set()


def _later(coro, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _LEAVING.add(task)
    task.add_done_callback(_LEAVING.discard)


def _track_json(track: Any) -> dict | None:
    """The same shape `/api/state` uses — one vocabulary for one track."""
    if track is None:
        return None
    return {
        "id": getattr(track, "id", "") or "",
        "title": getattr(track, "title", "") or "",
        "uploader": getattr(track, "uploader", "") or "",
        "duration": int(getattr(track, "duration", 0) or 0),
        "thumbnail": getattr(track, "thumbnail", "") or "",
        "requested_by": getattr(track, "requested_name", "") or "",
        "is_video": bool(getattr(track, "is_video", False)),
        "source": getattr(track, "source", "") or "",
        "stream": f"/api/stream/{getattr(track, 'id', '')}",
    }


def _signature(state: Any) -> tuple:
    """What makes a `state` message worth sending.

    The clock is not in here — it is what `sync` is for. Everything that is,
    changes only when somebody does something, which is exactly when the app
    has to redraw.
    """
    if state is None:
        return ("idle",)
    current = getattr(state, "current", None)
    return (
        getattr(current, "id", "") or "",
        bool(getattr(state, "paused", False)),
        int(getattr(state, "volume", 0) or 0),
        len(getattr(state, "queue", []) or []),
        str(getattr(getattr(state, "loop", None), "value", "")),
        tuple(getattr(state, "effects", []) or []),
        bool(getattr(state, "autoplay", False)),
        bool(getattr(state, "is_video", False)),
    )


class Room:
    """One chat's live fan-out: the sockets, the last state, the clock loop."""

    def __init__(self, chat_id: int) -> None:
        self.chat_id = chat_id
        self.clients: set[web.WebSocketResponse] = set()
        self.task: asyncio.Task[None] | None = None
        self.signature: tuple | None = None
        self.people: int = 0
        self._people_at = 0.0
        self._closed = asyncio.Event()
        #: Set to cut a `sync` sleep short (a tap should not wait out the tick).
        self._wake = asyncio.Event()

    # ── state ──────────────────────────────────────────────────────────────
    def _player(self):
        return runtime.player

    def position(self) -> float:
        player = self._player()
        state = player.queues.get(self.chat_id) if player else None
        if state is None:
            return 0.0
        try:
            return max(0.0, float(state.elapsed() or 0.0))
        except Exception:  # pragma: no cover - a state that cannot answer yet
            return 0.0

    def snapshot(self, *, full: bool = True) -> dict:
        player = self._player()
        state = player.queues.get(self.chat_id) if player else None
        current = getattr(state, "current", None)
        payload: dict[str, Any] = {
            "t": "state" if full else "sync",
            "chat_id": self.chat_id,
            "server_time": round(time.time(), 3),
            "position": round(self.position(), 3),
            "playing": bool(getattr(state, "playing", False)),
            "paused": bool(getattr(state, "paused", False)),
            "has_track": current is not None,
        }
        if not full:
            return payload
        payload.update(
            {
                "track": _track_json(current),
                "queue": [
                    {**_track_json(track), "index": index + 1}
                    for index, track in enumerate((getattr(state, "queue", []) or [])[:60])
                ],
                "volume": int(getattr(state, "volume", 100) or 0),
                "loop": str(getattr(getattr(state, "loop", None), "value", "off")),
                "autoplay": bool(getattr(state, "autoplay", False)),
                "effects": list(getattr(state, "effects", []) or []),
                "is_video": bool(getattr(state, "is_video", False)),
                "listen": self.people,
                "streaming": bool(runtime.streaming_ready),
                "signature": list(_signature(state)),
            }
        )
        return payload

    async def refresh_people(self, *, force: bool = False) -> None:
        """How many people are in the voice chat — asked rarely, never awaited
        by the loop that draws the clock."""
        now = time.monotonic()
        if not force and now - self._people_at < PEOPLE_EVERY:
            return
        self._people_at = now
        calls = getattr(runtime, "calls", None)
        if calls is None:
            return
        try:
            people = await asyncio.wait_for(calls.get_participants(self.chat_id), timeout=2.5)
            self.people = max(0, len(people or []) - 1)
        except Exception:  # not in a call, or Telegram is slow: keep the last answer
            pass

    # ── fan-out ────────────────────────────────────────────────────────────
    async def broadcast(self, payload: dict) -> None:
        if not self.clients:
            return
        dropped: list[web.WebSocketResponse] = []
        for socket in list(self.clients):
            try:
                await socket.send_json(payload)
            except Exception:
                dropped.append(socket)
        for socket in dropped:
            self.clients.discard(socket)

    async def announce(self, kind: str, **detail: Any) -> None:
        """A thing that just happened, in the vocabulary the app renders."""
        await self.broadcast({"t": "event", "kind": kind, "at": round(time.time(), 3), **detail})

    def _changes(self, previous: tuple | None, current: tuple) -> list[tuple[str, dict]]:
        """Turn a signature difference into events a person would understand."""
        if previous is None or previous == current:
            return []
        out: list[tuple[str, dict]] = []
        old_track, new_track = previous[0], current[0]
        if new_track and new_track != old_track:
            out.append(("skip" if old_track else "start", {"track_id": new_track}))
        if current[3] > previous[3]:
            out.append(("add", {"count": current[3] - previous[3]}))
        elif current[3] < previous[3]:
            out.append(("remove", {"count": previous[3] - current[3]}))
        if current[1] != previous[1]:
            out.append(("pause" if current[1] else "resume", {}))
        if current[2] != previous[2]:
            out.append(("volume", {"volume": current[2]}))
        return out

    async def loop(self) -> None:
        """One ticker per room, shared by every socket in it."""
        try:
            while not self._closed.is_set():
                player = self._player()
                state = player.queues.get(self.chat_id) if player else None
                signature = _signature(state)
                events = self._changes(self.signature, signature)
                state_changed = self.signature != signature
                self.signature = signature

                people_before = self.people
                await self.refresh_people()
                for kind, detail in events:
                    await self.announce(kind, **detail)
                # Somebody walking into the voice chat is a change the app can
                # see, so it is one the app should be told about — but it is not
                # a *player* change, so it is compared separately.
                if state_changed or self.people != people_before:
                    await self.broadcast(self.snapshot(full=True))
                else:
                    await self.broadcast(self.snapshot(full=False))

                playing = bool(getattr(state, "playing", False))
                wait = TICK if playing else IDLE_TICK
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=wait)
                self._wake.clear()
        finally:
            self._closed.set()

    def wake(self) -> None:
        """Ask the ticker to run now instead of at the end of its sleep."""
        self._wake.set()

    def start(self) -> None:
        if self.task is None or self.task.done():
            self._closed.clear()
            self.task = asyncio.create_task(self.loop(), name=f"live:{self.chat_id}")

    async def stop(self) -> None:
        self._closed.set()
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None


class Hub:
    """Every open room in this process."""

    def __init__(self) -> None:
        self.rooms: dict[int, Room] = {}

    def get(self, chat_id: int) -> Room:
        room = self.rooms.get(int(chat_id))
        if room is None:
            room = Room(int(chat_id))
            self.rooms[int(chat_id)] = room
        return room

    def join(self, chat_id: int, socket: web.WebSocketResponse) -> Room:
        room = self.get(chat_id)
        room.clients.add(socket)
        room.start()
        return room

    async def leave(self, chat_id: int, socket: web.WebSocketResponse) -> None:
        room = self.rooms.get(int(chat_id))
        if room is None:
            return
        room.clients.discard(socket)
        if room.clients:
            return
        # Nobody is watching: let the ticker go after a short grace, so a
        # reconnecting phone does not restart it five times a minute.
        await asyncio.sleep(EMPTY_GRACE)
        if not room.clients:
            await room.stop()
            self.rooms.pop(int(chat_id), None)

    async def shutdown(self) -> None:
        for room in list(self.rooms.values()):
            for socket in list(room.clients):
                with contextlib.suppress(Exception):
                    await socket.close(code=1001, message=b"server shutting down")
            await room.stop()
        self.rooms.clear()


HUB = Hub()


async def _caller(request: web.Request) -> WebUser:
    from vyron.web.auth import identify

    return await identify(request, read_body=False)


async def _may_control(client: Any, user: WebUser, chat_id: int) -> bool:
    """Who may drive this room from the app.

    A tap in the Mini App is a remote control for somebody's voice chat, so the
    bar is the same one the bot uses in the chat itself: the owner, an admin, or
    a token that was minted *for this chat* by `/api/room`.
    """
    from vyron.utils.helpers import is_chat_admin, is_owner

    if user.owner or is_owner(user.user_id):
        return True
    if user.chat_id and int(user.chat_id) == int(chat_id):
        return True
    if user.user_id and client is not None:
        return await is_chat_admin(client, chat_id, user.user_id)
    return False


async def _apply(client: Any, chat_id: int, action: str, value: Any) -> tuple[bool, str]:
    """Run one control request against the player. Returns (ok, toast)."""
    player = runtime.player
    if player is None:
        return False, "the player is still starting"
    try:
        if action == "pause":
            return bool(await player.pause(chat_id)), "Paused"
        if action == "resume":
            return bool(await player.resume(chat_id)), "Playing"
        if action == "toggle":
            resolved = await player.toggle(chat_id)
            return bool(resolved), "Playing" if resolved else "Paused"
        if action == "skip":
            track = await player.skip(chat_id)
            return True, f"Playing {track.title}" if track else "Nothing left in the queue"
        if action == "stop":
            await player.stop(chat_id, announce=True)
            return True, "Stopped"
        if action == "seek":
            target = max(0, int(float(value or 0)))
            return bool(await player.seek(chat_id, target)), f"Jumped to {target}s"
        if action == "volume":
            volume = await player.set_volume(chat_id, int(float(value or 100)))
            return True, f"Volume {volume}%"
        if action == "loop":
            state = player.queues.get(chat_id)
            state.loop = state.loop.next()
            await player.persist(chat_id)
            return True, f"Loop {state.loop.label}"
        if action == "shuffle":
            count = player.queues.shuffle(chat_id)
            await player.persist(chat_id)
            return True, f"Shuffled {count} tracks" if count else "Nothing to shuffle"
        if action == "clear":
            cleared = len(player.queues.get(chat_id).queue)
            player.queues.get(chat_id).queue.clear()
            await player.persist(chat_id)
            return True, f"Cleared {cleared} track{'s' if cleared != 1 else ''}"
        if action in {"autoplay", "effects"}:
            state = player.queues.get(chat_id)
            if action == "autoplay":
                state.autoplay = not state.autoplay
                state.autoplay_set = True
                await player.persist(chat_id)
                return True, "Radio on" if state.autoplay else "Radio off"
            effect = str(value or "").strip()
            if not effect:
                return False, "Which effect?"
            if effect in state.effects:
                state.effects.remove(effect)
                toast = f"{effect} off"
            else:
                state.effects.append(effect)
                toast = f"{effect} on"
            await player.persist(chat_id)
            return True, toast
    except Exception as exc:  # a control that fails must not drop the socket
        logger.info("live control %s failed in %s: %s", action, chat_id, exc)
        return False, "That did not work"
    return False, "Unknown action"


async def live_socket(request: web.Request) -> web.WebSocketResponse:
    """`/ws/room?chat_id=…` — the live channel for one voice chat."""
    user = await _caller(request)
    from vyron.config import settings

    if not (user.authenticated or user.owner or settings.webapp_allow_anon):
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    raw = request.query.get("chat_id") or request.query.get("chat") or ""
    try:
        chat_id = int(raw)
    except (TypeError, ValueError):
        # Fall back to the chat the token is scoped to — a Mini App opened from
        # a group link carries exactly one, and asking for it again is noise.
        chat_id = int(user.chat_id or 0)
    if not chat_id:
        return web.json_response(
            {"ok": False, "error": "chat_id is required"}, status=400
        )

    socket = web.WebSocketResponse(heartbeat=30, max_msg_size=MAX_MESSAGE)
    await socket.prepare(request)
    client = getattr(runtime, "bot", None)
    can_control = await _may_control(client, user, chat_id)
    room = HUB.join(chat_id, socket)

    await room.refresh_people(force=True)
    hello = room.snapshot(full=True)
    hello.update(
        {
            "t": "hello",
            "you": {
                "id": user.user_id,
                "name": user.name or "You",
                "can_control": can_control,
            },
        }
    )
    await socket.send_json(hello)

    try:
        async for message in socket:
            if message.type == WSMsgType.TEXT:
                try:
                    payload = message.json()
                except Exception:
                    continue
                if not isinstance(payload, dict):
                    continue
                kind = payload.get("t")
                if kind == "ping":
                    await socket.send_json(
                        {
                            "t": "pong",
                            "id": payload.get("id"),
                            "server_time": round(time.time(), 3),
                        }
                    )
                    continue
                if kind == "control":
                    action = str(payload.get("action") or "")
                    if not can_control:
                        await socket.send_json(
                            {"t": "denied", "action": action, "reason": "admins only"}
                        )
                        continue
                    ok, toast = await _apply(client, chat_id, action, payload.get("value"))
                    await socket.send_json({"t": "ack", "action": action, "ok": ok, "toast": toast})
                    # The room's own ticker sends the new state to everybody,
                    # including this socket — one authority, one message.
                    # Nudge it so a tap feels immediate instead of waiting out
                    # the current second.
                    room.wake()
                    continue
            elif message.type == WSMsgType.ERROR:
                logger.debug("live socket error in %s: %s", chat_id, socket.exception())
                break
    except Exception as exc:  # pragma: no cover - transport level
        logger.debug("live socket for %s ended: %s", chat_id, exc)
    finally:
        _later(HUB.leave(chat_id, socket), f"live:leave:{chat_id}")
    return socket


def register(app: web.Application) -> None:
    app.router.add_get("/ws/room", live_socket)


__all__ = ["HUB", "Hub", "Room", "live_socket", "register"]
