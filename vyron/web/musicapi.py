# ---------------------------------------------------------------------------
#  VYRON — Music API HTTP surface (Eldian-compatible, same URL as the bot)
#
#  Registered on the *same* aiohttp app as /health and the Mini App, so one
#  Render deployment exposes everything:
#
#      GET  /v1                  → docs page (human readable)
#      GET  /v1/openapi.json     → machine readable description
#      GET  /v1/health           → {"status": "ok", ...}
#      POST /v1/track/by-video-id→ audio file   (X-API-Key)
#      POST /v1/track/by-query   → audio file   (X-API-Key)
#      POST /v1/search           → JSON tracks  (X-API-Key)
#      GET  /v1/info/by-video-id → JSON track   (X-API-Key)
#      GET  /v1/lyrics           → JSON lyrics  (X-API-Key)
#      GET  /v1/key              → key + quota  (X-API-Key)
#
#  Mutating key operations live in the Mini App (/api/keys) and in the bot
#  (/getapi, /listkey, /revoke) — never in this public surface.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import re
from html import escape as html_escape
from typing import Any

from aiohttp import web

from vyron.config import settings
from vyron.core.musicapi import AuthResult, get_music_api, mask_key
from vyron.runtime import runtime

logger = logging.getLogger(__name__)

VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{6,24}$")
_DOWNLOAD_SLOTS = 2
_semaphore: "asyncio.Semaphore | None" = None


# ── helpers ────────────────────────────────────────────────────────────────
def _sem() -> "asyncio.Semaphore":
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_DOWNLOAD_SLOTS)
    return _semaphore


def _header(request: web.Request) -> str:
    raw = request.headers.get("X-API-Key") or request.headers.get("x-api-key") or ""
    if not raw:
        bearer = request.headers.get("Authorization", "")
        if bearer.lower().startswith("bearer "):
            raw = bearer[7:]
    if not raw:
        raw = request.query.get("key") or ""
    return raw.strip()


async def _auth(request: web.Request) -> AuthResult:
    return await get_music_api().authenticate(_header(request))


def _limited(auth: AuthResult) -> dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(auth.limit),
        "X-RateLimit-Remaining": str(max(0, auth.remaining)),
        "X-RateLimit-Reset": str(auth.reset_in),
    }
    if auth.record:
        headers["X-API-Key-Masked"] = mask_key(str(auth.record.get("key", "")))
    return headers


def _fail(auth: AuthResult) -> web.Response:
    return web.json_response(
        {"ok": False, "error": auth.error or "unauthorized"},
        status=auth.status or 401,
        headers=_limited(auth),
    )


async def _body(request: web.Request) -> dict[str, Any]:
    if request.can_read_body:
        try:
            payload = await request.json()
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return dict(request.query)


def _track_json(track) -> dict[str, Any]:
    return {
        "video_id": track.id,
        "title": track.title,
        "artist": track.uploader,
        "duration": track.duration,
        "thumbnail": track.thumbnail,
        "source": track.source,
        "url": track.watch_url,
    }


def _base_url(request: web.Request) -> str:
    if settings.webapp_url:
        return settings.webapp_url
    proto = request.headers.get("X-Forwarded-Proto") or request.scheme
    host = request.headers.get("X-Forwarded-Host") or request.host
    return f"{proto}://{host}"


def _ready() -> bool:
    return runtime.youtube is not None and runtime.downloader is not None


def _not_ready() -> web.Response:
    return web.json_response(
        {
            "ok": False,
            "error": "the bot is still starting — retry in a moment",
            "ready": False,
        },
        status=503,
    )


# ── endpoints ──────────────────────────────────────────────────────────────
async def health(request: web.Request) -> web.Response:
    api = get_music_api()
    stats = await api.stats()
    return web.json_response(
        {
            "status": "ok",
            "ok": True,
            "service": "vyron-music-api",
            "version": runtime.version,
            "uptime": round(runtime.uptime, 1),
            "ready": _ready(),
            "streaming": runtime.streaming_ready,
            "auth_required": not settings.music_api_open,
            "rate_limit": stats["rate_limit"],
            "keys": stats["keys"],
            "endpoints": [
                "/v1/track/by-video-id",
                "/v1/track/by-query",
                "/v1/search",
                "/v1/info/by-video-id",
                "/v1/lyrics",
                "/v1/key",
            ],
        }
    )


