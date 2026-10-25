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


def test_state_survives_a_storage_that_is_down(monkeypatch):
    """A dead collection must cost a section of the payload, not the whole app.

    Production once answered 500 to every `/api/state` for minutes at a time —
    the Mini App could not open at all — because one storage call raised.
    """
    from vyron.runtime import runtime

    class Down:
        def __getattr__(self, name):
            async def boom(*args, **kwargs):
                raise RuntimeError("mongo is down")

            return boom

    monkeypatch.setattr(runtime, "storage", Down(), raising=False)
    token = auth.make_token(-100999, 424242, TOKEN)

    async def scenario(client):
        response = await client.get("/api/state", headers={"X-Vyron-Token": token})
        assert response.status == 200, await response.text()
        body = await response.json()
        assert body["ok"] is True
        assert body["favorites"] == [] and body["history"] == [] and body["playlists"] == []
        assert body["stats"]["chats"] == 0
        # The parts that do not need storage are still there.
        assert body["chat"]["id"] == -100999

    asyncio.run(_with_client(scenario))


def test_json_helper_stringifies_values_it_does_not_know():
    """bson ObjectIds and datetimes used to 500 the endpoint they appeared in."""
    from datetime import datetime

    from vyron.web.server import _json

    response = _json({"when": datetime(2026, 10, 25, 9, 4, 20), "nested": [{"id": object()}]})
    assert response.status == 200
    assert response.content_type == "application/json"
    assert "2026-10-25" in response.text


def test_tracks_skips_a_row_it_cannot_convert():
    from vyron.web import server

    rows = [{"id": "abc", "title": "Kept", "duration": 120}, "not even a dict"]
    titles = [row["title"] for row in server._tracks(rows)]
    assert titles == ["Kept"]


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


def test_the_state_payload_points_at_a_real_avatar_route():
    async def scenario(client):
        token = auth.make_token(-100999, 424242, TOKEN)
        response = await client.post(
            "/api/state", json={"token": token}, headers={"X-Vyron-Token": token}
        )
        body = await response.json()
        assert body["user"]["avatar"] == "/api/avatar"
        assert body["user"]["photo"] == ""  # a signed token carries no picture

    asyncio.run(_with_client(scenario))


def test_the_light_poll_answers_the_live_half_and_then_304s():
    """`/api/now` exists so a 5-second timer is not a full document each time."""

    async def scenario(client):
        assert (await client.get("/api/now")).status == 401

        token = auth.make_token(-100999, 424242, TOKEN)
        headers = {"X-Vyron-Token": token}
        first = await client.get("/api/now", headers=headers)
        assert first.status == 200
        body = await first.json()
        assert body["ok"] is True and body["chat"]["id"] == -100999
        assert body["now"] is None and body["queue"] == []
        assert "version" in body and "settings" in body
        # the heavy lists are deliberately absent
        assert "favorites" not in body and "playlists" not in body and "history" not in body

        tag = first.headers["ETag"]
        assert tag
        again = await client.get("/api/now", headers={**headers, "If-None-Match": tag})
        assert again.status == 304
        assert await again.read() == b""

    asyncio.run(_with_client(scenario))


def test_the_light_poll_reports_playback_once_there_is_some(monkeypatch):
    from vyron.core.queue import ChatState, Track
    from vyron.runtime import runtime

    class Queues:
        def get(self, _chat):
            state = ChatState(
                chat_id=-100999,
                current=Track(id="now1", title="Believer", duration=200),
                playing=True,
                offset=30,
            )
            state.queue = [Track(id="now2", title="Next", duration=100)]
            return state

    class Player:
        queues = Queues()

    monkeypatch.setattr(runtime, "player", Player(), raising=False)

    async def scenario(client):
        token = auth.make_token(-100999, 424242, TOKEN)
        response = await client.get("/api/now", headers={"X-Vyron-Token": token})
        body = await response.json()
        assert body["now"]["title"] == "Believer"
        assert body["now"]["elapsed"] == 30
        assert body["now"]["progress"] == 0.15
        assert len(body["queue"]) == 1

    asyncio.run(_with_client(scenario))


