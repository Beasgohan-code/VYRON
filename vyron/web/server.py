# ---------------------------------------------------------------------------
#  VYRON — web app API
#
#  JSON surface over the same Player the bot uses.  The UI is a React + Vite
#  app in `frontend/`; `npm run build` writes it to `webapp/dist`, which is what
#  this module serves.  Views: Home · Search · Library · Queue · Playlists ·
#  Rooms · Profile.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from aiohttp import web

from vyron.config import settings
from vyron.core import playlists as pl
from vyron.core.journal import journal
from vyron.core.lyrics import parse_lrc
from vyron.core.queue import LoopMode, Track
from vyron.runtime import runtime
from vyron.core.musicapi import (
    MAX_KEYS_PER_OWNER,
    API_VERSION,
    find_key,
    get_music_api,
    mask_key,
)
from vyron.web import stream as audio
from vyron.web.auth import WebUser, make_token, resolve_user, verify_owner_token

logger = logging.getLogger(__name__)

_LYRICS_CACHE: dict[str, tuple[float, dict]] = {}
# Telegram round-trips are the slowest thing on a small host: a chat title does
# not change often enough to fetch on every state request.
_TITLE_CACHE: dict[int, tuple[float, str]] = {}
_PLAYLIST_CACHE: dict[int, tuple[float, list[dict]]] = {}

_WEBAPP_ROOT = Path(
    getattr(settings, "webapp_dir", Path(__file__).resolve().parent.parent.parent / "webapp")
)
# `webapp/dist` is the compiled SPA; fall back to the folder itself so a custom
# or hand-written build (WEBAPP_DIR=…) keeps working.
WEB_DIR = _WEBAPP_ROOT / "dist" if (_WEBAPP_ROOT / "dist" / "index.html").is_file() else _WEBAPP_ROOT