async def search(request: web.Request) -> web.Response:
    auth = await _auth(request)
    if not auth.ok:
        return _fail(auth)
    if not _ready():
        return _not_ready()

    body = await _body(request)
    query = str(body.get("query") or body.get("q") or "").strip()
    if not query:
        return web.json_response({"ok": False, "error": "query is required"}, status=400)
    try:
        limit = max(1, min(25, int(body.get("limit") or settings.search_results)))
    except (TypeError, ValueError):
        limit = settings.search_results

    try:
        tracks = await runtime.youtube.search(query, limit=limit)
    except Exception as exc:
        logger.info("music api search failed: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=502)

    return web.json_response(
        {
            "ok": True,
            "query": query,
            "count": len(tracks),
            "results": [_track_json(track) for track in tracks],
        },
        headers=_limited(auth),
    )


def _video_id(body: dict[str, Any]) -> str:
    raw = str(body.get("video_id") or body.get("id") or body.get("v") or "").strip()
    if raw.startswith("http"):
        from vyron.core.search import youtube_id

        return youtube_id(raw) or ""
    return raw


async def info(request: web.Request) -> web.Response:
    auth = await _auth(request)
    if not auth.ok:
        return _fail(auth)
    if not _ready():
        return _not_ready()

    body = await _body(request)
    video_id = _video_id(body)
    if not VIDEO_RE.match(video_id):
        return web.json_response(
            {"ok": False, "error": "video_id must be a YouTube id (6-24 chars)"}, status=400
        )
    try:
        track = await runtime.youtube.resolve(f"https://www.youtube.com/watch?v={video_id}")
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    return web.json_response({"ok": True, "track": _track_json(track)}, headers=_limited(auth))


async def track_by_video_id(request: web.Request) -> web.StreamResponse:
    auth = await _auth(request)
    if not auth.ok:
        return _fail(auth)
    if not _ready():
        return _not_ready()

    body = await _body(request)
    video_id = _video_id(body)
    if not VIDEO_RE.match(video_id):
        return web.json_response(
            {"ok": False, "error": "video_id must be a YouTube id (6-24 chars)"}, status=400
        )
    return await _serve(request, auth, f"https://www.youtube.com/watch?v={video_id}")


async def track_by_query(request: web.Request) -> web.StreamResponse:
    auth = await _auth(request)
    if not auth.ok:
        return _fail(auth)
    if not _ready():
        return _not_ready()

    body = await _body(request)
    query = str(body.get("query") or body.get("q") or "").strip()
    if not query:
        return web.json_response({"ok": False, "error": "query is required"}, status=400)
    return await _serve(request, auth, query)


async def _serve(request: web.Request, auth: AuthResult, target: str) -> web.StreamResponse:
    try:
        track = await runtime.youtube.resolve(target)
    except Exception as exc:
        logger.info("music api resolve failed: %s", exc)
        return web.json_response({"ok": False, "error": str(exc)}, status=502)

    async with _sem():
        try:
            path = await runtime.downloader.audio(track)
        except Exception as exc:
            logger.warning("music api download failed: %s", exc)
            return web.json_response({"ok": False, "error": str(exc)}, status=502)

    size = path.stat().st_size
    await get_music_api().note_use(auth.record, size=size)
    filename = f"{track.title[:60]} [{track.id}].mp3".replace("/", "-").replace('"', "")
    headers = {
        **_limited(auth),
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Track-Id": str(track.id),
        "X-Track-Title": track.title[:200].encode("ascii", "ignore").decode() or "track",
        "X-Track-Duration": str(track.duration),
        "X-Track-Size": str(size),
        "Cache-Control": "private, max-age=0",
    }
    return web.FileResponse(path, headers=headers)


async def lyrics(request: web.Request) -> web.Response:
    auth = await _auth(request)
    if not auth.ok:
        return _fail(auth)

    body = await _body(request)
    title = str(body.get("title") or body.get("q") or "").strip()
    artist = str(body.get("artist") or "").strip()
    if not title:
        return web.json_response({"ok": False, "error": "title is required"}, status=400)
    if runtime.lyrics is None:
        return web.json_response({"ok": False, "error": "lyrics engine is not ready"}, status=503)

    try:
        duration = int(float(body.get("duration") or 0))
    except (TypeError, ValueError):
        duration = 0
    try:
        result = await (runtime.lyrics.timed(title, artist, duration) if duration else runtime.lyrics.find(title, artist))
    except Exception as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=502)
    if result is None:
        return web.json_response({"ok": False, "error": "no lyrics found"}, status=404)

    from vyron.core.lyrics import parse_lrc

    return web.json_response(
        {
            "ok": True,
            "title": result.title,
            "artist": result.artist,
            "synced": bool(result.has_sync),
            "text": result.as_text(),
            "lines": parse_lrc(result.synced),
        },
        headers=_limited(auth),
    )