def test_the_avatar_endpoint_serves_the_picture(monkeypatch):
    from vyron.web import avatars

    picture = avatars.Avatar(
        body=b"\xff\xd8\xff\x00" * 8, content_type="image/jpeg", etag='"tag"'
    )
    seen: list[int] = []

    async def fake_avatar_for(user_id, photo=""):
        seen.append(user_id)
        return picture

    monkeypatch.setattr(avatars, "avatar_for", fake_avatar_for)

    async def scenario(client):
        token = auth.make_token(-100999, 424242, TOKEN)
        headers = {"X-Vyron-Token": token}
        response = await client.get("/api/avatar", headers=headers)
        assert response.status == 200
        assert response.headers["Content-Type"].startswith("image/jpeg")
        assert response.headers["Cache-Control"] == "private, max-age=21600"
        assert response.headers["X-Avatar"] == "custom"
        assert await response.read() == picture.body

        # the same picture is one small body, not a re-download
        cached = await client.get("/api/avatar", headers={**headers, "If-None-Match": '"tag"'})
        assert cached.status == 304

    asyncio.run(_with_client(scenario))
    assert seen and seen[0] == 424242


def test_the_avatar_endpoint_admits_when_there_is_no_picture(monkeypatch):
    from vyron.web import avatars

    async def nothing(user_id, photo=""):
        return None

    monkeypatch.setattr(avatars, "avatar_for", nothing)

    async def scenario(client):
        token = auth.make_token(-100999, 424242, TOKEN)
        response = await client.get("/api/avatar", headers={"X-Vyron-Token": token})
        assert response.status == 404
        # do not let a browser cache "no face" forever: people add photos
        assert response.headers["Cache-Control"] == "no-store"

    asyncio.run(_with_client(scenario))


def test_the_avatar_endpoint_is_not_public():
    async def scenario(client):
        response = await client.get("/api/avatar")
        assert response.status == 401

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
    """The served shell is the built bundle — checked by the frontend CI job.

    A source checkout that was never built has no `webapp/dist` (it is a build
    artifact), so this skips instead of failing; the Docker image and the
    frontend workflow both assert the bundle exists.
    """
    from vyron.web.server import WEB_DIR

    page = WEB_DIR / "index.html"   # WEB_DIR *is* dist/ once it has been built
    if not page.is_file():
        pytest.skip("webapp/dist not built — run `npm run build` in frontend/")
    html = page.read_text(encoding="utf-8")
    assert "telegram-web-app.js" in html
    assert "/app/static/assets/" in html
    assert "root" in html
    # installable + no 465 kB visual on the critical path
    assert "manifest.webmanifest" in html
    assert "three-runtime" not in html


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
    if not built.is_file():
        pytest.skip("webapp/dist not built (the frontend CI job asserts the bundle)")


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


def test_client_error_is_journalled_without_a_session():
    """A crash can happen before a Mini App has a session, so this one route
    stays open — but it only ever writes a line and answers `{ok}`."""
    from vyron.core.journal import journal

    journal.clear()

    async def scenario(client):
        crashed = await client.post(
            "/api/client-error",
            json={
                "message": "cannot read properties of undefined",
                "stack": "TypeError at Player.tsx:42",
                "scope": "render",
            },
            headers={"User-Agent": "TelegramBot unit-test"},
        )
        assert crashed.status == 200
        assert (await crashed.json())["ok"] is True

        events = journal.events(levels=["error"], limit=50)
        matching = [event for event in events if "cannot read properties" in event["message"]]
        assert matching, "the crash should be in the journal"
        assert matching[0]["scope"] == "webapp"
        assert "TypeError at Player.tsx:42" in str(matching[0]["meta"]["stack"])
        assert matching[0]["meta"]["at"] == "render"

    asyncio.run(_with_client(scenario))


def test_client_error_survives_a_broken_body():
    async def scenario(client):
        empty = await client.post("/api/client-error", data=b"not json")
        assert empty.status == 200
        assert (await empty.json())["ok"] is True

        huge = await client.post("/api/client-error", json={"message": "x" * 5000, "stack": "y" * 9000})
        assert huge.status == 200

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


