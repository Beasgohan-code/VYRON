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
        assert isinstance(payload["trending"], list)
        assert isinstance(payload["shelves"], list) and isinstance(payload["moods"], list)
        # without a chart service the payload is honest about being empty
        if not payload.get("ready", True):
            assert payload["trending"] == [] and payload["shelves"] == []
        else:
            assert payload["trending"] and {"key", "title", "tracks"} <= set(payload["shelves"][0])

    asyncio.run(_with_client(scenario))


def test_rooms_endpoint_shape():
    async def scenario(client):
        token = auth.make_token(-100556, 424242, TOKEN)
        response = await client.get("/api/rooms", headers={"X-Vyron-Token": token})
        payload = await response.json()
        assert response.status == 200 and payload["ok"] is True
        assert isinstance(payload["rooms"], list)
        for room in payload["rooms"]:
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

    artwork = (frontend / "src" / "components" / "Cover.tsx").read_text(encoding="utf-8")
    assert "svg" in artwork.lower() or "gradient" in artwork.lower(), "procedural artwork missing"

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


def test_stream_head_probe_reports_the_real_mime(monkeypatch, tmp_path):
    """HEAD must answer cheaply, with the format's own mime — not audio/mpeg."""
    from vyron.core.queue import Track
    from vyron.core.search import StreamInfo
    from vyron.runtime import runtime
    from vyron.web import stream as audio

    monkeypatch.setattr(audio, "settings", dataclasses.replace(audio.settings, webapp_allow_anon=True))
    audio.remember(Track(id="abcdefghijk", title="WebM song", duration=200))

    class FakeYouTube:
        def __init__(self):
            self.calls = 0

        async def stream_info(self, track, *, video=False, refresh=False):
            self.calls += 1
            return StreamInfo(url="https://media.invalid/x", mime="audio/webm", ext="webm")

    fake = FakeYouTube()
    monkeypatch.setattr(runtime, "youtube", fake, raising=False)

    async def scenario():
        app = build_app(with_webapp=False)
        audio.register(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.head("/api/stream/abcdefghijk")
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("audio/webm")
            assert response.headers["Accept-Ranges"] == "bytes"
            assert await response.read() == b""
        assert fake.calls == 1

    asyncio.run(scenario())


def test_stream_reports_expired_source_instead_of_playing_a_fake_tone(monkeypatch):
    """A browser must get a real error, not 24 seconds of synth beeps."""
    from vyron.core.queue import Track
    from vyron.core.search import StreamInfo
    from vyron.runtime import runtime
    from vyron.web import stream as audio

    monkeypatch.setattr(audio, "settings", dataclasses.replace(audio.settings, webapp_allow_anon=True))
    audio.remember(Track(id="zzzzzzzzzzz", title="Gone", duration=200))

    class ExpiringYouTube:
        async def stream_info(self, track, *, video=False, refresh=False):
            return StreamInfo(url="https://media.invalid/gone", mime="audio/mp4")

    async def fake_proxy(request, info):
        raise audio.UpstreamExpired("403")

    monkeypatch.setattr(runtime, "youtube", ExpiringYouTube(), raising=False)
    monkeypatch.setattr(audio, "_proxy_range", fake_proxy)

    async def scenario():
        app = build_app(with_webapp=False)
        audio.register(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/stream/zzzzzzzzzzz")
            assert response.status == 502
            payload = await response.json()
            assert payload["error"] == "upstream_failed"
            assert "fake" not in payload and payload["hint"]

    asyncio.run(scenario())


def test_audio_info_says_when_streaming_is_not_configured(monkeypatch, tmp_path):
    from vyron.core.queue import Track
    from vyron.runtime import runtime
    from vyron.web import stream as audio

    monkeypatch.setattr(audio, "settings", dataclasses.replace(audio.settings, webapp_allow_anon=True))
    monkeypatch.setattr(runtime, "youtube", None, raising=False)
    monkeypatch.setattr(runtime, "downloader", None, raising=False)
    audio.remember(Track(id="yyyyyyyyyyy", title="Nothing", duration=100))

    async def scenario():
        app = build_app(with_webapp=False)
        audio.register(app)
        async with TestClient(TestServer(app)) as client:
            payload = await (await client.get("/api/audio/yyyyyyyyyyy")).json()
            assert payload["playable"] is False
            assert "reason" in payload

    asyncio.run(scenario())


def test_stream_resolver_crash_is_json_not_a_500(monkeypatch):
    """A resolver bug must degrade to a readable error, never an HTML 500."""
    from vyron.core.queue import Track
    from vyron.runtime import runtime
    from vyron.web import stream as audio

    monkeypatch.setattr(audio, "settings", dataclasses.replace(audio.settings, webapp_allow_anon=True))
    monkeypatch.setattr(runtime, "downloader", None, raising=False)
    audio.remember(Track(id="crashcrash1", title="Crash", duration=200))

    class BrokenYouTube:
        async def stream_info(self, track, *, video=False, refresh=False):
            raise RuntimeError("yt-dlp exploded")

    monkeypatch.setattr(runtime, "youtube", BrokenYouTube(), raising=False)

    async def scenario():
        app = build_app(with_webapp=False)
        audio.register(app)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/api/stream/crashcrash1")
            assert response.status == 502
            payload = await response.json()
            assert payload["error"] == "upstream_failed" and payload["hint"]

    asyncio.run(scenario())


def test_content_disposition_survives_any_title():
    """A non-latin-1 title must not turn a download into a 500."""
    from vyron.api.routes import content_disposition

    for title in ["Believer", "Песня 📀", 'bad "quote" / slash', "line\nbreak"]:
        header = content_disposition(title, "dQw4w9WgXcQ")
        header.encode("latin-1")  # would raise before the fix
        assert header.startswith("attachment; filename=\"")
        assert "filename*=UTF-8''" in header
    inline = content_disposition("Believer", "dQw4w9WgXcQ", inline=True)
    assert inline.startswith("inline;")


# ── owner access ────────────────────────────────────────────────────────────
def test_owner_token_roundtrip_and_expiry():
    token = auth.make_owner_token(TOKEN, 424242)
    assert token.startswith(auth.OWNER_TOKEN_PREFIX)
    who = auth.verify_owner_token(token, TOKEN)
    assert who is not None and who.owner and who.user_id == 424242

    assert auth.verify_owner_token(token, "other-token") is None
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert auth.verify_owner_token(tampered, TOKEN) is None
    expired = auth.make_owner_token(TOKEN, 424242, ttl=-5)
    assert auth.verify_owner_token(expired, TOKEN) is None


def test_owner_token_grants_web_app_access_without_telegram():
    owner_token = auth.make_owner_token(TOKEN, settings.owner_id)

    async def scenario(client):
        state = await client.post("/api/state", json={}, headers={"X-Owner-Token": owner_token})
        body = await state.json()
        assert state.status == 200 and body["ok"] is True
        assert body["owner"] is True and body["user"]["owner"] is True

        via_query = await client.post(f"/api/state?ot={owner_token}", json={})
        assert via_query.status == 200

        # an owner token for somebody else is rejected
        stranger = auth.make_owner_token(TOKEN, 999999)
        denied = await client.post("/api/state", json={}, headers={"X-Owner-Token": stranger})
        assert denied.status == 401

        # keys console opens for the owner
        keys = await client.get("/api/keys", headers={"X-Owner-Token": owner_token})
        payload = await keys.json()
        assert keys.status == 200 and payload["is_owner"] is True
        assert "keys" in payload and "base" in payload

    asyncio.run(_with_client(scenario))


def test_api_console_key_lifecycle_for_the_owner(monkeypatch):
    from vyron.core import musicapi as core

    monkeypatch.setattr(core, "_api", None)  # isolated in-memory key store
    owner_token = auth.make_owner_token(TOKEN, settings.owner_id)
    headers = {"X-Owner-Token": owner_token, "X-Vyron-Token": ""}

    async def scenario(client):
        created = await client.post("/api/keys", json={"action": "create", "label": "ci"}, headers=headers)
        body = await created.json()
        assert created.status == 200 and body["created"]["key"].startswith("vyrn_")

        listing = await (await client.get("/api/keys", headers=headers)).json()
        assert listing["is_owner"] is True and listing["keys"]

        revoked = await client.post(
            "/api/keys", json={"action": "revoke", "id": listing["keys"][0]["id"]}, headers=headers
        )
        assert (await revoked.json())["revoked"] is True

    asyncio.run(_with_client(scenario))


def test_api_console_blocks_non_owners_from_minting():
    token = auth.make_token(0, 555001, TOKEN)  # not OWNER_ID

    async def scenario(client):
        listed = await client.get("/api/keys", headers={"X-Vyron-Token": token})
        payload = await listed.json()
        assert listed.status == 200 and payload["is_owner"] is False and payload["keys"] == []

        denied = await client.post("/api/keys", json={"action": "create"}, headers={"X-Vyron-Token": token})
        assert denied.status == 403

    asyncio.run(_with_client(scenario))


# ── owner journal API ───────────────────────────────────────────────────────
def test_logs_endpoint_is_owner_only():
    from vyron.web.auth import make_owner_token

    async def scenario(client):
        anonymous = await client.get("/api/logs")
        assert anonymous.status == 403
        body = await anonymous.json()
        assert body["ok"] is False

        owner_id = next(iter(settings.owners))
        token = make_owner_token(TOKEN, owner_id)
        allowed = await client.get("/api/logs", headers={"X-Owner-Token": token})
        assert allowed.status == 200
        payload = await allowed.json()
        assert payload["ok"] is True
        assert isinstance(payload["events"], list)
        assert "system" in payload and "stats" in payload

    asyncio.run(_with_client(scenario))


def test_logs_endpoint_records_and_filters():
    from vyron.core.journal import journal
    from vyron.web.auth import make_owner_token

    journal.clear()
    journal.error("player", "unit-test boom")
    journal.info("boot", "unit-test boot")

    async def scenario(client):
        owner_id = next(iter(settings.owners))
        token = make_owner_token(TOKEN, owner_id)
        headers = {"X-Owner-Token": token}

        everything = await (await client.get("/api/logs?level=all", headers=headers)).json()
        assert any("unit-test boom" in event["message"] for event in everything["events"])

        errors = await (await client.get("/api/logs?level=error", headers=headers)).json()
        assert {event["level"] for event in errors["events"]} == {"error"}

        scoped = await (await client.get("/api/logs?scope=boot", headers=headers)).json()
        assert {event["scope"] for event in scoped["events"]} == {"boot"}

    asyncio.run(_with_client(scenario))


def test_logs_action_clear_is_owner_only():
    from vyron.web.auth import make_owner_token

    async def scenario(client):
        assert (await client.post("/api/logs", json={"action": "clear"})).status == 403

        owner_id = next(iter(settings.owners))
        token = make_owner_token(TOKEN, owner_id)
        response = await client.post(
            "/api/logs", json={"action": "clear"}, headers={"X-Owner-Token": token}
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["ok"] is True and "stats" in payload

    asyncio.run(_with_client(scenario))