async def me(request: web.Request) -> web.Response:
    auth = await _auth(request)
    if not auth.ok:
        return _fail(auth)
    record = auth.record or {}
    return web.json_response(
        {
            "ok": True,
            "key": mask_key(str(record.get("key", ""))),
            "label": record.get("label", ""),
            "owner_id": record.get("owner_id"),
            "created_at": record.get("created_at"),
            "last_used_at": record.get("last_used_at"),
            "uses": int(record.get("uses") or 0),
            "bytes": int(record.get("bytes") or 0),
            "open_access": bool(auth.open_access),
            "quota": {
                "limit_per_minute": auth.limit,
                "remaining": max(0, auth.remaining),
                "reset_in": auth.reset_in,
            },
        },
        headers=_limited(auth),
    )


async def index(request: web.Request) -> web.Response:
    """JSON index — /v1 is the docs page only for browsers."""
    if "text/html" in request.headers.get("Accept", "") and request.query.get("format") != "json":
        return await docs(request)
    base = _base_url(request)
    return web.json_response(
        {
            "ok": True,
            "service": "vyron-music-api",
            "version": runtime.version,
            "docs": f"{base}/v1/docs",
            "openapi": f"{base}/v1/openapi.json",
            "endpoints": {
                "health": "GET /v1/health",
                "track": "POST /v1/track/by-video-id",
                "track_by_query": "POST /v1/track/by-query",
                "search": "POST /v1/search",
                "info": "GET /v1/info/by-video-id?video_id=…",
                "lyrics": "GET /v1/lyrics?title=…&artist=…",
                "key": "GET /v1/key",
            },
        }
    )


def _spec() -> dict[str, Any]:
    key_scheme = {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
    secured = [{"ApiKeyAuth": []}]
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "VYRON Music API",
            "version": runtime.version,
            "description": "Eldian-compatible music API bundled with the VYRON bot.",
        },
        "components": {"securitySchemes": key_scheme},
        "paths": {
            "/v1/health": {"get": {"summary": "Health", "responses": {"200": {"description": "ok"}}}},
            "/v1/track/by-video-id": {
                "post": {
                    "summary": "Download a track by YouTube id",
                    "security": secured,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["video_id"],
                                    "properties": {"video_id": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "responses": {"200": {"description": "audio/mpeg"}, "401": {"description": "missing key"}},
                }
            },
            "/v1/track/by-query": {
                "post": {
                    "summary": "Download the first match for a search string",
                    "security": secured,
                    "responses": {"200": {"description": "audio/mpeg"}},
                }
            },
            "/v1/search": {
                "post": {
                    "summary": "Search YouTube",
                    "security": secured,
                    "responses": {"200": {"description": "JSON results"}},
                }
            },
            "/v1/info/by-video-id": {
                "get": {"summary": "Track metadata", "security": secured, "responses": {"200": {"description": "JSON"}}}
            },
            "/v1/lyrics": {
                "get": {"summary": "Lyrics from LRCLIB", "security": secured, "responses": {"200": {"description": "JSON"}}}
            },
            "/v1/key": {
                "get": {"summary": "Key info + quota", "security": secured, "responses": {"200": {"description": "JSON"}}}
            },
        },
    }