# ── rooms: attach from the Mini App (no URL, no browser) ────────────────────
def test_room_attach_requires_admin_and_mints_a_chat_token(monkeypatch):
    from pyrogram.enums import ChatMemberStatus

    from vyron.runtime import runtime

    class FakeMember:
        def __init__(self, status):
            self.status = status

    class FakeBot:
        def __init__(self, status):
            self.status = status
            self.calls: list[tuple[int, int]] = []

        async def get_chat_member(self, chat_id, user_id):
            self.calls.append((chat_id, user_id))
            if self.status is None:
                raise RuntimeError("not a member")
            return FakeMember(self.status)

    chat_id = -1009876543210
    outsider = auth.make_token(0, 555001, TOKEN)

    async def scenario(client):
        admin_bot = FakeBot(ChatMemberStatus.ADMINISTRATOR)
        monkeypatch.setattr(runtime, "bot", admin_bot, raising=False)

        attached = await client.post(
            "/api/room", json={"chat_id": chat_id}, headers={"X-Vyron-Token": outsider}
        )
        body = await attached.json()
        assert attached.status == 200 and body["ok"] is True
        assert body["chat_id"] == chat_id
        who = auth.verify_token(body["token"], TOKEN)
        assert who is not None and who.chat_id == chat_id and who.user_id == 555001
        assert admin_bot.calls == [(chat_id, 555001)]

        # a plain member cannot take over somebody else's room
        monkeypatch.setattr(runtime, "bot", FakeBot(ChatMemberStatus.MEMBER), raising=False)
        denied = await client.post(
            "/api/room", json={"chat_id": chat_id}, headers={"X-Vyron-Token": outsider}
        )
        assert denied.status == 403

        # private chats are not rooms
        private = await client.post(
            "/api/room", json={"chat_id": 555001}, headers={"X-Vyron-Token": outsider}
        )
        assert private.status == 400

        # the endpoint is not a way to probe chats anonymously
        anonymous = await client.post("/api/room", json={"chat_id": chat_id})
        assert anonymous.status == 401

    asyncio.run(_with_client(scenario))


# ── token revocation (epochs) ───────────────────────────────────────────────
def test_revoke_all_kills_older_tokens(tmp_path, monkeypatch):
    from vyron.core import tokens
    from vyron.database import JsonStorage
    from vyron.runtime import runtime

    storage = JsonStorage(settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)
    tokens.reset_cache()

    async def scenario():
        first = auth.make_owner_token(TOKEN, 424242, epoch=await tokens.epoch(424242))
        assert auth.verify_owner_token(first, TOKEN) is not None

        epoch = await tokens.revoke_all(424242)
        assert epoch == 1
        assert (await storage.get_meta("token_epoch:424242")) == 1

        # the old token still parses, but no longer passes the epoch gate
        assert auth.verify_owner_token(first, TOKEN).epoch == 0
        assert not await tokens.accepts(424242, 0)

        second = auth.make_owner_token(TOKEN, 424242, epoch=await tokens.epoch(424242))
        assert await tokens.accepts(424242, auth.verify_owner_token(second, TOKEN).epoch)

        # revocation survives a process restart: a cold cache reads storage
        tokens.reset_cache()
        assert await tokens.epoch(424242) == 1
        assert not await tokens.accepts(424242, 0)

    asyncio.run(scenario())


def test_revoked_owner_token_is_rejected_by_the_api(tmp_path, monkeypatch):
    from vyron.core import tokens
    from vyron.database import JsonStorage
    from vyron.runtime import runtime

    storage = JsonStorage(settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)
    tokens.reset_cache()
    owner_token = auth.make_owner_token(TOKEN, settings.owner_id)

    async def scenario(client):
        before = await client.post("/api/state", json={}, headers={"X-Owner-Token": owner_token})
        assert before.status == 200 and (await before.json())["owner"] is True

        await tokens.revoke_all(settings.owner_id)

        after = await client.post("/api/state", json={}, headers={"X-Owner-Token": owner_token})
        assert after.status == 401

        # the same token through the query parameter path is refused too
        via_query = await client.get(f"/api/keys?ot={owner_token}")
        assert via_query.status == 401

        # ...and through the older `?t=` door as well
        via_t = await client.post(f"/api/state?t={owner_token}", json={})
        assert via_t.status == 401

    asyncio.run(_with_client(scenario))
    tokens.reset_cache()


