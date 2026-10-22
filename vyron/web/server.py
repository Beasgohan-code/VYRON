# ---------------------------------------------------------------------------
#  VYRON — web app API
#
#  A small JSON surface over the same Player the bot uses, so the Mini App and
#  the chat never disagree about state.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from pyrogram.enums import ChatType

from vyron.config import settings
from vyron.core.queue import LoopMode, Track
from vyron.runtime import runtime
from vyron.web.auth import WebUser, make_token, resolve_user

logger = logging.getLogger(__name__)

WEB_DIR = Path(getattr(settings, "webapp_dir", Path(__file__).resolve().parent.parent.parent / "webapp"))


DEMO_STATE = {
    "version": "preview",
    "streaming": True,
    "user": {"id": 0, "name": "Preview", "username": ""},
    "chat": {"id": 0, "title": "VYRON Preview", "is_group": False},
    "now": {
        "title": "Midnight Drive",
        "uploader": "VYRON Demo",
        "duration": 212,
        "elapsed": 74.0,
        "progress": 0.35,
        "paused": False,
        "volume": 100,
        "loop": "off",
        "source": "youtube",
        "requested_by": "you",
        "thumbnail": "",
        "url": "",
    },
    "queue": [
        {"index": 1, "title": "Neon Skyline", "uploader": "VYRON Demo", "duration": 198, "thumbnail": ""},
        {"index": 2, "title": "Slow Motion", "uploader": "VYRON Demo", "duration": 241, "thumbnail": ""},
        {"index": 3, "title": "Afterglow", "uploader": "VYRON Demo", "duration": 167, "thumbnail": ""},
    ],
    "settings": {"volume": 100, "loop": "off", "autoplay": True, "always_on": False, "shuffle": False},
    "favorites": [{"id": "demo", "title": "Saved track", "uploader": "VYRON Demo", "duration": 180}],
}


# ── helpers ─────────────────────────────────────────────────────────────────
def _track_json(track: Track | None, *, index: int | None = None) -> dict | None:
    if track is None:
        return None
    payload = {
        "id": track.id,
        "title": track.title,
        "uploader": track.uploader,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "source": track.source,
        "requested_by": track.requested_name,
        "video": track.is_video,
        "url": track.watch_url,
    }
    if index is not None:
        payload["index"] = index
    return payload


async def _read_json(request: web.Request) -> dict:
    try:
        payload = await request.json()
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


async def _identify(request: web.Request) -> WebUser:
    body = await _read_json(request) if request.method == "POST" else {}
    init_data = (
        request.headers.get("X-Init-Data")
        or body.get("init_data")
        or request.query.get("init_data", "")
    )
    token = request.headers.get("X-Vyron-Token") or body.get("token") or request.query.get("t", "")
    return resolve_user(
        init_data=init_data or "",
        token=token or "",
        bot_token=settings.bot_token,
        allow_anon=settings.webapp_allow_anon,
    )


def _guard(user: WebUser) -> web.Response | None:
    if user.authenticated or settings.webapp_allow_anon:
        return None
    return web.json_response(
        {"ok": False, "error": "unauthorized", "hint": "open the app from Telegram"},
        status=401,
    )


async def _is_admin(chat_id: int, user_id: int) -> bool:
    if not runtime.bot or not user_id:
        return False
    if user_id in settings.owners:
        return True
    try:
        member = await runtime.bot.get_chat_member(chat_id, user_id)
        return member.status.name in {"ADMINISTRATOR", "OWNER"}
    except Exception:
        return True  # private chat / unknown → the player still guards itself


# ── routes ──────────────────────────────────────────────────────────────────
async def index(_: web.Request) -> web.StreamResponse:
    page = WEB_DIR / "index.html"
    if not page.is_file():
        return web.Response(status=404, text="web app not installed")
    return web.FileResponse(page)