def _track_json(track: Track | None, *, index: int | None = None) -> dict | None:
    if track is None:
        return None
    audio.remember(track)
    payload = {
        "id": track.id,
        "title": track.title,
        "uploader": track.uploader,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "source": track.source,
        "requested_by": track.requested_name,
        "views": track.views,
        "video": track.is_video,
        "url": track.watch_url,
        "query": f"{track.title} {track.uploader}".strip(),
        "stream": f"/api/stream/{track.id}",
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

    # Owner access: `X-Owner-Token`, `?ot=` (or a `vown_` link token) works
    # from any browser — no Telegram initData required.
    owner_raw = (
        request.headers.get("X-Owner-Token")
        or body.get("owner_token")
        or request.query.get("ot", "")
        or (token if token.startswith("vown_") else "")
    ).strip()
    if owner_raw:
        provisional = verify_owner_token(owner_raw, settings.bot_token)
        if provisional is not None and provisional.user_id in settings.owners:
            from vyron.core import tokens

            if await tokens.accepts(provisional.user_id, provisional.epoch):
                return provisional

    # A `vown_` token can also arrive as `?t=` / `X-Vyron-Token` (older links).
    # It follows the same generation rule as the header, so a revoked token
    # cannot sneak back in through the other door.
    owner_epoch = None
    if token.startswith("vown_"):
        from vyron.core import tokens

        provisional = verify_owner_token(token, settings.bot_token)
        if provisional is not None:
            owner_epoch = await tokens.epoch(provisional.user_id)

    return resolve_user(
        init_data=init_data or "",
        token=token or "",
        bot_token=settings.bot_token,
        allow_anon=settings.webapp_allow_anon,
        owner_ids=settings.owners,
        owner_epoch=owner_epoch,
    )


_EMPTY_HOME = {
    "hero": {
        "headline": "Music hits different here.",
        "subline": "Search for a song, or start playback from the bot's voice chat.",
        "cover": "",
    },
    "trending": [],
    "shelves": [],
    "moods": [],
}


def _denied(user: WebUser) -> web.Response | None:
    if user.authenticated or user.owner or settings.webapp_allow_anon:
        return None
    return web.json_response(
        {"ok": False, "error": "unauthorized", "hint": "open the app from Telegram"},
        status=401,
    )


def _is_owner(user: WebUser) -> bool:
    return bool(getattr(user, "owner", False) or (user.user_id and user.user_id in settings.owners))


def _chat_id(user: WebUser) -> int:
    return user.chat_id or user.user_id


async def _none(value=None):
    return value


async def _chat_title(chat_id: int) -> str:
    """Chat title with a 10-minute cache and a hard timeout."""
    cached = _TITLE_CACHE.get(chat_id)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    if runtime.bot is None:
        return ""
    try:
        chat = await asyncio.wait_for(runtime.bot.get_chat(chat_id), timeout=3)
        title = chat.title or chat.first_name or ""
    except Exception:
        return cached[1] if cached else ""
    _TITLE_CACHE[chat_id] = (time.time(), title)
    return title


# ── static shell ────────────────────────────────────────────────────────────
async def index(_: web.Request) -> web.StreamResponse:
    page = WEB_DIR / "index.html"
    if not page.is_file():
        return web.Response(
            status=404,
            text=(
                "web app not built — run `npm install && npm run build` in frontend/ "
                "(output goes to webapp/dist)"
            ),
        )
    response = web.FileResponse(page)
    # never cache the shell: asset filenames are content-hashed by Vite
    response.headers["Cache-Control"] = "no-cache"
    # The app is opened with ?t=<token>. Keep that out of Referer headers and
    # stop browsers from guessing content types.
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


# ── state ───────────────────────────────────────────────────────────────────
async def state(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    player = runtime.player
    chat_id = _chat_id(user)
    state_obj = player.queues.get(chat_id) if player else None
    current = state_obj.current if state_obj else None

    now = _track_json(current)
    if now and state_obj:
        elapsed = state_obj.elapsed()
        now.update(
            elapsed=round(elapsed, 1),
            paused=state_obj.paused,
            volume=state_obj.volume,
            loop=state_obj.loop.value,
            progress=(
                round(min(1.0, elapsed / current.duration), 4) if current.duration else 0
            ),
        )

    chat_title, favorites, history, playlist_rows, counters = await asyncio.gather(
        _chat_title(user.chat_id) if user.chat_id else _none(),
        runtime.storage.favorites(user.user_id, 50) if runtime.storage else _none([]),
        runtime.storage.history(user.user_id, 20) if runtime.storage else _none([]),
        pl.list_playlists(user.user_id),
        runtime.storage.counters() if runtime.storage else _none({}),
    )
    playlists = [pl.summary(entry) for entry in playlist_rows]

    return web.json_response(
        {
            "ok": True,
            "version": runtime.version,
            "bot": settings.bot_username,
            "streaming": runtime.streaming_ready,
            "user": {
                "id": user.user_id,
                "name": user.name,
                "username": user.username,
                "owner": _is_owner(user),
                "access": user.source,
            },
            "owner": _is_owner(user),
            "chat": {
                "id": chat_id,
                "title": chat_title,
                "is_group": bool(user.chat_id) and chat_id < 0,
            },
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
                "effects": state_obj.effects if state_obj else [],
            },
            "favorites": [
                {**_track_json(Track.from_dict(item))} for item in favorites
            ],
            "history": [{**_track_json(Track.from_dict(item))} for item in history],
            "playlists": playlists,
            "stats": {
                "tracks": counters.get("tracks", 0),
                "downloads": counters.get("downloads", 0),
                "chats": len(await runtime.storage.all_chat_ids()) if runtime.storage else 0,
            },
        }
    )


_OFFLINE_HINTS = (
    "getaddrinfo",
    "urlopen error",
    "connection refused",
    "connection reset",
    "timed out",
    "timeout",
    "ssl",
    "temporary failure in name resolution",
    "network is unreachable",
    "eof occurred",
    "proxy",
)


def _looks_offline(message: str) -> bool:
    """True when the failure is the network, not the query.

    The difference matters to the listener: "no results" means try a different
    search, "unreachable" means this host cannot talk to YouTube at all.
    """
    lowered = message.lower()
    return any(hint in lowered for hint in _OFFLINE_HINTS)


# ── home / discovery ────────────────────────────────────────────────────────
async def home(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    if runtime.charts is None:
        await _engine()      # a wake-up request should wait, not show an empty home
    if runtime.charts is None:
        return web.json_response({"ok": True, "ready": False, **_EMPTY_HOME})

    payload = await runtime.charts.home()
    return web.json_response({"ok": True, **payload})


async def _engine() -> bool:
    """True once the search engine exists — waiting out a cold start if needed.

    The port opens before boot finishes (a host that never sees the port
    assumes the deploy failed), so the first request after a wake-up can land
    while yt-dlp is still coming up. Waiting a few seconds is a better answer
    than a 503, and the wait is bounded.
    """
    if runtime.youtube is not None:
        return True
    return await runtime.wait_ready(getattr(settings, "boot_wait", 15.0))


async def search(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    body = await _read_json(request)
    query = str(body.get("query") or request.query.get("q") or "").strip()
    if not query:
        return web.json_response({"ok": True, "results": []})
    if not await _engine() or runtime.youtube is None:
        return web.json_response(
            {
                "ok": False,
                "ready": False,
                "error": "search is still starting",
                "hint": "the deployment is booting — retry in a few seconds",
            },
            status=503,
            headers={"Retry-After": "5"},
        )
    limit = min(20, max(4, int(body.get("limit") or 10)))
    try:
        tracks = await runtime.youtube.search(
            query, limit=limit, requester=(user.user_id, user.name or "")
        )
    except Exception as exc:
        message = str(exc) or "search failed"
        if _looks_offline(message):
            return web.json_response(
                {
                    "ok": False,
                    "error": "youtube_unreachable",
                    "reason": message[:160],
                    "hint": "this host cannot reach YouTube — set PROXY, or COOKIES_FILE, and retry",
                },
                status=502,
            )
        return web.json_response({"ok": False, "error": message}, status=400)
    return web.json_response(
        {"ok": True, "query": query, "results": [_track_json(track, index=i) for i, track in enumerate(tracks, 1)]}
    )


async def lyrics(request: web.Request) -> web.Response:
    """Lyrics for the in-app player. LRCLIB, cached in memory for a while."""
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    body = await _read_json(request)
    title = str(body.get("title") or request.query.get("title") or "").strip()
    artist = str(body.get("artist") or request.query.get("artist") or "").strip()
    duration = int(float(body.get("duration") or request.query.get("duration") or 0))
    if not title:
        return web.json_response({"ok": False, "error": "title is required"}, status=400)

    key = f"{title.lower()}|{artist.lower()}|{duration // 30}"
    cached = _LYRICS_CACHE.get(key)
    if cached and cached[0] > time.time():
        return web.json_response({"ok": True, **cached[1], "cached": True})

    client = runtime.lyrics
    if client is None:
        return web.json_response({"ok": False, "error": "lyrics service not ready"}, status=503)
    try:
        result = await client.timed(title, artist, duration) if duration else await client.find(title, artist)
    except Exception as exc:
        logger.debug("lyrics lookup failed: %s", exc)
        result = None
    if result is None:
        return web.json_response({"ok": False, "error": "no lyrics found"}, status=404)

    payload = {
        "title": title,
        "artist": artist,
        "text": result.as_text(),
        "synced": bool(result.has_sync),
        "lines": parse_lrc(result.synced),
    }
    _LYRICS_CACHE[key] = (time.time() + 3600, payload)
    if len(_LYRICS_CACHE) > 200:
        for stale in list(_LYRICS_CACHE)[:50]:
            _LYRICS_CACHE.pop(stale, None)
    return web.json_response({"ok": True, **payload})


def _quota_limits(body: dict) -> dict[str, int]:
    """The rolling caps a request asked for (daily/monthly requests or bytes)."""
    from vyron.core.musicapi import QUOTA_FIELDS

    out: dict[str, int] = {}
    for name in QUOTA_FIELDS:
        raw = body.get(name)
        if raw in (None, ""):
            continue
        text = str(raw).lstrip("-")
        if text.isdigit():
            out[name] = int(raw)
    return out


async def api_keys(request: web.Request) -> web.Response:
    """Music-API console for the Mini App (initData auth).

    GET  → base URL, docs links, the caller's keys and aggregate stats.
    POST → {action: create|revoke|rotate, ...} with scopes/days/rate_limit.
    """
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied

    api = get_music_api()
    base = settings.api_base or _public_base(request)
    docs = f"{base}/v1/docs" if base else "/v1/docs"
    meta = {
        "scopes": ["read", "search", "download", "admin"],
        "default_scopes": ["read", "search", "download"],
        "version": API_VERSION,
    }

    is_owner = _is_owner(user)

    async def listing() -> list[dict]:
        rows = await api.keys(
            None if is_owner else user.user_id, reveal=False, include_revoked=is_owner
        )
        for row in rows:
            row["quota"] = api.quota(row)
        return rows

    async def payload(*extra: dict) -> web.Response:
        from vyron.api.metrics import METRICS
        from vyron.core import sources as registry

        body = {
            "ok": True,
            "base": base,
            "docs": docs,
            "openapi": f"{base}/v1/openapi.json" if base else "/v1/openapi.json",
            "is_owner": is_owner,
            "keys": await listing(),
            "sources": [dict(row) for row in registry.status()],
            "source_order": registry.describe(),
            "stats": await api.stats(),
            "metrics": METRICS.snapshot(),
            "limits": {"max_keys": MAX_KEYS_PER_OWNER},
            **meta,
        }
        for item in extra:
            body.update(item)
        return web.json_response(body)

    if request.method == "GET":
        return await payload()

    body = await _read_json(request)
    action = str(body.get("action") or "create")

    if action in {"create", "rotate"} and not is_owner:
        # Minting is the owner's call: the webapp is reachable by any Telegram
        # user, and a key is a download allowance on the owner's server.
        return web.json_response(
            {"ok": False, "error": "only the bot owner can create or rotate keys"}, status=403
        )

    if action == "create":
        scopes = body.get("scopes")
        if isinstance(scopes, str):
            scopes = [chunk for chunk in scopes.replace(";", ",").split(",") if chunk.strip()]
        days = body.get("days")
        rate_limit = body.get("rate_limit")
        record, error = await api.issue(
            user.user_id,
            str(body.get("label") or "web")[:40],
            scopes=scopes,
            days=int(days) if str(days or "").isdigit() else None,
            rate_limit=int(rate_limit) if str(rate_limit or "").isdigit() else None,
            by=user.user_id,
            limits=_quota_limits(body),
        )
        if record is None:
            return web.json_response({"ok": False, "error": error or "could not create key"}, status=400)
        logger.info("music api key issued to %s (%s)", user.user_id, record.get("label"))
        return await payload({"created": {**record, "masked": mask_key(str(record["key"]))}})

    identifier = str(body.get("id") or body.get("key") or body.get("prefix") or "").strip()
    if not identifier:
        return web.json_response({"ok": False, "error": "id is required"}, status=400)
    visible = await api.keys(None if is_owner else user.user_id, reveal=False)
    if not find_key(visible, identifier):
        return web.json_response({"ok": False, "error": "key not found"}, status=404)

    if action == "revoke":
        revoked = await api.revoke(
            None if is_owner else user.user_id, identifier, force=is_owner, by=user.user_id
        )
        if not revoked:
            return web.json_response({"ok": False, "error": "key not found"}, status=404)
        return await payload({"revoked": True})

    if action == "rotate":
        match = find_key(visible, identifier) or {}
        record, error = await api.rotate(
            int(match.get("owner_id") or user.user_id), str(match.get("id")), by=user.user_id
        )
        if record is None:
            return web.json_response({"ok": False, "error": error or "could not rotate"}, status=400)
        return await payload({"created": {**record, "masked": mask_key(str(record["key"]))}})

    if action == "update":
        days = body.get("days", body.get("expires_in_days"))
        scopes = body.get("scopes") if is_owner else None
        rate_limit = body.get("rate_limit") if is_owner else None
        record, error = await api.update_key(
            None if is_owner else user.user_id,
            identifier,
            label=body.get("label"),
            scopes=scopes,
            days=int(days) if str(days).lstrip("-").isdigit() else None,
            rate_limit=(
                int(rate_limit) if str(rate_limit).lstrip("-").isdigit() else None
            ),
            force=is_owner,
            by=user.user_id,
            limits=_quota_limits(body),
        )
        if record is None:
            return web.json_response({"ok": False, "error": error or "could not update"}, status=400)
        return await payload({"updated": True})

    return web.json_response({"ok": False, "error": f"unknown action {action!r}"}, status=400)


def _public_base(request: web.Request) -> str:
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}"


async def mix(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    key = request.query.get("key", "")
    if runtime.charts is None:
        await _engine()
    if runtime.charts is None:
        return web.json_response({"ok": True, "ready": False, "tracks": []})
    tracks = await runtime.charts.mix(key, limit=25)
    if not tracks:
        tracks = await runtime.charts.mood(key, limit=25)
    return web.json_response(
        {"ok": True, "key": key, "tracks": [_track_json(t, index=i) for i, t in enumerate(tracks, 1)]}
    )


# ── rooms (listen together) ─────────────────────────────────────────────────
async def room_attach(request: web.Request) -> web.Response:
    """Mint a chat-scoped token for a room the caller administers.

    Telegram only allows `web_app` buttons in private chats, so a group entry
    point sends people to the DM. This keeps the *group* controllable from the
    app once they are there — without ever printing a URL with a token in it.
    """
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied

    body = await _read_json(request)
    try:
        chat_id = int(body.get("chat_id") or 0)
    except (TypeError, ValueError):
        chat_id = 0
    if chat_id >= 0:
        return web.json_response({"ok": False, "error": "not a group chat"}, status=400)
    if runtime.bot is None or not settings.bot_token:
        return web.json_response({"ok": False, "error": "the bot is not ready yet"}, status=503)

    from vyron.utils.helpers import is_chat_admin

    if not await is_chat_admin(runtime.bot, chat_id, user.user_id):
        return web.json_response(
            {"ok": False, "error": "only an admin of that chat can control it"}, status=403
        )

    logger.info("webapp: %s attached to chat %s", user.user_id, chat_id)
    return web.json_response(
        {
            "ok": True,
            "chat_id": chat_id,
            "token": make_token(chat_id, user.user_id, settings.bot_token),
        }
    )


async def rooms(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    if runtime.player is None:
        return web.json_response({"ok": True, "ready": False, "rooms": []})

    entries = []
    for chat_id in runtime.player.active_chats():
        state_obj = runtime.player.queues.get(chat_id)
        title = f"Chat {chat_id}"
        username = ""
        try:
            chat = await runtime.bot.get_chat(chat_id)
            title = chat.title or chat.first_name or title
            username = chat.username or ""
        except Exception:
            pass
        listeners = 0
        try:
            participants = await runtime.calls.get_participants(chat_id)
            listeners = max(0, len(participants or []) - 1)
        except Exception:
            listeners = 0
        entries.append(
            {
                "chat_id": chat_id,
                "title": title,
                "username": username,
                "listeners": listeners,
                "playing": bool(state_obj and state_obj.playing),
                "paused": bool(state_obj and state_obj.paused),
                "track": _track_json(state_obj.current) if state_obj else None,
                "volume": state_obj.volume if state_obj else 100,
                "effects": state_obj.effects if state_obj else [],
            }
        )
    return web.json_response({"ok": True, "rooms": entries})


# ── playlists ───────────────────────────────────────────────────────────────
async def playlists_route(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    if not user.authenticated:
        return web.json_response({"ok": True, "playlists": []})
    cached = _PLAYLIST_CACHE.get(user.user_id)
    if cached is None or time.time() - cached[0] > 20:
        cached = (
            time.time(),
            [pl.summary(entry) for entry in await pl.list_playlists(user.user_id)],
        )
        _PLAYLIST_CACHE[user.user_id] = cached
    return web.json_response({"ok": True, "playlists": cached[1], "cached": True})


# ── actions ─────────────────────────────────────────────────────────────────
# Background jobs started by the web app (downloads) — kept referenced so they
# are not garbage-collected mid-flight.
_TASKS: set[asyncio.Task] = set()

# Every action /api/action understands.  Unknown names are rejected before the
# player guard so a stale frontend gets a useful 400 instead of a 503.
KNOWN_ACTIONS = frozenset(
    {
        "play", "play_now", "play_next", "pause", "resume", "toggle", "skip",
        "stop", "seek", "volume", "loop", "shuffle", "clear", "remove", "move",
        "jump", "autoplay", "always", "effects", "favorite", "unfavorite",
        "favorite_track", "playlist_create", "playlist_delete", "playlist_add",
        "playlist_remove", "playlist_play", "search", "download",
    }
)

# Actions that work without an active voice-chat player.
PLAYERLESS_ACTIONS = frozenset(
    {
        "playlist_create", "playlist_delete", "playlist_add", "playlist_remove",
        "favorite_track", "unfavorite", "search",
    }
)


async def _mirror_now_playing(user: WebUser, chat_id: int) -> None:
    """Echo Mini App playback into the listener's DM.

    Starting a song from the web app used to be silent on the phone. Now the
    same poster the bot would post in the chat is mirrored to the person who
    tapped play — so "I pressed play in the app" also shows up in Telegram.
    """
    if not settings.np_dm:
        return
    bot = getattr(runtime, "bot", None)
    player = runtime.player
    if bot is None or player is None or not user.user_id:
        return
    if int(user.user_id) == int(chat_id):
        return  # already a DM with the bot: the card is right there
    state = player.queues.get(chat_id)
    if state is None or state.current is None:
        return
    title = ""
    try:
        chat = await bot.get_chat(chat_id)
        title = getattr(chat, "title", "") or ""
    except Exception:  # pragma: no cover - cosmetic
        title = ""
    from vyron.ui import nowplaying

    await nowplaying.mirror_to_dm(bot, user.user_id, state, chat_title=title)


async def action(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied

    body = await _read_json(request)
    name = str(body.get("action") or "")
    value = body.get("value")
    chat_id = _chat_id(user)

    if not user.authenticated:
        return web.json_response(
            {"ok": False, "error": "open the app from Telegram to control playback"},
            status=401,
        )

    if name not in KNOWN_ACTIONS:
        return web.json_response(
            {"ok": False, "error": f"unknown action {name!r}", "actions": sorted(KNOWN_ACTIONS)},
            status=400,
        )

    player = runtime.player
    if player is None and name not in PLAYERLESS_ACTIONS:
        return web.json_response({"ok": False, "error": "player not ready"}, status=503)
    state_obj = player.queues.get(chat_id) if player else None

    def ok(**extra) -> web.Response:
        return web.json_response({"ok": True, **extra})

    try:
        # ── playback ──────────────────────────────────────────────────────
        if name == "play":
            query = str(value or "").strip()
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            track = await runtime.youtube.resolve(query, requester=(user.user_id, user.name or ""))
            position = await player.enqueue(chat_id, track, play_now=True)
            await _mirror_now_playing(user, chat_id)
            return ok(position=position, track=_track_json(track))

        if name in {"play_now", "play_next"}:
            query = str(value or "").strip()
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            track = await runtime.youtube.resolve(query, requester=(user.user_id, user.name or ""))
            if name == "play_now":
                await player.play_track(chat_id, track)
                await _mirror_now_playing(user, chat_id)
                return ok(track=_track_json(track))
            await player.enqueue(chat_id, track, index=0)
            return ok(track=_track_json(track))

        if name == "pause":
            return ok(changed=await player.pause(chat_id))
        if name == "resume":
            return ok(changed=await player.resume(chat_id))
        if name == "toggle":
            return ok(changed=await player.toggle(chat_id))
        if name == "skip":
            track = await player.skip(chat_id, count=int(value or 1))
            await _mirror_now_playing(user, chat_id)
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
            return ok(moved=player.queues.move(chat_id, int(pair.get("from", 0)), int(pair.get("to", 0))))
        if name == "jump":
            track = await player.jump(chat_id, int(value or 0))
            await _mirror_now_playing(user, chat_id)
            return ok(track=_track_json(track))
        if name == "autoplay":
            state_obj.autoplay = not state_obj.autoplay
            await player.persist(chat_id)
            return ok(autoplay=state_obj.autoplay)
        if name == "always":
            state_obj.always_on = not state_obj.always_on
            await player.persist(chat_id)
            return ok(always_on=state_obj.always_on)
        if name == "effects":
            from vyron.core import chatcfg, effects as audio_fx

            active = audio_fx.resolve(value if isinstance(value, list) else [])
            await chatcfg.set(chat_id, "effects", active)
            state_obj.effects = active
            return ok(effects=active, labels=audio_fx.labels(active))

        # ── library ───────────────────────────────────────────────────────
        if name == "favorite":
            if not state_obj.current or runtime.storage is None:
                return ok(saved=False)
            saved = await runtime.storage.add_favorite(user.user_id, state_obj.current.to_dict())
            return ok(saved=saved)
        if name == "unfavorite":
            media_id = str(value or "")
            removed = await runtime.storage.remove_favorite(user.user_id, media_id)
            return ok(removed=removed)
        if name == "favorite_track":
            payload = value if isinstance(value, dict) else {}
            if runtime.storage is None or not payload.get("id"):
                return ok(saved=False)
            saved = await runtime.storage.add_favorite(user.user_id, payload)
            return ok(saved=saved)

        # ── playlists ─────────────────────────────────────────────────────
        if name in {"playlist_create", "playlist_delete", "playlist_add", "playlist_remove"}:
            _PLAYLIST_CACHE.pop(user.user_id, None)
        if name == "playlist_create":
            entry = await pl.create(user.user_id, str(value or "New playlist"))
            return ok(playlist=pl.summary(entry))
        if name == "playlist_delete":
            return ok(deleted=await pl.delete(user.user_id, str(value or "")))
        if name == "playlist_add":
            payload = value if isinstance(value, dict) else {}
            playlist_id = str(payload.get("playlist_id") or "")
            track_payload = payload.get("track") or {}
            tracks: list[Track] = []
            if track_payload.get("id"):
                tracks = [Track.from_dict(track_payload)]
            elif state_obj and state_obj.current:
                tracks = [state_obj.current]
            added = await pl.add_tracks(user.user_id, playlist_id, tracks)
            return ok(added=added)
        if name == "playlist_remove":
            payload = value if isinstance(value, dict) else {}
            return ok(
                removed=await pl.remove_track(
                    user.user_id, str(payload.get("playlist_id") or ""), str(payload.get("id") or "")
                )
            )
        if name == "playlist_play":
            playlist_id = str(value or "")
            title, tracks = await pl.as_tracks(user.user_id, playlist_id)
            if not tracks:
                return web.json_response({"ok": False, "error": "playlist is empty"}, status=400)
            started = 0
            for track in tracks[:60]:
                position = await player.enqueue(chat_id, track)
                if position > 0:
                    started += 1
            return ok(queued=started, name=title)

        if name == "search":
            query = str(value or "").strip()
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            tracks = await runtime.youtube.search(
                query, limit=8, requester=(user.user_id, user.name or "")
            )
            return ok(results=[_track_json(t, index=i) for i, t in enumerate(tracks, 1)])

        if name == "download":
            payload = value if isinstance(value, dict) else {}
            query = str(payload.get("query") or "").strip()
            kind = "video" if payload.get("kind") == "video" else "audio"
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            if runtime.bot is None:
                return web.json_response({"ok": False, "error": "bot unavailable"}, status=503)
            from vyron.modules.play import deliver

            track = await runtime.youtube.resolve(query, requester=(user.user_id, user.name or ""))
            task = asyncio.create_task(
                deliver(runtime.bot, chat_id, track, kind == "video", reply_to=None)
            )
            _TASKS.add(task)
            task.add_done_callback(_TASKS.discard)
            return ok(started=True, track=_track_json(track))

    except Exception as exc:
        logger.warning("web action %s failed: %s", name, exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=400)

    return web.json_response({"ok": False, "error": f"unknown action {name!r}"}, status=400)


# ── misc ────────────────────────────────────────────────────────────────────
async def info(request: web.Request) -> web.Response:
    return web.json_response(
        {
            "ok": True,
            "name": settings.webapp_title,
            "bot": settings.bot_username,
            "version": runtime.version,
            "auth_required": not settings.webapp_allow_anon,
            "streaming": runtime.streaming_ready,
            "music_api": {
                "enabled": bool(settings.music_api),
                "open": bool(settings.music_api_open),
                "base": settings.api_base or _public_base(request) if settings.music_api else "",
                "docs": f"{settings.api_base or _public_base(request)}/v1/docs" if settings.music_api else "",
            },
        }
    )


async def authenticate(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    token = make_token(_chat_id(user), user.user_id, settings.bot_token)
    return web.json_response({"ok": True, "token": token, "chat_id": _chat_id(user)})


def chat_link(chat_id: int, user_id: int) -> str:
    if not settings.webapp_url:
        return ""
    token = make_token(chat_id, user_id, settings.bot_token)
    return f"{settings.webapp_url}/app/?t={token}"


# ── owner console: journal ──────────────────────────────────────────────────
_LOG_FILTERS: dict[str, list[str] | None] = {
    "all": None,
    "info": ["info", "ok", "warn", "error"],
    "warn": ["warn", "error"],
    "error": ["error"],
}


def _system_snapshot() -> dict:
    """Everything an owner wants on one screen, without a second dashboard."""
    player = runtime.player
    from vyron.core import keepalive, watchdog

    chats = 0
    playing = 0
    if player is not None:
        try:
            chats = len(player.active_chats())
            playing = sum(
                1
                for chat_id in player.active_chats()
                if getattr(player.queues.get(chat_id), "playing", False)
            )
        except Exception:  # pragma: no cover - defensive
            pass
    return {
        "version": runtime.version,
        "uptime": round(runtime.uptime, 1),
        "storage": getattr(runtime.storage, "backend", "none") if runtime.storage else "none",
        "streaming": runtime.streaming_ready,
        "resolver": runtime.youtube is not None,
        "downloader": runtime.downloader is not None,
        "handlers": len(runtime.handlers_loaded),
        "chats": chats,
        "playing": playing,
        "watchdog": dict(watchdog.status()),
        "keepalive": {
            key: value
            for key, value in keepalive.status().items()
            if key in {"enabled", "runs", "last_ok", "last_status"}
        },
    }


async def logs(request: web.Request) -> web.Response:
    """Owner-only journal feed. `?since=<seq>` makes it a cheap live tail."""
    user = await _identify(request)
    if not _is_owner(user):
        return web.json_response({"ok": False, "error": "owner only"}, status=403)
    query = request.query
    try:
        since = max(0, int(query.get("since") or 0))
    except ValueError:
        since = 0
    try:
        limit = min(400, max(10, int(query.get("n") or 120)))
    except ValueError:
        limit = 120
    level = (query.get("level") or "all").lower()
    scope = (query.get("scope") or "").strip() or None

    events = journal.events(
        since=since,
        limit=limit,
        levels=_LOG_FILTERS.get(level, None),
        scope=scope,
    )
    stats = journal.stats()
    return web.json_response(
        {
            "ok": True,
            "events": events,
            "stats": stats,
            "system": _system_snapshot(),
            "filter": {"level": level, "scope": scope, "since": since, "n": limit},
        }
    )




# ── live log stream (SSE) ───────────────────────────────────────────────────

LIVE_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="color-scheme" content="dark">
<title>VYRON · live logs</title>
<style>
  :root { --bg:#07080c; --panel:#0d0f16; --line:#1b1f2b; --text:#e7eaf3; --dim:#8b93a7;
          --ok:#3ddc97; --warn:#ffcc66; --err:#ff6b6b; --accent:#8b7bff; }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--text);
    font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace; }
  header { position:sticky; top:0; display:flex; flex-wrap:wrap; gap:8px; align-items:center;
    padding:12px 14px; background:rgba(7,8,12,.92); backdrop-filter:blur(10px);
    border-bottom:1px solid var(--line); z-index:2; }
  .brand { font-weight:700; letter-spacing:.14em; font-size:11px; color:var(--dim); }
  .dot { width:8px; height:8px; border-radius:50%; background:var(--err); box-shadow:0 0 10px var(--err); }
  .dot.on { background:var(--ok); box-shadow:0 0 10px var(--ok); }
  button, input { font:inherit; color:var(--text); background:var(--panel); border:1px solid var(--line);
    border-radius:10px; padding:6px 10px; }
  button { cursor:pointer; }
  button[aria-pressed="true"] { border-color:var(--accent); color:#fff; background:#171533; }
  #list { padding:10px 12px 40px; }
  .row { display:grid; grid-template-columns:64px 58px 96px 1fr; gap:10px; padding:5px 6px;
    border-radius:8px; border-left:2px solid transparent; }
  .row:hover { background:#0b0d14; }
  .row.warn { border-left-color:var(--warn); }
  .row.error { border-left-color:var(--err); }
  .row.ok { border-left-color:var(--ok); }
  .time { color:var(--dim); }
  .lvl { text-transform:uppercase; font-size:10.5px; letter-spacing:.08em; }
  .lvl.warn { color:var(--warn); } .lvl.error { color:var(--err); } .lvl.ok { color:var(--ok); }
  .lvl.info { color:#6ea8ff; } .lvl.debug { color:var(--dim); }
  .scope { color:var(--dim); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .msg { white-space:pre-wrap; word-break:break-word; }
  .meta { display:none; margin:4px 0 0; padding:8px 10px; border-radius:8px; background:#0a0c12;
    color:#a9b2c7; white-space:pre-wrap; }
  .row.open .meta { display:block; }
  .row.clickable { cursor:pointer; }
  #empty { color:var(--dim); padding:24px 14px; }
  @media (max-width:640px) { .row { grid-template-columns:54px 1fr; } .scope { display:none; } }
</style>
</head>
<body>
<header>
  <span class="dot" id="dot"></span>
  <span class="brand">VYRON · LIVE</span>
  <button id="pause" aria-pressed="false">pause</button>
  <button data-level="all" aria-pressed="true">all</button>
  <button data-level="info" aria-pressed="false">info+</button>
  <button data-level="warn" aria-pressed="false">warn+</button>
  <button data-level="error" aria-pressed="false">errors</button>
  <input id="scope" placeholder="scope filter" size="10">
  <button id="clear">clear view</button>
  <button id="save">download</button>
  <span class="brand" id="stats"></span>
</header>
<div id="list"></div>
<div id="empty">waiting for events…</div>
<script>
(function(){
  var params = new URLSearchParams(location.search);
  var token = params.get('ot') || params.get('t') || '';
  var level = 'all', scope = '', paused = false, keep = [], source = null;
  var list = document.getElementById('list');
  var empty = document.getElementById('empty');
  var dot = document.getElementById('dot');
  var statsEl = document.getElementById('stats');

  function fmtTime(ts){
    var d = new Date((ts || 0) * 1000);
    return d.toTimeString().slice(0,8);
  }
  function add(ev){
    if (paused) { keep.push(ev); return; }
    var row = document.createElement('div');
    row.className = 'row ' + (ev.level || 'info') + (ev.meta && Object.keys(ev.meta).length ? ' clickable' : '');
    var meta = ev.meta && Object.keys(ev.meta).length;
    row.innerHTML = '<span class="time">' + fmtTime(ev.ts) + '</span>' +
      '<span class="lvl ' + (ev.level || 'info') + '">' + (ev.level || 'info') + '</span>' +
      '<span class="scope">' + (ev.scope || 'app') + '</span>' +
      '<span class="msg"></span>';
    row.querySelector('.msg').textContent = ev.message || '';
    if (meta) {
      var pre = document.createElement('pre');
      pre.className = 'meta';
      pre.textContent = JSON.stringify(ev.meta, null, 2);
      row.querySelector('.msg').appendChild(pre);
      row.addEventListener('click', function(){ row.classList.toggle('open'); });
    }
    list.appendChild(row);
    while (list.childElementCount > 1200) { list.removeChild(list.firstChild); }
    empty.style.display = 'none';
    if (nearBottom()) window.scrollTo(0, document.body.scrollHeight);
  }
  function nearBottom(){
    return window.innerHeight + window.scrollY >= document.body.scrollHeight - 120;
  }
  function connect(){
    if (source) { source.close(); }
    var url = '/api/logs/stream?level=' + encodeURIComponent(level) +
      (scope ? '&scope=' + encodeURIComponent(scope) : '') +
      (token ? '&ot=' + encodeURIComponent(token) : '');
    source = new EventSource(url);
    source.addEventListener('open', function(){ dot.classList.add('on'); });
    source.addEventListener('error', function(){ dot.classList.remove('on'); });
    source.addEventListener('log', function(message){
      try { add(JSON.parse(message.data)); } catch (e) {}
    });
    source.addEventListener('hello', function(message){
      try {
        var data = JSON.parse(message.data);
        var counts = (data.stats && data.stats.counts) || {};
        statsEl.textContent = (counts.error || 0) + ' errors · ' + (counts.warn || 0) + ' warnings';
      } catch (e) {}
    });
  }
  document.querySelectorAll('[data-level]').forEach(function(btn){
    btn.addEventListener('click', function(){
      level = btn.getAttribute('data-level');
      document.querySelectorAll('[data-level]').forEach(function(other){
        other.setAttribute('aria-pressed', String(other === btn));
      });
      connect();
    });
  });
  document.getElementById('pause').addEventListener('click', function(){
    paused = !paused;
    this.setAttribute('aria-pressed', String(paused));
    this.textContent = paused ? 'resume' : 'pause';
    if (!paused) { keep.splice(0).forEach(add); }
  });
  document.getElementById('scope').addEventListener('change', function(){
    scope = this.value.trim(); connect();
  });
  document.getElementById('clear').addEventListener('click', function(){
    list.innerHTML = ''; empty.style.display = 'block';
  });
  document.getElementById('save').addEventListener('click', function(){
    var text = Array.from(list.children).map(function(row){
      return row.querySelector('.time').textContent + ' ' +
        row.querySelector('.lvl').textContent + ' ' +
        row.querySelector('.scope').textContent + ' ' +
        row.querySelector('.msg').firstChild.textContent;
    }).join('\n');
    var blob = new Blob([text], {type:'text/plain'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'vyron-logs.txt';
    a.click();
  });
  connect();
})();
</script>
</body>
</html>"""


async def _sse(response: web.StreamResponse, event: str, payload: dict) -> None:
    import json as _json

    body = f"event: {event}\ndata: {_json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
    await response.write(body.encode("utf-8"))


def _passes(event: dict, levels: set[str] | None, scope: str | None) -> bool:
    if levels is not None and event.get("level") not in levels:
        return False
    if scope and event.get("scope") != scope:
        return False
    return True


async def logs_stream(request: web.Request) -> web.StreamResponse:
    """Server-sent events: the journal, live, for the owner's console.

    A render host showing "server failure" is only half a diagnosis; this
    stream is the other half — the same lines the process logs, as they happen,
    with the backlog replayed first so nothing is missed on reconnect.
    """
    user = await _identify(request)
    if not _is_owner(user):
        return web.json_response({"ok": False, "error": "owner only"}, status=403)

    level = (request.query.get("level") or "all").lower()
    levels = set(_LOG_FILTERS.get(level) or []) or None
    scope = (request.query.get("scope") or "").strip() or None
    try:
        since = max(0, int(request.query.get("since") or 0))
    except ValueError:
        since = 0

    response = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await response.prepare(request)
    await response.write(b"retry: 3000\n\n")

    subscription = journal.subscribe(limit=600)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 240  # browsers reconnect; proxies like short streams
    try:
        for event in journal.events(limit=200, since=since):
            if _passes(event, levels, scope):
                await _sse(response, "log", event)
        await _sse(
            response,
            "hello",
            {
                "seq": journal.stats().get("seq", 0),
                "stats": journal.stats(),
                "system": _system_snapshot(),
                "subscribers": journal.subscribers,
            },
        )
        while loop.time() < deadline:
            try:
                payload = await asyncio.wait_for(subscription.queue.get(), timeout=15)
            except asyncio.TimeoutError:
                await response.write(b": ping\n\n")  # keep-alive comment
                continue
            if not _passes(payload, levels, scope):
                continue
            await _sse(response, "log", payload)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        journal.unsubscribe(subscription)
    return response


def _live_page() -> str:
    """A tiny, dependency-free viewer for the stream (works on a phone)."""
    return LIVE_PAGE


async def logs_live(_request: web.Request) -> web.Response:
    return web.Response(text=_live_page(), content_type="text/html", charset="utf-8")



async def logs_action(request: web.Request) -> web.Response:
    """`clear` or `export` the journal — owner only, always audited."""
    user = await _identify(request)
    if not _is_owner(user):
        return web.json_response({"ok": False, "error": "owner only"}, status=403)
    body = await _read_json(request)
    action_name = str(body.get("action") or "").lower()
    if action_name == "clear":
        removed = journal.clear(reason="from the web console")
        return web.json_response({"ok": True, "cleared": removed, "stats": journal.stats()})
    if action_name == "export":
        path = journal.export()
        if path is None:
            return web.json_response({"ok": False, "error": "nothing to export"}, status=404)
        return web.json_response({"ok": True, "file": path.name, "path": str(path)})
    return web.json_response({"ok": False, "error": "unknown action"}, status=400)


def register(app: web.Application) -> None:
    if not settings.webapp:
        return
    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if WEB_DIR.is_dir():
        app.router.add_static("/app/static", WEB_DIR, show_index=False)
    # SPA deep links (/app/anything) render the shell; the app routes in memory.
    app.router.add_get("/app/{tail:(?!static/).+}", index)
    app.router.add_get("/api/info", info)
    app.router.add_get("/api/home", home)
    app.router.add_get("/api/rooms", rooms)
    app.router.add_post("/api/room", room_attach)
    app.router.add_get("/api/playlists", playlists_route)
    app.router.add_get("/api/mix", mix)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/state", state)
    app.router.add_post("/api/search", search)
    app.router.add_post("/api/action", action)
    app.router.add_post("/api/auth", authenticate)
    app.router.add_post("/api/lyrics", lyrics)
    app.router.add_get("/api/keys", api_keys)
    app.router.add_post("/api/keys", api_keys)
    app.router.add_get("/api/logs", logs)
    app.router.add_get("/api/logs/stream", logs_stream)
    app.router.add_get("/logs/live", logs_live)
    app.router.add_post("/api/logs", logs_action)
    audio.register(app)
    logger.info("web app mounted from %s", WEB_DIR)


__all__ = ["WEB_DIR", "chat_link", "register"]
