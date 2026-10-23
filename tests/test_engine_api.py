"""The download API (/vyron) — option set, retries, lifecycle and HTTP surface.

No network and no ffmpeg here: yt-dlp itself is replaced by a fake that either
writes a file (success) or raises (failure), so these tests pin the contract we
promised clients, not YouTube's behaviour.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import time
import uuid

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pyrogram")

from aiohttp.test_utils import TestClient, TestServer

from vyron.config import settings
from vyron.core.musicapi import MusicAPI
from vyron.core.queue import Track
from vyron.database import JsonStorage
from vyron.engine import routes
from vyron.engine import youtube as engine
from vyron.engine.youtube import (
    EngineError,
    build_options,
    cleanup_download,
    cleanup_stale_downloads,
    download_audio,
    validate_cookies,
    validate_proxy,
)
from vyron.utils.health import build_app


def _fresh_dir(base):
    base.mkdir(parents=True, exist_ok=True)
    path = base / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def cfg(**overrides):
    return dataclasses.replace(settings, **overrides)


# ── validation ──────────────────────────────────────────────────────────────
def test_proxy_must_be_a_real_url_with_a_supported_scheme():
    assert validate_proxy("socks5://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
    with pytest.raises(EngineError) as bad_url:
        validate_proxy("127.0.0.1:1080")
    assert bad_url.value.status == 400
    with pytest.raises(EngineError) as bad_scheme:
        validate_proxy("ftp://example.com:21")
    assert "Unsupported proxy scheme" in str(bad_scheme.value)


def test_cookies_string_and_file_are_mutually_exclusive(tmp_path):
    with pytest.raises(EngineError):
        validate_cookies("a=b", str(tmp_path / "cookies.txt"))
    with pytest.raises(EngineError):
        validate_cookies("   ", None)
    with pytest.raises(EngineError):
        validate_cookies(None, str(tmp_path / "missing.txt"))
    validate_cookies(None, None)  # nothing configured is fine


# ── yt-dlp options ────────────────────────────────────────────────────────
def test_options_carry_the_documented_knobs(tmp_path):
    options = build_options(
        cfg(yt_dlp_format="bestaudio[ext=m4a]/best", yt_dlp_retries=5, yt_dlp_socket_timeout=12),
        tmp_path,
        "abc12345678",
    )
    assert options["format"] == "bestaudio[ext=m4a]/best"
    assert options["retries"] == 5 and options["fragment_retries"] == 5
    assert options["socket_timeout"] == 12
    assert options["outtmpl"].endswith("abc12345678.%(ext)s")
    assert options["noplaylist"] is True and options["continuedl"] is True


def test_options_use_the_cookie_file_and_proxy(tmp_path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n")
    options = build_options(
        cfg(cookies_text="", cookies_file="", youtube_cookies_file=str(cookie), youtube_proxy=""),
        tmp_path,
        "abc12345678",
    )
    assert options["cookiefile"] == str(cookie)
    assert "proxy" not in options


# ── download + retries ────────────────────────────────────────────────────
class _FakeYDL:
    """Stands in for yt_dlp.YoutubeDL — records options, then writes or raises."""

    writes = True
    failures = 0
    seen: list[dict] = []

    def __init__(self, options):
        self.options = options
        type(self).seen.append(options)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        from pathlib import Path

        video_id = url.rsplit("=", 1)[-1]
        if type(self).failures > 0:
            type(self).failures -= 1
            raise RuntimeError("HTTP Error 403: Forbidden")
        if type(self).writes:
            Path(self.options["outtmpl"].replace("%(ext)s", "m4a")).write_bytes(b"ID3" + b"\x00" * 64)
        return {"id": video_id}


@pytest.fixture
def fake_ydl(monkeypatch):
    _FakeYDL.writes = True
    _FakeYDL.failures = 0
    _FakeYDL.seen = []
    monkeypatch.setattr(engine.yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr(engine.time, "sleep", lambda _s: None)
    return _FakeYDL


def test_download_returns_the_written_file(tmp_path, fake_ydl):
    path = download_audio("abc12345678", tmp_path / "req", cfg=cfg(yt_dlp_retries=2))
    assert path.is_file() and path.suffix == ".m4a"
    assert path.read_bytes().startswith(b"ID3")
    assert len(fake_ydl.seen) == 1


def test_download_retries_then_reports_a_gateway_error(tmp_path, fake_ydl):
    fake_ydl.failures = 99
    with pytest.raises(EngineError) as failure:
        download_audio("abc12345678", tmp_path / "req", cfg=cfg(yt_dlp_retries=3))
    assert failure.value.status == 502
    assert "after retries" in str(failure.value)
    assert len(fake_ydl.seen) == 3


def test_download_recovers_on_a_later_attempt(tmp_path, fake_ydl):
    fake_ydl.failures = 1
    path = download_audio("abc12345678", tmp_path / "req", cfg=cfg(yt_dlp_retries=3))
    assert path.is_file() and len(fake_ydl.seen) == 2


def test_missing_output_file_is_a_server_error(tmp_path, fake_ydl):
    fake_ydl.writes = False
    with pytest.raises(EngineError) as failure:
        download_audio("abc12345678", tmp_path / "req", cfg=cfg(yt_dlp_retries=1))
    assert failure.value.status == 500


# ── cleanup ────────────────────────────────────────────────────────────────
def test_cleanup_removes_the_file_and_its_request_directory(tmp_path):
    folder = tmp_path / "abc"
    folder.mkdir()
    path = folder / "abc12345678.m4a"
    path.write_bytes(b"ID3")
    cleanup_download(path)
    assert not path.exists() and not folder.exists()


def test_cleanup_accepts_a_request_directory(tmp_path):
    folder = tmp_path / "abc"
    folder.mkdir()
    (folder / "abc12345678.m4a.part").write_bytes(b"partial")
    cleanup_download(folder)
    assert not folder.exists()


def test_failed_download_answers_502_and_leaves_nothing_behind(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    monkeypatch.setattr(routes, "settings", cfg(downloads_dir=tmp_path / "dl"))
    monkeypatch.setattr(routes, "new_request_dir", lambda *a, **k: _fresh_dir(tmp_path / "dl"))

    async def boom(video_id, folder, **_kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{video_id}.m4a.part").write_bytes(b"partial")
        raise engine.EngineError("Unable to download track after retries: 403", 502)

    monkeypatch.setattr(routes, "download_audio_async", boom)

    async def run():
        record, _ = await api.issue(4244, "cli")
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/vyron/v1/track/by-video-id",
                json={"video_id": "abc12345678"},
                headers={"X-API-Key": record["key"]},
            )
            return response.status, await response.json()

    status, payload = asyncio.run(run())
    assert status == 502 and payload["code"] == "download_failed"
    assert list((tmp_path / "dl").iterdir()) == []


def test_stale_directories_are_swept(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    new.mkdir()
    stale = time.time() - 5000
    os.utime(old, (stale, stale))
    removed = cleanup_stale_downloads(tmp_path, cfg=cfg(download_cleanup_seconds=900))
    assert removed == 1 and not old.exists() and new.exists()


# ── HTTP surface ──────────────────────────────────────────────────────────
def _api(tmp_path, monkeypatch):
    storage = JsonStorage(dataclasses.replace(settings, data_dir=tmp_path))
    asyncio.run(storage.connect())
    monkeypatch.setattr(MusicAPI, "_storage", staticmethod(lambda: storage))
    api = MusicAPI(settings=dataclasses.replace(settings, music_api_open=False))
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)
    return api


def test_video_id_parsing():
    assert routes.video_id_from({"video_id": "abc12345678"}) == "abc12345678"
    assert routes.video_id_from({"url": "https://youtu.be/abc12345678"}) == "abc12345678"
    assert routes.video_id_from({"url": "https://www.youtube.com/watch?v=abc12345678&t=30"}) == "abc12345678"
    with pytest.raises(Exception):
        routes.video_id_from({"video_id": "not-an-id"})


def test_download_api_requires_a_key(tmp_path, monkeypatch):
    _api(tmp_path, monkeypatch)

    async def run():
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/vyron/v1/track/by-video-id", json={"video_id": "abc12345678"}
            )
            return response.status, await response.json()

    status, payload = asyncio.run(run())
    assert status == 401
    assert payload["ok"] is False and payload["code"] == "missing_key"


def test_download_api_serves_audio(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    monkeypatch.setattr(routes, "settings", cfg(downloads_dir=tmp_path / "dl"))
    (tmp_path / "dl").mkdir()

    async def fake_download(video_id, folder, **_kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{video_id}.m4a"
        path.write_bytes(b"ID3" + b"\x00" * 32)
        return path

    monkeypatch.setattr(routes, "download_audio_async", fake_download)

    async def run():
        record, _ = await api.issue(4242, "cli")
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            health = await client.get("/vyron/health")
            audio = await client.post(
                "/vyron/v1/track/by-video-id",
                json={"video_id": "abc12345678"},
                headers={"X-API-Key": record["key"]},
            )
            return await health.json(), audio, await audio.read()

    health, audio, payload = asyncio.run(run())
    assert health["status"] == "ok" and health["engine"] == "vyron"
    assert audio.status == 200
    assert audio.headers["X-Engine"] == "vyron"
    assert audio.headers["X-Track-Id"] == "abc12345678"
    assert audio.headers["X-API-Version"] == "2.0"
    assert "attachment" in audio.headers["Content-Disposition"]
    assert payload.startswith(b"ID3")


def test_download_api_by_query_uses_search(tmp_path, monkeypatch):
    api = _api(tmp_path, monkeypatch)
    monkeypatch.setattr(routes, "settings", cfg(downloads_dir=tmp_path / "dl"))

    class FakeYouTube:
        async def search(self, query, limit=None):
            assert query == "neon nights"
            return [Track(id="abc12345678", title="Neon Nights", duration=90)]

    from vyron.runtime import runtime

    monkeypatch.setattr(runtime, "youtube", FakeYouTube())

    async def fake_download(video_id, folder, **_kwargs):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{video_id}.m4a"
        path.write_bytes(b"ID3" + b"\x00" * 8)
        return path

    monkeypatch.setattr(routes, "download_audio_async", fake_download)

    async def run():
        record, _ = await api.issue(4243, "cli")
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            hit = await client.post(
                "/vyron/v1/track/by-query",
                json={"query": "neon nights"},
                headers={"X-API-Key": record["key"]},
            )
            empty = await client.post(
                "/vyron/v1/track/by-query", json={}, headers={"X-API-Key": record["key"]}
            )
            return hit, await hit.read(), empty.status, await empty.json()

    hit, payload, empty_status, empty = asyncio.run(run())
    assert hit.status == 200 and hit.headers["X-Track-Id"] == "abc12345678"
    assert payload.startswith(b"ID3")
    assert empty_status == 400 and empty["code"] == "missing_query"


def test_download_api_index_and_docs(tmp_path, monkeypatch):
    _api(tmp_path, monkeypatch)

    async def run():
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            index = await (await client.get("/vyron/")).json()
            docs = await (await client.get("/vyron/v1/docs")).json()
            return index, docs

    index, docs = asyncio.run(run())
    assert index["engine"] == "vyron"
    assert index["endpoints"]["by_video_id"].endswith("/vyron/v1/track/by-video-id")
    assert "/vyron/v1/track/by-query" in docs["paths"]
