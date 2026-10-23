"""Web app auth + API tests (no Telegram, no network)."""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pyrogram")

from aiohttp.test_utils import TestClient, TestServer

from vyron.config import settings
from vyron.utils.health import build_app
from vyron.web import auth

TOKEN = settings.bot_token


def _secret() -> bytes:
    return hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()


def signed_init_data(user_id: int = 424242, name: str = "Test User") -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": name, "username": "tester"}),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    fields["hash"] = hmac.new(_secret(), check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


# ── auth primitives ─────────────────────────────────────────────────────────
def test_token_roundtrip():
    token = auth.make_token(-1001234567890, 42, TOKEN, ttl=60)
    user = auth.verify_token(token, TOKEN)
    assert user is not None
    assert user.chat_id == -1001234567890 and user.user_id == 42


def test_token_rejects_tampering_and_expiry():
    assert auth.verify_token(auth.make_token(-100, 42, TOKEN, ttl=-1), TOKEN) is None
    valid = auth.make_token(-100, 42, TOKEN)
    tampered = valid[:-1] + ("0" if valid[-1] != "0" else "1")
    assert auth.verify_token(tampered, TOKEN) is None
    assert auth.verify_token(valid, "different-token") is None


def test_verify_init_data():
    good = signed_init_data()
    user = auth.verify_init_data(good, TOKEN)
    assert user is not None and user.user_id == 424242
    assert auth.verify_init_data(good.replace("424242", "424243"), TOKEN) is None
    assert auth.verify_init_data("", TOKEN) is None


def test_resolve_user_prefers_signed_chat_token():
    token = auth.make_token(-100777, 424242, TOKEN)
    user = auth.resolve_user(init_data=signed_init_data(), token=token, bot_token=TOKEN)
    assert user.chat_id == -100777
    assert user.name == "Test User"  # profile copied from initData


def test_resolve_user_without_credentials():
    assert auth.resolve_user(init_data="", token="", bot_token=TOKEN).authenticated is False
    anon = auth.resolve_user(init_data="", token="", bot_token=TOKEN, allow_anon=True)
    assert anon.source == "anon"


# ── HTTP surface ────────────────────────────────────────────────────────────
async def _with_client(scenario):
    app = build_app(with_webapp=True)
    async with TestClient(TestServer(app)) as client:
        return await scenario(client)


def test_info_endpoint():
    async def scenario(client):
        response = await client.get("/api/info")
        payload = await response.json()
        assert response.status == 200
        assert payload["ok"] is True and payload["bot"]

    asyncio.run(_with_client(scenario))


def test_state_requires_auth():
    async def scenario(client):
        anonymous = await client.post("/api/state", json={})
        assert anonymous.status == 401
        payload = await anonymous.json()
        assert payload["ok"] is False and payload["error"] == "unauthorized"

        token = auth.make_token(-100999, 424242, TOKEN)
        authorised = await client.post(
            "/api/state", json={"token": token}, headers={"X-Vyron-Token": token}
        )
        assert authorised.status == 200
        body = await authorised.json()
        assert body["ok"] is True
        assert body["chat"]["id"] == -100999
        assert body["now"] is None and body["queue"] == []

    asyncio.run(_with_client(scenario))


def test_action_requires_auth():
    async def scenario(client):
        response = await client.post("/api/action", json={"action": "pause"})
        assert response.status == 401

    asyncio.run(_with_client(scenario))


def test_health_endpoint():
    async def scenario(client):
        response = await client.get("/health")
        assert response.status in (200, 503)
        payload = await response.json()
        assert "ok" in payload

    asyncio.run(_with_client(scenario))


def test_app_shell_is_served():
    from vyron.web.server import WEB_DIR

    page = WEB_DIR / "index.html"
    assert page.is_file(), "built Mini App missing — run `npm run build` in frontend/"
    html = page.read_text(encoding="utf-8")
    assert "telegram-web-app.js" in html
    assert "/app/static/assets/" in html
    assert "root" in html