async def state(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _guard(user)
    if denied:
        return denied

    player = runtime.player
    if user.source == "anon" and player is None:
        return web.json_response(
            {"ok": True, "preview": True, **DEMO_STATE}
        )
    chat_id = user.chat_id or user.user_id
    state_obj = player.queues.get(chat_id) if player else None
    current = state_obj.current if state_obj else None

    now = _track_json(current)
    if now and state_obj:
        now["elapsed"] = round(state_obj.elapsed(), 1)
        now["paused"] = state_obj.paused
        now["volume"] = state_obj.volume
        now["loop"] = state_obj.loop.value
        now["progress"] = (
            round(min(1.0, state_obj.elapsed() / current.duration), 4)
            if current.duration
            else 0
        )

    chat_title = ""
    if runtime.bot and user.chat_id:
        try:
            chat = await runtime.bot.get_chat(user.chat_id)
            chat_title = chat.title or chat.first_name or ""
        except Exception:
            chat_title = ""

    return web.json_response(
        {
            "ok": True,
            "version": runtime.version,
            "streaming": runtime.streaming_ready,
            "user": {"id": user.user_id, "name": user.name, "username": user.username},
            "chat": {"id": chat_id, "title": chat_title, "is_group": bool(user.chat_id) and chat_id < 0},
            "now": now,
            "queue": [
                _track_json(track, index=index + 1)
                for index, track in enumerate(state_obj.queue if state_obj else [])
            ],
            "settings": {
                "volume": state_obj.volume if state_obj else settings.default_volume,
                "loop": state_obj.loop.value if state_obj else "off",
                "autoplay": state_obj.autoplay if state_obj else settings.autoplay_default,
                "always_on": state_obj.always_on if state_obj else False,
                "shuffle": state_obj.shuffle if state_obj else False,
            },
            "favorites": [
                _track_json(Track.from_dict(item))
                for item in (await runtime.storage.favorites(user.user_id, 10) if runtime.storage else [])
            ],
        }
    )


async def action(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _guard(user)
    if denied:
        return denied

    body = await _read_json(request)
    name = str(body.get("action") or "")
    value = body.get("value")
    chat_id = user.chat_id or user.user_id
    player = runtime.player
    if player is None:
        return web.json_response({"ok": False, "error": "player not ready"}, status=503)

    state_obj = player.queues.get(chat_id)

    def ok(**extra) -> web.Response:
        return web.json_response({"ok": True, **extra})

    try:
        if name == "play":
            query = str(value or "").strip()
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            track = await runtime.youtube.resolve(
                query, requester=(user.user_id, user.name or "")
            )
            position = await player.enqueue(chat_id, track, play_now=True)
            return ok(position=position, track=_track_json(track))

        if name == "pause":
            return ok(changed=await player.pause(chat_id))
        if name == "resume":
            return ok(changed=await player.resume(chat_id))
        if name == "toggle":
            return ok(changed=await player.toggle(chat_id))
        if name == "skip":
            track = await player.skip(chat_id, count=int(value or 1))
            return ok(track=_track_json(track))
        if name == "stop":
            await player.stop(chat_id, leave=True)
            return ok()
        if name == "seek":
            return ok(changed=await player.seek(chat_id, int(float(value or 0))))
        if name == "volume":
            return ok(volume=await player.set_volume(chat_id, int(float(value or 100))))
        if name == "loop":
            state_obj.loop = LoopMode.parse(value)
            await player.persist(chat_id)
            return ok(loop=state_obj.loop.value)
        if name == "shuffle":
            return ok(shuffled=player.queues.shuffle(chat_id))
        if name == "clear":
            return ok(removed=player.queues.clear(chat_id))
        if name == "remove":
            track = player.queues.remove(chat_id, int(value or 0))
            return ok(track=_track_json(track))
        if name == "move":
            pair = value if isinstance(value, dict) else {}
            moved = player.queues.move(chat_id, int(pair.get("from", 0)), int(pair.get("to", 0)))
            return ok(moved=moved)
        if name == "jump":
            track = await player.jump(chat_id, int(value or 0))
            return ok(track=_track_json(track))
        if name == "autoplay":
            state_obj.autoplay = not state_obj.autoplay
            await player.persist(chat_id)
            return ok(autoplay=state_obj.autoplay)
        if name == "always":
            state_obj.always_on = not state_obj.always_on
            await player.persist(chat_id)
            return ok(always_on=state_obj.always_on)
        if name == "favorite":
            if not state_obj.current or runtime.storage is None:
                return ok(saved=False)
            saved = await runtime.storage.add_favorite(
                user.user_id, state_obj.current.to_dict()
            )
            return ok(saved=saved)
        if name == "search":
            query = str(value or "").strip()
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            results = await runtime.youtube.search(
                query, limit=6, requester=(user.user_id, user.name or "")
            )
            return ok(
                results=[
                    {**_track_json(track), "index": index}
                    for index, track in enumerate(results)
                ]
            )
        if name == "play_index":
            return web.json_response(
                {"ok": False, "error": "use action=play with a query"}, status=400
            )
    except Exception as exc:
        logger.warning("web action %s failed: %s", name, exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    return web.json_response({"ok": False, "error": f"unknown action {name!r}"}, status=400)


async def info(_: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "name": settings.webapp_title,
            "bot": settings.bot_username,
            "version": runtime.version,
            "auth_required": not settings.webapp_allow_anon,
        }
    )


async def authenticate(request: web.Request) -> web.Response:
    """Exchange Telegram initData for a chat-scoped token (used by /app links)."""
    user = await _identify(request)
    denied = _guard(user)
    if denied:
        return denied
    token = make_token(user.chat_id or user.user_id, user.user_id, settings.bot_token)
    return web.json_response({"ok": True, "token": token, "chat_id": user.chat_id or user.user_id})


def chat_link(chat_id: int, user_id: int) -> str:
    """Public Mini App URL for a chat (used by the /app command)."""
    if not settings.webapp_url:
        return ""
    token = make_token(chat_id, user_id, settings.bot_token)
    return f"{settings.webapp_url}/app/?t={token}"


def register(app: web.Application) -> None:
    """Attach the Mini App routes to an existing aiohttp application."""
    if not settings.webapp:
        return
    static_dir = WEB_DIR
    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if static_dir.is_dir():
        app.router.add_static("/app/static", static_dir, show_index=False)
    app.router.add_get("/api/info", info)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/state", state)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/auth", authenticate)
    logger.info("web app mounted from %s", static_dir)


__all__ = ["WEB_DIR", "chat_link", "register"]
