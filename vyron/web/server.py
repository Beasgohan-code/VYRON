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
from vyron.core.lyrics import parse_lrc
from vyron.core.queue import LoopMode, Track
from vyron.runtime import runtime
from vyron.core.musicapi import find_key, get_music_api, mask_key
from vyron.web import stream as audio
from vyron.web.auth import WebUser, make_token, resolve_user, verify_owner_token

logger = logging.getLogger(__name__)

_LYRICS_CACHE: dict[str, tuple[float, dict]] = {}

_WEBAPP_ROOT = Path(
    getattr(settings, "webapp_dir", Path(__file__).resolve().parent.parent.parent / "webapp")
)
# `webapp/dist` is the compiled SPA; fall back to the folder itself so a custom
# or hand-written build (WEBAPP_DIR=…) keeps working.
WEB_DIR = _WEBAPP_ROOT / "dist" if (_WEBAPP_ROOT / "dist" / "index.html").is_file() else _WEBAPP_ROOT


# ── demo payload (browser preview) ──────────────────────────────────────────
# Served to anonymous visitors and to the standalone preview server, so the UI
# can be developed without Telegram credentials or network access.  Covers are
# the procedural artwork shipped in frontend/public/covers.
def _demo_track(index: int, title: str, uploader: str, duration: int) -> dict:
    return {
        "id": f"demo{index:02d}",
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "thumbnail": f"/app/static/covers/{index:02d}.jpg",
        "source": "youtube",
        "url": "",
        "query": f"{title} {uploader}",
        "stream": f"/api/stream/demo{index:02d}",
    }


_DEMO_TRACKS = [
    _demo_track(1, "Neon Skyline", "VYRON Sessions", 198),
    _demo_track(2, "Slow Motion", "Aria Vale", 241),
    _demo_track(3, "Afterglow", "Kite & Co.", 167),
    _demo_track(4, "Midnight Drive", "Lumen", 212),
    _demo_track(5, "Paper Planes", "Nova Ray", 189),
    _demo_track(6, "Golden Hour", "Sable", 233),
    _demo_track(7, "Static Bloom", "Halcyon", 205),
    _demo_track(8, "Riverline", "Ora", 176),
    _demo_track(9, "Glasshouse", "Mirage Club", 254),
    _demo_track(10, "Ultraviolet", "Neon Hills", 221),
]

_DEMO_QUEUE = [{**track, "index": index} for index, track in enumerate(_DEMO_TRACKS[:6], 1)]

_DEMO_MIXES = [
    ("daily", "Daily Mix", "sun"),
    ("chill", "Chill Vibes", "wave"),
    ("anime", "Anime Mix", "star"),
    ("workout", "Workout", "bolt"),
    ("focus", "Focus", "moon"),
    ("night", "Night Vibes", "moon"),
]

DEMO = {
    "version": "preview",
    "streaming": True,
    "bot": "VyronMusicBot",
    "user": {"id": 0, "name": "Preview Listener", "username": "preview"},
    "chat": {"id": 0, "title": "VYRON Preview", "is_group": False},
    "now": {
        **_DEMO_TRACKS[3],
        "elapsed": 74.0,
        "progress": 0.35,
        "paused": False,
        "requested_by": "you",
    },
    "queue": _DEMO_QUEUE,
    "settings": {
        "volume": 100,
        "loop": "off",
        "autoplay": True,
        "always_on": False,
        "shuffle": False,
        "effects": [],
    },
    "favorites": _DEMO_TRACKS[:5],
    "history": _DEMO_TRACKS[5:],
    "playlists": [
        {
            "id": "p1",
            "name": "Late Night",
            "count": 4,
            "duration": 848,
            "covers": [t["thumbnail"] for t in _DEMO_TRACKS[:4]],
            "tracks": _DEMO_TRACKS[:4],
        },
        {
            "id": "p2",
            "name": "Focus Session",
            "count": 3,
            "duration": 651,
            "covers": [t["thumbnail"] for t in _DEMO_TRACKS[4:7]],
            "tracks": _DEMO_TRACKS[4:7],
        },
    ],
    "rooms": [
        {
            "chat_id": -1001,
            "title": "Chill Squad",
            "username": "vyronmusichub",
            "listeners": 4,
            "playing": True,
            "paused": False,
            "track": _DEMO_TRACKS[1],
            "volume": 90,
            "effects": ["bass"],
        },
        {
            "chat_id": -1002,
            "title": "Late Night Lo-fi",
            "username": "",
            "listeners": 12,
            "playing": True,
            "paused": True,
            "track": _DEMO_TRACKS[6],
            "volume": 70,
            "effects": [],
        },
    ],
    "stats": {"users": 4832, "chats": 128, "tracks": 12400},
}


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
        who = verify_owner_token(owner_raw, settings.bot_token)
        if who is not None and who.user_id in settings.owners:
            return who

    return resolve_user(
        init_data=init_data or "",
        token=token or "",
        bot_token=settings.bot_token,
        allow_anon=settings.webapp_allow_anon,
        owner_ids=settings.owners,
    )