# ── discovery / rooms / playlists ───────────────────────────────────────────
def test_home_endpoint_shape():
    async def scenario(client):
        token = auth.make_token(-100555, 424242, TOKEN)
        response = await client.get("/api/home", headers={"X-Vyron-Token": token})
        payload = await response.json()
        assert response.status == 200 and payload["ok"] is True
        assert payload["hero"]["headline"]
        assert isinstance(payload["trending"], list) and payload["trending"]
        assert {"key", "title", "tracks"} <= set(payload["shelves"][0])
        assert payload["moods"]

    asyncio.run(_with_client(scenario))


def test_rooms_endpoint_shape():
    async def scenario(client):
        token = auth.make_token(-100556, 424242, TOKEN)
        response = await client.get("/api/rooms", headers={"X-Vyron-Token": token})
        payload = await response.json()
        assert response.status == 200 and payload["ok"] is True
        room = payload["rooms"][0]
        assert {"chat_id", "title", "listeners", "playing", "track"} <= set(room)

    asyncio.run(_with_client(scenario))


def test_playlists_endpoint_requires_auth():
    async def scenario(client):
        assert (await client.get("/api/playlists")).status == 401

    asyncio.run(_with_client(scenario))


def test_mix_endpoint():
    async def scenario(client):
        token = auth.make_token(-100557, 424242, TOKEN)
        response = await client.get("/api/mix?key=daily", headers={"X-Vyron-Token": token})
        payload = await response.json()
        assert response.status == 200 and payload["ok"] is True
        assert isinstance(payload["tracks"], list)

    asyncio.run(_with_client(scenario))


def test_search_endpoint_without_query_is_empty():
    async def scenario(client):
        token = auth.make_token(-100558, 424242, TOKEN)
        response = await client.post("/api/search", json={}, headers={"X-Vyron-Token": token})
        payload = await response.json()
        assert payload == {"ok": True, "results": []}

    asyncio.run(_with_client(scenario))


# ── playlist storage round-trip (web actions) ──────────────────────────────
def test_playlist_actions_roundtrip(tmp_path, monkeypatch):
    from vyron.config import settings as live_settings
    from vyron.database import JsonStorage
    from vyron.runtime import runtime

    storage = JsonStorage(live_settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)
    monkeypatch.setattr(runtime, "player", None)

    async def scenario(client):
        headers = {"X-Vyron-Token": auth.make_token(-100559, 424242, TOKEN)}

        created = await client.post(
            "/api/action", json={"action": "playlist_create", "value": "Road Trip"}, headers=headers
        )
        payload = await created.json()
        assert payload["ok"] is True
        playlist_id = payload["playlist"]["id"]

        track = {
            "id": "abc12345678",
            "title": "Song",
            "duration": 200,
            "uploader": "Artist",
            "thumbnail": "",
            "source": "youtube",
        }
        added = await client.post(
            "/api/action",
            json={"action": "playlist_add", "value": {"playlist_id": playlist_id, "track": track}},
            headers=headers,
        )
        assert (await added.json())["ok"] is True

        listing = await client.get("/api/playlists", headers=headers)
        playlists = (await listing.json())["playlists"]
        assert playlists[0]["name"] == "Road Trip"
        assert playlists[0]["count"] == 1

        removed = await client.post(
            "/api/action",
            json={"action": "playlist_delete", "value": playlist_id},
            headers=headers,
        )
        assert (await removed.json())["ok"] is True
        assert (await (await client.get("/api/playlists", headers=headers)).json())["playlists"] == []

    asyncio.run(_with_client(scenario))


def test_action_unknown_name_is_rejected():
    async def scenario(client):
        headers = {"X-Vyron-Token": auth.make_token(-100560, 424242, TOKEN)}
        response = await client.post("/api/action", json={"action": "definitely-not-a-thing"}, headers=headers)
        assert response.status == 400
        payload = await response.json()
        assert payload["ok"] is False and "playlist_create" in payload["actions"]

    asyncio.run(_with_client(scenario))