# ── Mini App playback is mirrored into the DM ───────────────────────────────
def test_web_playback_mirrors_the_poster_to_the_listener(monkeypatch):
    from vyron.core.queue import ChatState, Track
    from vyron.runtime import runtime
    from vyron.web import server
    from vyron.ui import nowplaying

    delivered: list[tuple[int, int, str]] = []

    async def fake_mirror(bot, user_id, state, *, chat_title=""):
        delivered.append((int(user_id), int(state.chat_id), chat_title))

    monkeypatch.setattr(nowplaying, "mirror_to_dm", fake_mirror)

    class _Queues(dict):
        pass

    class _Player:
        def __init__(self, state):
            self.queues = _Queues({-100777: state})

    class _Bot:
        async def get_chat(self, chat_id):
            return type("C", (), {"title": "Listening Room"})()

    state = ChatState(chat_id=-100777)
    state.current = Track(id="x", title="Song", duration=200)
    monkeypatch.setattr(runtime, "player", _Player(state))
    monkeypatch.setattr(runtime, "bot", _Bot())

    user = auth.WebUser(user_id=424242, name="Test", source="init")
    asyncio.run(server._mirror_now_playing(user, -100777))
    assert delivered == [(424242, -100777, "Listening Room")]

    # a DM already shows the card — never send it twice
    delivered.clear()
    asyncio.run(server._mirror_now_playing(user, 424242))
    assert delivered == []


# ── the Mini App is installable and works offline (#14, #16) ─────────────────
def test_service_worker_is_served_with_scope_over_app():
    """A worker under /app/static/ could not control /app/ without the header."""
    from vyron.web.server import WEB_DIR

    if not (WEB_DIR / "sw.js").is_file():
        pytest.skip("webapp/dist not built — run `npm run build` in frontend/")

    async def scenario(client):
        response = await client.get("/app/sw.js")
        assert response.status == 200
        assert "javascript" in response.headers["Content-Type"]
        assert response.headers["Service-Worker-Allowed"] == "/app/"
        # a pinned worker would keep serving an old shell after a deploy
        assert "no-cache" in response.headers["Cache-Control"]
        body = await response.text()
        assert "addEventListener(\"fetch\"" in body
        # state-carrying routes must never be served from the cache
        for prefix in ("/api/", "/v1/", "/audio/"):
            assert prefix in body

    asyncio.run(_with_client(scenario))


def test_manifest_declares_a_real_app():
    import json
    from vyron.web.server import WEB_DIR

    manifest = WEB_DIR / "manifest.webmanifest"
    if not manifest.is_file():
        pytest.skip("webapp/dist not built — run `npm run build` in frontend/")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert data["start_url"] == "/app/" and data["scope"] == "/app/"
    assert data["display"] in {"standalone", "fullscreen", "minimal-ui"}
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(icon.get("purpose") == "maskable" for icon in data["icons"])
    for icon in data["icons"]:
        path = WEB_DIR / icon["src"].removeprefix("/app/static/")
        assert path.is_file(), f"manifest points at a missing icon: {icon['src']}"


# ── /api/stream is not an open proxy (#1) ───────────────────────────────────
def test_stream_does_not_resolve_ids_nobody_was_shown(monkeypatch):
    """A bare YouTube id used to resolve for anyone with a token.

    That made /api/stream a CDN for the whole internet, billed to the host.
    """
    import dataclasses

    from vyron.config import settings as base
    from vyron.web import stream as audio

    # frozen dataclass: swap the whole settings object the module sees
    monkeypatch.setattr(audio, "settings", dataclasses.replace(base, webapp_direct_ids=False))
    audio._REGISTRY.clear()

    class FakeYouTube:
        called = False

        async def resolve(self, url):
            FakeYouTube.called = True
            raise AssertionError("must not resolve an unseen id")

    monkeypatch.setattr(audio.runtime, "youtube", FakeYouTube())
    found = asyncio.run(audio.lookup_playable("dQw4w9WgXcQ", user_id=0))
    assert found is None
    assert FakeYouTube.called is False

    # …and it stays reachable for an id the deployment did show someone
    from vyron.core.queue import Track

    audio.remember(Track(id="dQw4w9WgXcQ", title="Never Gonna Give You Up"))
    assert asyncio.run(audio.lookup_playable("dQw4w9WgXcQ", user_id=0)).title