def _denied(user: WebUser) -> web.Response | None:
    if user.authenticated or user.owner or settings.webapp_allow_anon:
        return None
    return web.json_response(
        {"ok": False, "error": "unauthorized", "hint": "open the app from Telegram"},
        status=401,
    )


def _is_preview(user: WebUser) -> bool:
    return user.source == "anon" and runtime.player is None


def _is_owner(user: WebUser) -> bool:
    return bool(getattr(user, "owner", False) or (user.user_id and user.user_id in settings.owners))


def _chat_id(user: WebUser) -> int:
    return user.chat_id or user.user_id


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
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


# ── state ───────────────────────────────────────────────────────────────────
async def state(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    if _is_preview(user):
        return web.json_response({"ok": True, "preview": True, **DEMO})

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

    chat_title = ""
    if runtime.bot and user.chat_id:
        try:
            chat = await runtime.bot.get_chat(user.chat_id)
            chat_title = chat.title or chat.first_name or ""
        except Exception:
            chat_title = ""

    favorites = await runtime.storage.favorites(user.user_id, 50) if runtime.storage else []
    history = await runtime.storage.history(user.user_id, 20) if runtime.storage else []
    playlists = [pl.summary(entry) for entry in await pl.list_playlists(user.user_id)]
    counters = await runtime.storage.counters() if runtime.storage else {}

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


# ── home / discovery ────────────────────────────────────────────────────────
async def home(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    if _is_preview(user) or runtime.charts is None:
        return web.json_response(
            {
                "ok": True,
                "preview": True,
                "hero": {
                    "headline": "Music hits different here.",
                    "subline": "Discover, stream, download and listen together — all in one place.",
                    "cover": "/app/static/covers/07.jpg",
                },
                "trending": _DEMO_TRACKS[:8],
                "shelves": [
                    {
                        "key": key,
                        "title": title,
                        "glyph": glyph,
                        "kind": "mix",
                        "tracks": [
                            _DEMO_TRACKS[(index * 2 + offset) % len(_DEMO_TRACKS)]
                            for offset in range(4)
                        ],
                    }
                    for index, (key, title, glyph) in enumerate(_DEMO_MIXES)
                ],
                "moods": [
                    {"key": key, "title": title.replace(" Mix", ""), "glyph": "note"}
                    for key, title, _glyph in _DEMO_MIXES
                ]
                + [
                    {"key": "romance", "title": "Romance", "glyph": "heart"},
                    {"key": "party", "title": "Party", "glyph": "spark"},
                ],
            }
        )

    payload = await runtime.charts.home()
    return web.json_response({"ok": True, **payload})


async def search(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    body = await _read_json(request)
    query = str(body.get("query") or request.query.get("q") or "").strip()
    if not query:
        return web.json_response({"ok": True, "results": []})
    if _is_preview(user):
        return web.json_response({"ok": True, "results": _DEMO_TRACKS, "preview": True})

    limit = min(20, max(4, int(body.get("limit") or 10)))
    try:
        tracks = await runtime.youtube.search(
            query, limit=limit, requester=(user.user_id, user.name or "")
        )
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    return web.json_response(
        {"ok": True, "query": query, "results": [_track_json(track, index=i) for i, track in enumerate(tracks, 1)]}
    )


def _demo_lyrics(span: int) -> list[dict]:
    """Placeholder synced lyrics used by the anonymous browser preview."""
    words = (
        "city lights are bleeding through the window",
        "we were never meant to slow down",
        "hold the night a little longer",
        "every echo pulls me back to you",
        "static on the radio, still dancing",
        "nothing here is heavy when you sing",
        "keep the volume up until the morning",
        "we are golden in the afterglow",
        "run the tape again from the beginning",
        "all the quiet parts are yours",
        "tell me what the sky is playing",
        "one more chorus, then we go",
    )
    step = span / (len(words) + 1)
    return [{"time": round(step * (index + 1), 2), "text": line} for index, line in enumerate(words)]


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

    if _is_preview(user):
        # The browser preview has no bot runtime and no outbound network: serve a
        # deterministic lyric sheet so the player's synced-lyrics panel can be
        # exercised without credentials.
        span = max(30, duration or 180)
        lines = _demo_lyrics(span)
        payload = {
            "title": title,
            "artist": artist,
            "text": "\n".join(line["text"] for line in lines),
            "synced": True,
            "lines": lines,
            "demo": True,
        }
        return web.json_response({"ok": True, **payload})

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


_DEMO_KEYS = [
    {
        "id": "key_preview0001",
        "prefix": "vyrn_preview",
        "key": "vyrn_previewKEYdemo0000000000000000000000",
        "masked": "vyrn_pre…0000",
        "label": "preview-bot",
        "owner_id": 0,
        "scopes": ["read", "search", "download"],
        "active": True,
        "uses": 128,
        "bytes": 734003200,
        "created_at": 1750000000.0,
        "last_used_at": 1759999999.0,
        "expires_at": None,
        "rate_limit": None,
    },
    {
        "id": "key_preview0002",
        "prefix": "vyrn_ci",
        "key": "vyrn_ciKEYdemo00000000000000000000000000",
        "masked": "vyrn_ciK…0000",
        "label": "ci-pipeline",
        "owner_id": 0,
        "scopes": ["read", "search", "download", "admin"],
        "active": False,
        "uses": 41,
        "bytes": 52428800,
        "created_at": 1745000000.0,
        "last_used_at": 1749000000.0,
        "revoked_at": 1749500000.0,
        "expires_at": None,
        "rate_limit": 60,
    },
]


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
        "version": "2.0",
    }

    if _is_preview(user):
        payload = {
            "ok": True,
            "preview": True,
            "base": base,
            "docs": docs,
            "openapi": f"{base}/v1/openapi.json" if base else "/v1/openapi.json",
            "is_owner": True,
            "keys": _DEMO_KEYS,
            "stats": {
                "enabled": True,
                "open": True,
                "keys": 1,
                "keys_total": 2,
                "requests": 128,
                "bytes": 734003200,
                "rate_limit": settings.music_api_rate,
                "storage": "demo",
                "version": "2.0",
            },
            "metrics": {
                "requests": 128,
                "downloads": 31,
                "bytes_served": 734003200,
                "rate_limited": 2,
                "uptime_seconds": 3600,
                "latency_ms": {"avg": 18.0, "p50": 12.0, "p95": 34.0, "p99": 61.0},
                "by_status": {"200": 126, "429": 2},
            },
            **meta,
        }
        if request.method == "GET":
            return web.json_response(payload)
        body = await _read_json(request)
        action = str(body.get("action") or "create")
        if action == "create":
            record = {
                "key": "vyrn_" + "demo" * 10,
                "masked": "vyrn_demo…demo",
                "id": "key_demo0001",
                "prefix": "vyrn_demo",
                "label": str(body.get("label") or "web")[:40],
                "scopes": body.get("scopes") or meta["default_scopes"],
                "owner_id": 0,
                "active": True,
                "uses": 0,
                "bytes": 0,
                "expires_at": None,
                "created_at": time.time(),
            }
            return web.json_response({**payload, "ok": True, "created": record})
        return web.json_response({**payload, "ok": True, "revoked": True, "rotated": action == "rotate"})

    is_owner = _is_owner(user)
    if request.method == "GET":
        keys = await api.keys(None if is_owner else user.user_id, reveal=False)
        stats = await api.stats()
        from vyron.api.metrics import METRICS

        return web.json_response(
            {
                "ok": True,
                "base": base,
                "docs": docs,
                "openapi": f"{base}/v1/openapi.json" if base else "/v1/openapi.json",
                "is_owner": is_owner,
                "keys": keys,
                "stats": stats,
                "metrics": METRICS.snapshot(),
                **meta,
            }
        )

    if not is_owner:
        return web.json_response(
            {"ok": False, "error": "only the bot owner can manage API keys"}, status=403
        )

    body = await _read_json(request)
    action = str(body.get("action") or "create")
    keys = await api.keys(reveal=False)

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
        )
        if record is None:
            return web.json_response({"ok": False, "error": error or "could not create key"}, status=400)
        logger.info("music api key issued to %s (%s)", user.user_id, record.get("label"))
        return web.json_response(
            {"ok": True, "created": {**record, "masked": mask_key(str(record["key"]))}}
        )

    identifier = str(body.get("id") or body.get("key") or body.get("prefix") or "").strip()
    if not identifier:
        return web.json_response({"ok": False, "error": "id is required"}, status=400)
    if not find_key(keys, identifier):
        return web.json_response({"ok": False, "error": "key not found"}, status=404)

    if action == "revoke":
        revoked = await api.revoke(None, identifier, force=True)
        return web.json_response(
            {"ok": revoked, "revoked": revoked, **({} if revoked else {"error": "key not found"})}
        )

    if action == "rotate":
        match = find_key(keys, identifier) or {}
        record, error = await api.rotate(int(match.get("owner_id") or user.user_id), str(match.get("id")))
        if record is None:
            return web.json_response({"ok": False, "error": error or "could not rotate"}, status=400)
        return web.json_response(
            {"ok": True, "created": {**record, "masked": mask_key(str(record["key"]))}}
        )

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
    if _is_preview(user) or runtime.charts is None:
        return web.json_response({"ok": True, "tracks": _DEMO_TRACKS, "preview": True})
    tracks = await runtime.charts.mix(key, limit=25)
    if not tracks:
        tracks = await runtime.charts.mood(key, limit=25)
    return web.json_response(
        {"ok": True, "key": key, "tracks": [_track_json(t, index=i) for i, t in enumerate(tracks, 1)]}
    )


# ── rooms (listen together) ─────────────────────────────────────────────────
async def rooms(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied
    if _is_preview(user) or runtime.player is None:
        return web.json_response({"ok": True, "rooms": DEMO["rooms"], "preview": True})

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
    if _is_preview(user):
        return web.json_response({"ok": True, "playlists": DEMO["playlists"], "preview": True})
    return web.json_response(
        {
            "ok": True,
            "playlists": [pl.summary(entry) for entry in await pl.list_playlists(user.user_id)],
        }
    )


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


async def action(request: web.Request) -> web.Response:
    user = await _identify(request)
    denied = _denied(user)
    if denied:
        return denied

    body = await _read_json(request)
    name = str(body.get("action") or "")
    value = body.get("value")
    chat_id = _chat_id(user)

    if _is_preview(user):
        return web.json_response({"ok": True, "preview": True, "action": name})

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
            return ok(position=position, track=_track_json(track))

        if name in {"play_now", "play_next"}:
            query = str(value or "").strip()
            if not query:
                return web.json_response({"ok": False, "error": "empty query"}, status=400)
            track = await runtime.youtube.resolve(query, requester=(user.user_id, user.name or ""))
            if name == "play_now":
                await player.play_track(chat_id, track)
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
            return ok(track=_track_json(await player.skip(chat_id, count=int(value or 1))))
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
            return ok(track=_track_json(await player.jump(chat_id, int(value or 0))))
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
    audio.register(app)
    logger.info("web app mounted from %s", WEB_DIR)


__all__ = ["DEMO", "WEB_DIR", "chat_link", "register"]
