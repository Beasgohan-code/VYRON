"""Music API tests — keys, scopes, auth, rate limits and the /v1 HTTP surface."""
from __future__ import annotations

import asyncio
import dataclasses
import time

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pyrogram")

from aiohttp.test_utils import TestClient, TestServer

from vyron.config import settings
from vyron.core.musicapi import (
    DEFAULT_SCOPES,
    MAX_KEYS_PER_OWNER,
    MusicAPI,
    generate_key,
    hash_key,
    looks_like_key,
    mask_key,
    normalise_scopes,
)
from vyron.core.queue import Track
from vyron.database import JsonStorage
from vyron.runtime import runtime
from vyron.utils.health import build_app


def _storage(tmp_path) -> JsonStorage:
    return JsonStorage(dataclasses.replace(settings, data_dir=tmp_path))


def _api(tmp_path, monkeypatch, **overrides) -> tuple[MusicAPI, JsonStorage]:
    storage = _storage(tmp_path)
    asyncio.run(storage.connect())
    monkeypatch.setattr(MusicAPI, "_storage", staticmethod(lambda: storage))
    api = MusicAPI(settings=dataclasses.replace(settings, **overrides))
    return api, storage


# ── keys ────────────────────────────────────────────────────────────────────
def test_key_shape_and_mask():
    key = generate_key()
    assert key.startswith("vyrn_") and len(key) > 30
    assert looks_like_key(key)
    assert not looks_like_key("hello")
    masked = mask_key(key)
    assert masked.startswith("vyrn_") and "…" in masked and key not in masked
    assert hash_key(key) != key and len(hash_key(key)) == 64


def test_scope_normalisation():
    assert normalise_scopes(None) == list(DEFAULT_SCOPES)
    assert normalise_scopes("read,search") == ["read", "search"]
    assert normalise_scopes(["admin"]) == ["read", "search", "download", "admin"]
    assert normalise_scopes("nonsense") == list(DEFAULT_SCOPES)


def test_issue_authenticate_and_revoke(tmp_path, monkeypatch):
    api, storage = _api(tmp_path, monkeypatch)

    async def scenario():
        record, error = await api.issue(424242, "unit")
        assert record is not None and error == ""
        raw = record["key"]
        assert record["scopes"] == list(DEFAULT_SCOPES)

        ok = await api.authenticate(raw)
        assert ok.ok and ok.record["label"] == "unit"
        assert ok.limit == settings.music_api_rate
        assert ok.has("download") and not ok.has("admin")

        listed = await api.keys(424242)
        assert len(listed) == 1
        assert listed[0]["masked"].endswith("…") and raw not in listed[0]["masked"]
        assert "hash" not in listed[0] and "key" not in listed[0]

        assert await api.revoke(999, raw) is False  # someone else's key
        assert await api.revoke(424242, raw) is True

        revoked = await api.authenticate(raw)
        assert not revoked.ok and revoked.status == 403 and revoked.code == "revoked_key"

        stored = await storage.api_keys()
        assert stored and stored[0]["active"] is False
        # the raw key is never written to storage
        assert raw not in str(stored)

    asyncio.run(scenario())