def test_a_saved_catalogue_track_plays_after_a_restart(monkeypatch):
    """The registry is per-process; a JioSaavn id can be rehydrated by its API.

    Without this, every track a listener saved from the catalogue became
    "unknown track" on the first redeploy — and a free host redeploys often.
    """
    from vyron.core.queue import Track
    from vyron.web import stream as audio

    audio._REGISTRY.clear()
    asked: list[str] = []

    async def by_id(song_id):
        asked.append(song_id)
        return Track(
            id=song_id,
            title="Kesariya",
            url="https://cdn.example/kesariya.mp3",
            source="jiosaavn",
        )

    import vyron.core.jiosaavn as saavn

    monkeypatch.setattr(saavn, "by_id", by_id)
    found = asyncio.run(audio.lookup_playable("FeM7eXKX", user_id=0))

    assert found is not None and found.title == "Kesariya"
    assert asked == ["FeM7eXKX"]
    # …and it is remembered, so the next request never leaves the process
    assert asyncio.run(audio.lookup_playable("FeM7eXKX", user_id=0)).source == "jiosaavn"


def test_a_junk_id_is_still_unknown(monkeypatch):
    import vyron.core.jiosaavn as saavn
    from vyron.web import stream as audio

    audio._REGISTRY.clear()

    async def by_id(song_id):
        return None

    monkeypatch.setattr(saavn, "by_id", by_id)
    assert asyncio.run(audio.lookup_playable("not-a-song", user_id=0)) is None


def test_the_same_track_again_is_not_a_new_stream():
    """The production loop: 429 → the browser retries → the retry is refused.

    One listener on one song was reaching the per-minute limit, because every
    re-request (a seek, a pause toggle, a retry after a 429) counted as a fresh
    track. A repeat of the same track is the same stream.
    """
    from vyron.web.budget import Budget, BudgetExceeded

    budget = Budget(per_minute=2, per_hour=10, per_user=2, total=3)
    budget.check("u1", media="a")
    budget.start("u1", media="a")
    for _ in range(20):                     # seeks, retries, lock-screen toggles
        budget.check("u1", media="a")
        budget.start("u1", media="a")
    budget.check("u1", media="b")           # a real new track still counts
    budget.start("u1", media="b")
    with pytest.raises(BudgetExceeded):
        budget.check("u1", media="c")
    # …and the track that was refused is not refused on its *repeat*
    budget.check("u1", media="a")


def test_a_repeat_expires_so_the_hour_limit_still_means_something():
    from vyron.web import budget as module

    budget = module.Budget(per_minute=5, per_hour=1, per_user=2, total=3)
    budget.start("u1", now=0.0, media="a")
    budget.check("u1", now=10.0, media="a")      # still the same stream
    budget.start("u1", now=10.0, media="a")      # …and not counted twice
    with pytest.raises(module.BudgetExceeded):
        # After the repeat window it is a new stream again, so the hourly
        # limit (1) applies to it exactly as it would to any other track.
        budget.check("u1", now=module.REPEAT_WINDOW + 20.0, media="a")


def test_stream_budget_counts_starts_and_slots():
    from vyron.web.budget import Budget, BudgetExceeded

    budget = Budget(per_minute=3, per_hour=5, per_user=2, total=3)
    for _ in range(3):
        budget.check("u1")
        budget.start("u1")
    with pytest.raises(BudgetExceeded) as caught:
        budget.check("u1")
    assert caught.value.retry_after >= 1
    # the minute window is per identity: somebody else is unaffected
    budget.check("u2")

    budget.take_slot("u1")
    budget.take_slot("u1")
    with pytest.raises(BudgetExceeded, match="at once"):
        budget.take_slot("u1")
    budget.drop_slot("u1")
    budget.take_slot("u1")          # the slot came back

    budget.take_slot("u2")
    with pytest.raises(BudgetExceeded, match="capacity"):
        budget.take_slot("u3")
    assert budget.snapshot()["active"] == 3