def test_frontend_sources_exist():
    """The React app is the source of truth; dist/ is the built bundle."""
    root = Path(__file__).resolve().parent.parent
    frontend = root / "frontend"
    for name in ("package.json", "vite.config.ts", "src/App.tsx", "src/main.tsx", "src/styles.css"):
        assert (frontend / name).is_file(), f"frontend/{name} missing"

    views = sorted((frontend / "src" / "views").glob("*.tsx"))
    assert len(views) >= 7, "expected a view per screen"

    sources = "\n".join(path.read_text(encoding="utf-8") for path in views)
    for needle in ("home", "search", "library", "queue", "playlists", "rooms", "profile"):
        assert needle.lower() in sources.lower()

    api_source = (frontend / "src" / "lib" / "api.ts").read_text(encoding="utf-8")
    for endpoint in ("/api/state", "/api/home", "/api/playlists", "/api/rooms", "/api/action"):
        assert endpoint in api_source

    covers = sorted((frontend / "public" / "covers").glob("*.jpg"))
    assert len(covers) >= 8, "fallback artwork missing"

    built = root / "webapp" / "dist" / "index.html"
    assert built.is_file(), "webapp/dist not built"


# ── in-app audio ───────────────────────────────────────────────────────────
def test_track_registry_is_bounded_and_looked_up():
    from vyron.core.queue import Track
    from vyron.web import stream as audio

    for index in range(audio.MAX_REGISTRY + 25):
        audio.remember(Track(id=f"reg{index}", title=f"t{index}"))

    assert audio.registry_size() <= audio.MAX_REGISTRY
    assert audio.lookup("reg9999") is None
    newest = audio.lookup(f"reg{audio.MAX_REGISTRY + 24}")
    assert newest is not None and newest.title.startswith("t")


def test_registry_ignores_untitled_entries():
    from vyron.core.queue import Track
    from vyron.web import stream as audio

    before = audio.registry_size()
    audio.remember(None, Track(id="", title="no id"))
    assert audio.registry_size() == before


def test_demo_audio_is_a_valid_wav_and_is_cached(tmp_path, monkeypatch):
    import wave

    from vyron.web import stream as audio

    monkeypatch.setattr(
        audio, "settings", dataclasses.replace(audio.settings, data_dir=tmp_path)
    )
    path = audio.demo_audio("demo03")
    assert path.is_file() and path.stat().st_size > 2048
    with wave.open(str(path)) as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16000
        assert handle.getnframes() > 16000 * 10

    # second call reuses the file instead of re-synthesising
    stamp = path.stat().st_mtime_ns
    assert audio.demo_audio("demo03").stat().st_mtime_ns == stamp


def test_stream_route_serves_demo_audio_to_an_anonymous_visitor(tmp_path, monkeypatch):
    """The preview must be able to play without Telegram or network access."""
    from vyron.web import stream as audio

    monkeypatch.setattr(
        audio, "settings", dataclasses.replace(audio.settings, data_dir=tmp_path, webapp_allow_anon=True)
    )

    async def scenario():
        app = build_app(with_webapp=False)
        audio.register(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/stream/demo05")
            assert response.status == 200
            assert response.content_type == "audio/wav"
            body = await response.read()
            assert body[:4] == b"RIFF" and len(body) > 40_000

            info = await client.get("/api/audio/demo05")
            payload = await info.json()
            assert payload["ok"] and payload["demo"] is True

    asyncio.run(scenario())


def test_stream_rejects_unknown_tracks(tmp_path, monkeypatch):
    from vyron.web import stream as audio

    monkeypatch.setattr(
        audio, "settings", dataclasses.replace(audio.settings, data_dir=tmp_path, webapp_allow_anon=True)
    )

    async def scenario():
        app = build_app(with_webapp=False)
        audio.register(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/stream/does-not-exist")
            assert response.status == 404
            body = await response.json()
            assert body["ok"] is False

    asyncio.run(scenario())
