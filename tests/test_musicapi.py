"""Music API tests — keys, auth, rate limits and the /v1 HTTP surface."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pyrogram")

from aiohttp.test_utils import TestClient, TestServer

from vyron.config import settings
from vyron.core.musicapi import MusicAPI, generate_key, looks_like_key, mask_key
from vyron.core.queue import Track
from vyron.database import JsonStorage
from vyron.runtime import runtime
from vyron.utils.health import build_app


def _storage(tmp_path) -> JsonStorage:
    return JsonStorage(dataclasses.replace(settings, data_dir=tmp_path))


def _api(tmp_path, monkeypatch, **overrides) -> tuple[MusicAPI, JsonStorage]:
    storage = _storage(tmp_path)

    async def connect():
        await storage.connect()

    asyncio.run(connect())
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


def test_issue_authenticate_and_revoke(tmp_path, monkeypatch):
    api, storage = _api(tmp_path, monkeypatch)

    async def scenario():
        record, error = await api.issue(424242, "unit")
        assert record is not None and error == ""
        raw = record["key"]

        ok = await api.authenticate(raw)
        assert ok.ok and ok.record["label"] == "unit"
        assert ok.limit == settings.music_api_rate

        listed = await api.keys(424242)
        assert len(listed) == 1 and listed[0]["masked"] == mask_key(raw)

        assert await api.revoke(999, raw) is False  # someone else's key
        assert await api.revoke(424242, raw) is True

        revoked = await api.authenticate(raw)
        assert not revoked.ok and revoked.status == 403

        stored = await storage.api_keys()
        assert stored and stored[0]["active"] is False

    asyncio.run(scenario())


def test_unknown_and_missing_keys_are_rejected(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch)

    async def scenario():
        missing = await api.authenticate("")
        assert missing.status == 401
        unknown = await api.authenticate("vyrn_nope_nope_nope_nope")
        assert unknown.status == 403

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

        # a different key has its own window
        other, _ = await api.issue(2, "rl2")
        assert (await api.authenticate(other["key"])).ok

    asyncio.run(scenario())


def test_open_mode_allows_anonymous_requests(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_open=True)

    async def scenario():
        result = await api.authenticate("")
        assert result.ok and result.open_access

    asyncio.run(scenario())


def test_usage_counters_are_recorded(tmp_path, monkeypatch):
    api, storage = _api(tmp_path, monkeypatch)

    async def scenario():
        record, _ = await api.issue(7, "meter")
        await api.note_use(record, size=2048)
        keys = await api.keys(7)
        assert keys[0]["uses"] == 1 and keys[0]["bytes"] == 2048
        counters = await storage.counters()
        assert counters["api_downloads"] == 1

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
        assert "/v1/track/by-video-id" in payload["endpoints"]

        docs = await client.get("/v1/docs")
        assert docs.status == 200 and "VYRON Music API" in await docs.text()

        spec = await client.get("/v1/openapi.json")
        body = await spec.json()
        assert body["openapi"].startswith("3.")
        assert "/v1/track/by-video-id" in body["paths"]

    _client(scenario)


def test_v1_requires_a_key_by_default():
    async def scenario(client):
        response = await client.post("/v1/search", json={"query": "test"})
        assert response.status == 401
        payload = await response.json()
        assert payload["ok"] is False

        keyed = await client.get("/v1/key", headers={"X-API-Key": "vyrn_bogus"})
        assert keyed.status == 403

    _client(scenario)


def test_v1_search_and_download_with_a_key(tmp_path, monkeypatch):
    api, _ = _api(tmp_path, monkeypatch, music_api_open=False)
    monkeypatch.setattr(runtime, "youtube", _FakeYoutube())

    audio_file = tmp_path / "track.mp3"
    audio_file.write_bytes(b"ID3" + b"\x00" * 400)
    monkeypatch.setattr(runtime, "downloader", _FakeDownloader(audio_file))

    from vyron.web import musicapi as web_api

    async def scenario():
        record, _ = await api.issue(424242, "http")
        headers = {"X-API-Key": record["key"]}
        monkeypatch.setattr(web_api, "get_music_api", lambda: api)

        from aiohttp.test_utils import TestClient, TestServer

        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            search = await client.post("/v1/search", json={"query": "neon"}, headers=headers)
            payload = await search.json()
            assert payload["ok"] and payload["results"][0]["title"] == "neon hit"

            download = await client.post(
                "/v1/track/by-video-id", json={"video_id": "abc12345678"}, headers=headers
            )
            assert download.status == 200
            assert download.headers["X-Track-Id"] == "abc12345678"
            assert "attachment" in download.headers["Content-Disposition"]
            assert (await download.read()).startswith(b"ID3")

            me = await client.get("/v1/key", headers=headers)
            info = await me.json()
            assert info["ok"] and info["uses"] == 1

            bad = await client.post("/v1/track/by-video-id", json={"video_id": "no"}, headers=headers)
            assert bad.status == 400

    asyncio.run(scenario())


def test_v1_reports_not_ready_while_the_bot_boots(tmp_path, monkeypatch):
    from vyron.web import musicapi as web_api

    api, _ = _api(tmp_path, monkeypatch, music_api_open=True)
    monkeypatch.setattr(web_api, "get_music_api", lambda: api)
    monkeypatch.setattr(runtime, "youtube", None)
    monkeypatch.setattr(runtime, "downloader", None)

    async def scenario(client):
        response = await client.post("/v1/search", json={"query": "x"})
        assert response.status == 503
        assert (await response.json())["ready"] is False

    _client(scenario)


def test_health_stays_compatible_with_eldian_monitors():
    async def scenario(client):
        response = await client.get("/health")
        payload = await response.json()
        assert response.status == 200 and payload["status"] == "ok" and payload["ok"] is True

    _client(scenario)


def test_music_api_can_be_switched_off(monkeypatch):
    from vyron.web import musicapi as web_api

    monkeypatch.setattr(web_api, "settings", dataclasses.replace(settings, music_api=False))

    async def scenario(client):
        assert (await client.get("/v1/health")).status == 404
        assert (await client.get("/v1/docs")).status == 404

    _client(scenario)