async def openapi(request: web.Request) -> web.Response:
    return web.json_response(_spec())


async def docs(request: web.Request) -> web.Response:
    base = _base_url(request)
    api = get_music_api()
    stats = await api.stats()
    auth_note = (
        "Open mode is on — requests work without a key."
        if settings.music_api_open
        else "Send your key as <code>X-API-Key</code> (or <code>Authorization: Bearer …</code>)."
    )

    def code(text: str) -> str:
        return f"<pre><code>{html_escape(text)}</code></pre>"

    rows = [
        ("GET", "/v1/health", "Status, version, readiness", "no"),
        ("POST", "/v1/track/by-video-id", "Download audio for a YouTube id", "yes"),
        ("POST", "/v1/track/by-query", "Download the first match for a query", "yes"),
        ("POST", "/v1/search", "Search YouTube, returns JSON", "yes"),
        ("GET", "/v1/info/by-video-id", "Metadata without downloading", "yes"),
        ("GET", "/v1/lyrics", "Lyrics + synced lines", "yes"),
        ("GET", "/v1/key", "Your key, usage and quota", "yes"),
        ("GET", "/v1/openapi.json", "OpenAPI 3.1 description", "no"),
    ]
    table = "".join(
        f"<tr><td><span class='verb {method.lower()}'>{method}</span></td>"
        f"<td><code>{html_escape(path)}</code></td>"
        f"<td>{html_escape(desc)}</td><td>{key}</td></tr>"
        for method, path, desc, key in rows
    )

    curl_track = (
        'curl -X POST "' + base + '/v1/track/by-video-id" \\\n'
        '  -H "X-API-Key: vyrn_xxxxxxxx" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        '  -d \'{"video_id":"dQw4w9WgXcQ"}\' --output track.mp3'
    )
    curl_search = (
        'curl -X POST "' + base + '/v1/search" \\\n'
        '  -H "X-API-Key: vyrn_xxxxxxxx" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        '  -d \'{"query":"weeknd blinding lights","limit":5}\''
    )
    python_sample = (
        "import requests\n\n"
        'KEY = "vyrn_xxxxxxxx"\n'
        'BASE = "' + base + '"\n\n'
        'r = requests.post(f"{BASE}/v1/track/by-video-id",\n'
        '                  headers={"X-API-Key": KEY},\n'
        '                  json={"video_id": "dQw4w9WgXcQ"}, stream=True)\n'
        "r.raise_for_status()\n"
        'with open("track.mp3", "wb") as fh:\n'
        "    for chunk in r.iter_content(65536):\n"
        "        fh.write(chunk)"
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>VYRON Music API</title>
<style>
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:#07070d;color:#f4f4fa;font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
.glow{{position:fixed;inset:-30% -10% auto;height:70vh;background:radial-gradient(50% 50% at 30% 20%,rgba(139,92,246,.35),transparent 70%),radial-gradient(40% 40% at 80% 0%,rgba(34,211,238,.22),transparent 70%);filter:blur(30px);pointer-events:none}}
main{{position:relative;max-width:960px;margin:0 auto;padding:56px 22px 90px}}
h1{{font-size:clamp(30px,5vw,44px);margin:0 0 6px;letter-spacing:-.02em}}
h2{{font-size:19px;margin:38px 0 10px}}
p{{color:#a9a9c2}}
.badge{{display:inline-flex;gap:8px;align-items:center;padding:5px 12px;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:rgba(255,255,255,.04);font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#c9c9dd}}
.dot{{width:8px;height:8px;border-radius:50%;background:{'#34d399' if stats['enabled'] else '#f87171'}}}
table{{width:100%;border-collapse:collapse;margin-top:14px;font-size:14px}}
th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.08);vertical-align:top}}
th{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:#8d8da6}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px;background:rgba(255,255,255,.06);padding:1px 6px;border-radius:6px}}
pre{{background:#0d0d16;border:1px solid rgba(255,255,255,.09);border-radius:14px;padding:16px;overflow:auto}}
pre code{{background:none;padding:0;font-size:12.5px;line-height:1.55}}
.verb{{font-size:10.5px;font-weight:700;letter-spacing:.08em;padding:2px 7px;border-radius:6px}}
.get{{background:rgba(34,211,238,.16);color:#67e8f9}}
.post{{background:rgba(139,92,246,.2);color:#c4b5fd}}
.card{{border:1px solid rgba(255,255,255,.09);background:rgba(19,19,29,.7);border-radius:18px;padding:18px 20px;margin-top:16px}}
ul{{padding-left:20px;color:#a9a9c2}}
a{{color:#93c5fd;text-decoration:none}}
a:hover{{text-decoration:underline}}
small{{color:#6d6d85}}
</style></head>
<body><div class="glow"></div><main>
<span class="badge"><span class="dot"></span> music api · v{runtime.version}</span>
<h1>VYRON Music API</h1>
<p>Downloads, search, metadata and lyrics for Telegram music bots — served from the same
deployment as <strong>@{html_escape(settings.bot_username)}</strong> and the Mini App.
Eldian-compatible: <code>POST /v1/track/by-video-id</code> with an <code>X-API-Key</code> header.</p>

<div class="card">
<strong>Base URL</strong> <code>{html_escape(base)}</code><br/>
<small>{stats['keys']} active key(s) · {stats['requests']} requests served · rate limit
{stats['rate_limit']}/min per key · storage: {html_escape(str(stats['storage']))}</small><br/><br/>
{auth_note}
</div>

<h2>Endpoints</h2>
<table><thead><tr><th>Method</th><th>Path</th><th>What it does</th><th>Key</th></tr></thead>
<tbody>{table}</tbody></table>

<h2>Download a track</h2>
{code(curl_track)}

<h2>Search</h2>
{code(curl_search)}

<h2>Python</h2>
{code(python_sample)}

<h2>Getting a key</h2>
<ul>
  <li>Open the Mini App → <strong>API</strong> tab → <em>Create key</em>.</li>
  <li>Or ask the bot owner: <code>/getapi</code> in a DM, list with <code>/listkey</code>,
      revoke with <code>/revoke &lt;key&gt;</code>.</li>
  <li>Keys live in the same MongoDB as the bot when <code>MONGO_URL</code> is set,
      otherwise in a local JSON file.</li>
</ul>

<p><small>Rate limits are per key. Revoked keys return <code>403</code>; missing keys
<code>401</code>; over-quota requests <code>429</code> with <code>X-RateLimit-Reset</code>.</small></p>
</main></body></html>"""
    return web.Response(text=html, content_type="text/html")


# ── registration ───────────────────────────────────────────────────────────
def register(app: web.Application) -> bool:
    if not settings.music_api:
        return False
    app.router.add_get("/v1", index)
    app.router.add_get("/v1/", index)
    app.router.add_get("/v1/docs", docs)
    app.router.add_get("/v1/openapi.json", openapi)
    app.router.add_get("/v1/health", health)
    app.router.add_post("/v1/track/by-video-id", track_by_video_id)
    app.router.add_get("/v1/track/by-video-id", track_by_video_id)
    app.router.add_post("/v1/track/by-query", track_by_query)
    app.router.add_get("/v1/track/by-query", track_by_query)
    app.router.add_post("/v1/search", search)
    app.router.add_get("/v1/search", search)
    app.router.add_get("/v1/info/by-video-id", info)
    app.router.add_get("/v1/lyrics", lyrics)
    app.router.add_get("/v1/key", me)
    logger.info("music api mounted at /v1 (%s mode)", "open" if settings.music_api_open else "keyed")
    return True


__all__ = ["register"]