def test_unknown_and_missing_keys_are_rejected(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        missing = await api.authenticate("")
        assert missing.status == 401 and missing.code == "missing_key"
        unknown = await api.authenticate("vyrn_nope_nope_nope_nope")
        assert unknown.status == 403 and unknown.code == "invalid_key"

    asyncio.run(scenario())


def test_admin_scope_implies_every_scope(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        record, _ = await api.issue(1, "root", scopes=["admin"])
        result = await api.authenticate(record["key"])
        assert result.ok
        for scope in ("read", "search", "download", "admin"):
            assert result.has(scope)

    asyncio.run(scenario())


def test_expired_keys_are_refused(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        record, _ = await api.issue(5, "old", days=1)
        live = await api.authenticate(record["key"])
        assert live.ok

        record["expires_at"] = time.time() - 10
        await api._save(record)
        api._invalidate()
        expired = await api.authenticate(record["key"])
        assert not expired.ok and expired.code == "expired_key"

        listed = await api.keys(5)
        assert listed[0]["expired"] is True

    asyncio.run(scenario())


def test_rotate_issues_a_new_key_and_retires_the_old(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        record, _ = await api.issue(9, "rotate", scopes=["read", "search"], rate_limit=5)
        fresh, error = await api.rotate(9, record["id"])
        assert error == "" and fresh is not None
        assert fresh["id"] != record["id"]
        assert sorted(fresh["scopes"]) == ["read", "search"]
        assert fresh["rate_limit"] == 5

        assert not (await api.authenticate(record["key"])).ok
        assert (await api.authenticate(fresh["key"])).ok

        listing = {item["id"]: item for item in await api.keys(9)}
        assert listing[record["id"]]["replaced_by"] == fresh["id"]

    asyncio.run(scenario())


def test_key_limit_per_owner(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        for index in range(MAX_KEYS_PER_OWNER):
            record, error = await api.issue(11, f"k{index}")
            assert record is not None and error == ""
        blocked, error = await api.issue(11, "overflow")
        assert blocked is None and "limit" in error
        # a different owner is unaffected
        other, _ = await api.issue(12, "other")
        assert other is not None

    asyncio.run(scenario())


def test_rate_limit_is_per_key(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_rate=2)

    async def scenario():
        record, _ = await api.issue(1, "rl")
        raw = record["key"]
        assert (await api.authenticate(raw)).ok
        assert (await api.authenticate(raw)).ok
        third = await api.authenticate(raw)
        assert not third.ok and third.status == 429 and third.remaining == 0
        assert third.reset_in > 0

        other, _ = await api.issue(2, "rl2")
        assert (await api.authenticate(other["key"])).ok

        # per-key override wins over the global limit
        big, _ = await api.issue(3, "big", rate_limit=10)
        for _ in range(5):
            assert (await api.authenticate(big["key"])).ok

    asyncio.run(scenario())


def test_open_mode_allows_anonymous_requests(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_open=True)

    async def scenario():
        result = await api.authenticate("")
        assert result.ok and result.open_access

    asyncio.run(scenario())


def test_legacy_plaintext_keys_still_authenticate(tmp_path, monkeypatch):
    api, storage = _api(tmp_path, monkeypatch)
    legacy = "eldian_" + "x" * 32

    async def scenario():
        await storage.add_api_key(
            {"key": legacy, "owner_id": 77, "label": "legacy", "active": True, "created_at": time.time()}
        )
        api._invalidate()
        result = await api.authenticate(legacy)
        assert result.ok and result.record["owner_id"] == 77
        # legacy rows have no scopes → the safe defaults
        assert result.has("download") and not result.has("admin")

    asyncio.run(scenario())


def test_usage_counters_are_recorded(tmp_path, monkeypatch):
    api, storage = _api(tmp_path, monkeypatch)

    async def scenario():
        record, _ = await api.issue(7, "meter")
        await api.note_use(record, size=2048)
        keys = await api.keys(7)
        assert keys[0]["uses"] == 1 and keys[0]["bytes"] == 2048
        counters = await storage.counters()
        assert counters["api_downloads"] == 1 and counters["api_bytes"] == 2048

    asyncio.run(scenario())


def test_stats_summarises_the_store(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        record, _ = await api.issue(1, "a")
        await api.issue(1, "b")
        await api.note_use(record, size=10)
        stats = await api.stats()
        assert stats["keys"] == 2 and stats["keys_total"] == 2
        assert stats["requests"] == 1 and stats["bytes"] == 10
        assert stats["version"] == "2.0" and stats["enabled"] is True
        assert stats["storage"] == "json"

    asyncio.run(scenario())


# ── HTTP surface ────────────────────────────────────────────────────────────
class _FakeYoutube:
    async def search(self, query, limit=5, requester=(0, "")):
        return [Track(id="abc12345678", title=f"{query} hit", duration=90, uploader="Tester")]

    async def resolve(self, target, requester=(0, "")):
        if target.startswith("https://www.youtube.com/watch?v="):
            video_id = target.rsplit("=", 1)[-1]
        else:
            video_id = "abc12345678"
        return Track(id=video_id, title="Fake Track", duration=90, uploader="Tester")


class _FakeDownloader:
    def __init__(self, path):
        self.path = path

    async def audio(self, track, progress=None):
        return self.path


def _client(scenario, *, with_webapp: bool = False):
    async def run():
        app = build_app(with_webapp=with_webapp)
        async with TestClient(TestServer(app)) as client:
            return await scenario(client)

    return asyncio.run(run())


def test_v1_health_docs_and_openapi():
    async def scenario(client):
        health = await client.get("/v1/health")
        payload = await health.json()
        assert health.status == 200 and payload["status"] == "ok"
        assert health.headers["X-API-Version"] == "2.0"
        assert "/v1/tracks" in payload["endpoints"]

        docs = await client.get("/v1/docs")
        body = await docs.text()
        assert docs.status == 200 and "VYRON Music API" in body
        assert "X-API-Key" in body

        spec = await client.get("/v1/openapi.json")
        spec_body = await spec.json()
        assert spec_body["openapi"].startswith("3.")
        assert "/tracks" in spec_body["paths"]
        assert spec_body["components"]["securitySchemes"]["ApiKeyAuth"]["name"] == "X-API-Key"

        root = await client.get("/v1/?format=json")
        root_body = await root.json()
        assert root_body["ok"] and root_body["api_version"] == "2.0"

    _client(scenario)


def test_v1_requires_a_key_by_default():
    async def scenario(client):
        response = await client.post("/v1/search", json={"query": "test"})
        assert response.status == 401
        payload = await response.json()
        assert payload["ok"] is False and payload["code"] == "missing_key"
        assert payload["request_id"].startswith("req_")

        keyed = await client.get("/v1/me", headers={"X-API-Key": "vyrn_bogus"})
        assert keyed.status == 403

        unknown = await client.get("/v1/nope")
        assert unknown.status == 404 and (await unknown.json())["code"] == "not_found"

    _client(scenario)


def test_v1_search_and_download_with_a_key(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_open=False)
    monkeypatch.setattr(runtime, "youtube", _FakeYoutube())

    audio_file = tmp_path / "track.mp3"
    audio_file.write_bytes(b"ID3" + b"\x00" * 400)
    monkeypatch.setattr(runtime, "downloader", _FakeDownloader(audio_file))
    monkeypatch.setattr("vyron.api.routes.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)

    async def scenario():
        record, _ = await api.issue(424242, "http")
        headers = {"X-API-Key": record["key"]}

        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            search = await client.get("/v1/search?q=neon", headers=headers)
            payload = await search.json()
            assert payload["ok"] and payload["results"][0]["title"] == "neon hit"
            assert payload["results"][0]["stream_url"].endswith("/stream")
            assert search.headers["X-RateLimit-Remaining"]

            download = await client.post(
                "/v1/tracks", json={"video_id": "abc12345678"}, headers=headers
            )
            assert download.status == 200
            assert download.headers["X-Track-Id"] == "abc12345678"
            assert "attachment" in download.headers["Content-Disposition"]
            assert (await download.read()).startswith(b"ID3")

            legacy = await client.post(
                "/v1/track/by-video-id", json={"video_id": "abc12345678"}, headers=headers
            )
            assert legacy.status == 200

            info = await client.get("/v1/tracks/abc12345678", headers=headers)
            assert (await info.json())["track"]["title"] == "Fake Track"

            me = await client.get("/v1/me", headers=headers)
            info_body = await me.json()
            assert info_body["ok"] and info_body["uses"] >= 1
            assert info_body["scopes"] == list(DEFAULT_SCOPES)

            stream = await client.get("/v1/tracks/abc12345678/stream", headers=headers)
            assert stream.status == 200 and "inline" in stream.headers["Content-Disposition"]

            bad = await client.post("/v1/tracks", json={"video_id": "no"}, headers=headers)
            assert bad.status == 400 and (await bad.json())["code"] == "invalid_video"

    asyncio.run(scenario())


def test_scopes_are_enforced_over_http(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "youtube", _FakeYoutube())
    audio_file = tmp_path / "scope.mp3"
    audio_file.write_bytes(b"ID3")
    monkeypatch.setattr(runtime, "downloader", _FakeDownloader(audio_file))
    monkeypatch.setattr("vyron.api.routes.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)

    async def scenario():
        reader, _ = await api.issue(1, "reader", scopes=["read"])
        headers = {"X-API-Key": reader["key"]}

        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            blocked = await client.get("/v1/search?q=x", headers=headers)
            assert blocked.status == 403
            assert (await blocked.json())["code"] == "forbidden_scope"

            admin = await client.get("/v1/admin/keys", headers=headers)
            assert admin.status == 403

            allowed = await client.get("/v1/tracks/abc12345678", headers=headers)
            assert allowed.status == 200

            metrics = await client.get("/v1/metrics", headers=headers)
            assert metrics.status == 403

    asyncio.run(scenario())


def test_admin_endpoints_mint_list_and_revoke(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)
    monkeypatch.setattr("vyron.api.routes.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)

    async def scenario():
        root, _ = await api.issue(1, "root", scopes=["admin"])
        headers = {"X-API-Key": root["key"]}

        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            minted = await client.post(
                "/v1/admin/keys",
                json={"label": "ci", "scopes": ["read"], "days": 3},
                headers=headers,
            )
            assert minted.status == 201
            created = (await minted.json())["created"]
            assert created["key"].startswith("vyrn_") and created["label"] == "ci"

            listing = await (await client.get("/v1/admin/keys", headers=headers)).json()
            assert listing["count"] == 2
            assert all("hash" not in row for row in listing["keys"])
            raw_leaked = [row for row in listing["keys"] if row.get("key", "").startswith("vyrn_") and len(row["key"]) > 20]
            assert not raw_leaked

            rotated = await client.post(f"/v1/admin/keys/{created['id']}/rotate", headers=headers)
            assert rotated.status == 200 and (await rotated.json())["created"]["id"] != created["id"]

            revoked = await client.delete(f"/v1/admin/keys/{created['id']}", headers=headers)
            assert revoked.status == 200

            missing = await client.delete("/v1/admin/keys/key_nope", headers=headers)
            assert missing.status == 404

            metrics = await client.get("/v1/metrics", headers=headers)
            metrics_body = await metrics.json()
            assert metrics_body["ok"] and "latency_ms" in metrics_body

            prom = await client.get("/v1/metrics?format=prometheus", headers=headers)
            text = await prom.text()
            assert "vyron_api_requests_total" in text

            usage = await client.get("/v1/key", headers=headers)
            assert (await usage.json())["ok"] is True

    asyncio.run(scenario())


def test_v1_reports_not_ready_while_the_bot_boots(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_open=True)
    monkeypatch.setattr("vyron.api.routes.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)
    monkeypatch.setattr(runtime, "youtube", None)
    monkeypatch.setattr(runtime, "downloader", None)

    async def scenario(client):
        response = await client.post("/v1/search", json={"query": "x"})
        assert response.status == 503
        payload = await response.json()
        assert payload["ok"] is False and payload["code"] == "not_ready"

    _client(scenario)


def test_health_stays_compatible_with_eldian_monitors():
    async def scenario(client):
        response = await client.get("/health")
        payload = await response.json()
        assert response.status == 200 and payload["status"] == "ok" and payload["ok"] is True

    _client(scenario)


def test_music_api_can_be_switched_off(monkeypatch):
    monkeypatch.setattr("vyron.api.app.settings", dataclasses.replace(settings, music_api=False))

    async def scenario(client):
        assert (await client.get("/v1/health")).status == 404
        assert (await client.get("/v1/docs")).status == 404

    _client(scenario)


def test_bare_v1_redirects_to_the_docs_index():
    async def scenario(client):
        response = await client.get("/v1", allow_redirects=False)
        assert response.status in {301, 308}
        assert response.headers["Location"].endswith("/v1/")

    _client(scenario)


def test_api_console_creates_rotates_and_revokes_keys(tmp_path, monkeypatch):
    """The Mini App's /api/keys endpoint speaks the v2 key lifecycle."""
    api, _ = _api(tmp_path, monkeypatch)
    monkeypatch.setattr("vyron.web.server.get_music_api", lambda: api)

    class _User:
        user_id = 424242
        username = "tester"
        first_name = "Test"

    async def _identify(_request):
        return _User()

    monkeypatch.setattr("vyron.web.server._identify", _identify)
    monkeypatch.setattr("vyron.web.server._denied", lambda _user: None)
    monkeypatch.setattr("vyron.web.server._is_preview", lambda _user: False)
    monkeypatch.setattr(
        "vyron.web.server.settings", dataclasses.replace(settings, owner_id=424242, webapp=True)
    )

    async def scenario(client):
        created = await client.post(
            "/api/keys",
            json={"action": "create", "label": "console", "scopes": ["read", "search"], "days": 5, "rate_limit": 12},
        )
        body = await created.json()
        assert created.status == 200 and body["created"]["key"].startswith("vyrn_")
        key_id = body["created"]["id"]

        listing = await (await client.get("/api/keys")).json()
        assert listing["ok"] and listing["scopes"] == ["read", "search", "download", "admin"]
        row = next(item for item in listing["keys"] if item["id"] == key_id)
        assert row["scopes"] == ["read", "search"] and "key" not in row
        assert listing["metrics"]["requests"] >= 0

        rotated = await client.post("/api/keys", json={"action": "rotate", "id": key_id})
        rotated_body = await rotated.json()
        assert rotated.status == 200 and rotated_body["created"]["id"] != key_id

        revoked = await client.post("/api/keys", json={"action": "revoke", "id": rotated_body["created"]["id"]})
        assert (await revoked.json())["revoked"] is True

        missing = await client.post("/api/keys", json={"action": "revoke", "id": "key_nope"})
        assert missing.status == 404

    _client(scenario, with_webapp=True)


# ── owner access ────────────────────────────────────────────────────────────
def test_owner_token_unlocks_every_api_scope(tmp_path, monkeypatch):
    from vyron.web.auth import make_owner_token

    api, _ = _api(tmp_path, monkeypatch)
    monkeypatch.setattr("vyron.api.routes.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.settings", dataclasses.replace(settings, owner_id=424242))

    token = make_owner_token(settings.bot_token, 424242)

    async def scenario():
        async with TestClient(TestServer(build_app(with_webapp=False))) as client:
            me = await client.get("/v1/me", headers={"X-Owner-Token": token})
            body = await me.json()
            assert me.status == 200 and body["owner"] is True and body["mode"] == "owner"
            assert set(body["scopes"]) == {"read", "search", "download", "admin"}
            assert me.headers["X-Auth-Mode"] == "owner"

            listed = await client.get("/v1/admin/keys", headers={"X-Owner-Token": token})
            assert listed.status == 200

            # a bearer-style owner token works through X-API-Key too
            via_key = await client.get("/v1/admin/keys", headers={"X-API-Key": token})
            assert via_key.status == 200

            stranger = make_owner_token(settings.bot_token, 1234)
            denied = await client.get("/v1/me", headers={"X-Owner-Token": stranger})
            assert denied.status == 403 and (await denied.json())["code"] == "invalid_key"

    asyncio.run(scenario())


def test_owner_rate_limit_is_generous(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_rate=1)
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.security.settings", dataclasses.replace(settings, owner_id=424242))

    async def scenario():
        result = await api.authenticate_owner(424242)
        assert result.ok and result.owner and result.limit >= 120
        assert result.has("admin") and result.has("download")

    asyncio.run(scenario())