def test_stream_answers_429_with_retry_after(monkeypatch):
    from vyron.web import stream as audio
    from vyron.web.budget import BudgetExceeded

    audio.BUDGET.reset()

    def refuse(key, **kwargs):
        raise BudgetExceeded("hourly streaming limit reached", 42)

    monkeypatch.setattr(audio.BUDGET, "check", refuse)

    async def scenario(client):
        token = auth.make_token(-100777, 424242, TOKEN)
        response = await client.get(
            "/api/stream/dQw4w9WgXcQ", headers={"X-Vyron-Token": token}
        )
        assert response.status == 429
        assert response.headers["Retry-After"] == "42"
        payload = await response.json()
        assert payload["error"] == "rate_limited" and payload["retry_after"] == 42

    asyncio.run(_with_client(scenario))


def test_a_revocation_only_kills_tokens_minted_before_it(tmp_path):
    """Revoking must not lock the owner out of their own console.

    The epoch is monotonic; a token minted after the bump carries a *higher*
    epoch and has to keep working. Equality rejected it forever, which is how
    a `/revoke` left the owner with a 401 on every fresh token.
    """
    from vyron.config import Settings
    from vyron.core import tokens
    from vyron.database import JsonStorage
    from vyron.runtime import runtime

    storage = JsonStorage(dataclasses.replace(Settings(), data_dir=tmp_path))
    asyncio.run(storage.connect())
    previous, runtime.storage = runtime.storage, storage
    tokens.reset_cache()
    try:
        old = auth.make_owner_token(TOKEN, 424242, epoch=0)
        assert asyncio.run(tokens.accepts(424242, 0)) is True

        new_epoch = asyncio.run(tokens.revoke_all(424242))
        assert new_epoch == 1
        assert asyncio.run(tokens.accepts(424242, 0)) is False  # old token dead
        assert asyncio.run(tokens.accepts(424242, 1)) is True   # fresh one alive

        fresh = auth.make_owner_token(TOKEN, 424242, epoch=new_epoch)
        assert fresh != old
        assert auth.verify_owner_token(fresh, TOKEN, expected_epoch=1) is not None
        assert auth.verify_owner_token(old, TOKEN, expected_epoch=1) is None
    finally:
        runtime.storage = previous
        tokens.reset_cache()


def test_a_lookup_miss_is_not_asked_twice(monkeypatch):
    """One tap used to cost a storage round trip *and* an 8 s catalogue call,
    every single time, for an id that will never resolve.

    The Mini App asks `/api/audio/<id>` then `/api/stream/<id>`, and each poll
    repeated the whole fan-out: Render measured 29.7 s on a request that
    returned 404 in the end.
    """
    import vyron.core.jiosaavn as saavn
    from vyron.web import stream as audio

    audio._REGISTRY.clear()
    audio._LOOKUPS.clear()
    asked: list[str] = []

    async def by_id(song_id):
        asked.append(song_id)
        return None

    monkeypatch.setattr(saavn, "by_id", by_id)
    monkeypatch.setattr(audio.runtime, "youtube", None)
    monkeypatch.setattr(audio.runtime, "storage", None)

    assert asyncio.run(audio.lookup_playable("5dAAl81", user_id=7)) is None
    assert asyncio.run(audio.lookup_playable("5dAAl81", user_id=7)) is None
    assert asked == ["5dAAl81"], "a cached miss must not be asked again"

    # …but a song that is in the registry always wins, even over a cached miss.
    from vyron.core.queue import Track

    audio.remember(Track(id="5dAAl81", title="Now Known"))
    assert asyncio.run(audio.lookup_playable("5dAAl81", user_id=7)).title == "Now Known"
    audio._LOOKUPS.clear()
    audio._REGISTRY.clear()


def test_the_title_lookup_never_addresses_peer_zero(monkeypatch):
    """`Peer id invalid: 0` came from asking Telegram for chat 0.

    A token minted without a chat context resolves to peer 0, and Telegram
    answers that with an error. There is no title to fetch, so it is not
    fetched — and a failed lookup is remembered, so a polling app does not
    re-pay a 3-second timeout on every tick.
    """
    from vyron.web import server
    from vyron.runtime import runtime

    calls: list[int] = []

    class Bot:
        async def get_chat(self, chat_id):
            calls.append(chat_id)
            raise RuntimeError(f"Peer id invalid: {chat_id}")

    monkeypatch.setattr(runtime, "bot", Bot())
    server._TITLE_CACHE.clear()

    assert asyncio.run(server._chat_title(0)) == ""
    assert calls == [], "peer 0 must never be asked for"

    assert asyncio.run(server._chat_title(-100123)) == ""
    assert asyncio.run(server._chat_title(-100123)) == ""
    assert calls == [-100123], "a known-bad chat is retried in a minute, not per poll"
    server._TITLE_CACHE.clear()


def test_state_answers_a_degraded_app_instead_of_a_500(monkeypatch):
    """The Mini App's whole first paint comes from one endpoint.

    Whatever goes wrong inside it — this monkeypatch stands in for any of the
    fan-out's parts misbehaving — the app must still get a document to render,
    not a blank screen and a console error.
    """
    from vyron.web import server

    async def boom(request):
        raise RuntimeError("a bug in the payload")

    monkeypatch.setattr(server, "_state_response", boom)
    token = auth.make_token(-100999, 424242, TOKEN)

    async def scenario(client):
        response = await client.get("/api/state", headers={"X-Vyron-Token": token})
        assert response.status == 200, await response.text()
        body = await response.json()
        assert body["ok"] is True and body["degraded"] is True
        assert body["now"] is None and body["queue"] == []

    asyncio.run(_with_client(scenario))


# ── language, from the app ─────────────────────────────────────────────────
def test_the_state_carries_every_language_the_bot_speaks():
    async def scenario(client):
        token = auth.make_token(-100999, 424242, TOKEN)
        response = await client.post(
            "/api/state", json={"token": token}, headers={"X-Vyron-Token": token}
        )
        language = (await response.json())["language"]
        assert language["code"] == "en" and language["name"] == "English"
        codes = {item["code"] for item in language["available"]}
        assert {"hi", "ml", "pa", "bn", "ta", "te", "kn", "mr", "gu", "ur"} <= codes
        assert {"es", "fr", "de", "pt", "ru", "id", "ar", "tr"} <= codes
        arabic = next(item for item in language["available"] if item["code"] == "ar")
        assert arabic["rtl"] is True

    asyncio.run(_with_client(scenario))


def test_the_app_can_change_its_own_language(tmp_path, monkeypatch):
    from vyron.config import settings as live_settings
    from vyron.database import JsonStorage
    from vyron.runtime import runtime

    storage = JsonStorage(live_settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)
    monkeypatch.setattr(runtime, "player", None)

    async def scenario(client):
        # 424242 is the user, so this is a private chat: no admin to ask.
        headers = {"X-Vyron-Token": auth.make_token(424242, 424242, TOKEN)}
        response = await client.post(
            "/api/action", json={"action": "language", "value": "ta"}, headers=headers
        )
        assert response.status == 200, await response.text()
        payload = await response.json()
        assert payload["ok"] is True and payload["lang"] == "ta"
        assert payload["name"] == "தமிழ்"

        # …and the next poll already speaks it.
        state = await client.post("/api/state", json={}, headers=headers)
        assert (await state.json())["language"]["code"] == "ta"

        unknown = await client.post(
            "/api/action", json={"action": "language", "value": "klingon"}, headers=headers
        )
        assert unknown.status == 400
        assert (await unknown.json())["ok"] is False

    asyncio.run(_with_client(scenario))


def test_a_group_language_is_an_owner_decision_in_the_app(tmp_path, monkeypatch):
    from vyron.config import settings as live_settings
    from vyron.database import JsonStorage
    from vyron.runtime import runtime

    storage = JsonStorage(live_settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)
    monkeypatch.setattr(runtime, "player", None)

    async def scenario(client):
        # 424242 is the owner in the test environment; a listener is not.
        listener = {"X-Vyron-Token": auth.make_token(-100777, 555001, TOKEN)}
        response = await client.post(
            "/api/action", json={"action": "language", "value": "hi"}, headers=listener
        )
        assert response.status == 403
        assert "admin" in (await response.json())["error"]

        owner = {"X-Vyron-Token": auth.make_token(-100777, 424242, TOKEN)}
        allowed = await client.post(
            "/api/action", json={"action": "language", "value": "hi"}, headers=owner
        )
        assert allowed.status == 200 and (await allowed.json())["lang"] == "hi"

    asyncio.run(_with_client(scenario))
