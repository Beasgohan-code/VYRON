"""Downloads — the mirror fallback, the yt-dlp ladder and the /v1 job API.

Three layers are covered here because each one is a place downloads silently
break in production:

* **parsing** a Piped/Invidious answer (they disagree on field names),
* the **ladder** in ``Downloader`` (a refused client must not end the job), and
* the **job API** (submit → poll → fetch, and nobody else's job id).
"""
from __future__ import annotations

import asyncio
import dataclasses
import types

import pytest

from vyron.core.public_streams import (
    DirectStream,
    PublicStreams,
    parse_invidious,
    parse_invidious_video,
    parse_piped,
    parse_piped_video,
)
from vyron.core.queue import Track

INVIDIOUS_DOC = {
    "adaptiveFormats": [
        {"url": "https://cdn.example/low.m4a?mime=audio%2Fmp4", "type": "audio/mp4; codecs=mp4a", "bitrate": 48000},
        {"url": "https://cdn.example/high.m4a?mime=audio%2Fmp4", "type": "audio/mp4; codecs=mp4a", "bitrate": 129000},
        {"url": "https://cdn.example/v.mp4?mime=video%2Fmp4", "type": "video/mp4", "bitrate": 900000},
    ],
    "formatStreams": [
        {"url": "https://cdn.example/360.mp4", "resolution": "360p", "type": "video/mp4"},
        {"url": "https://cdn.example/720.mp4", "resolution": "720p", "type": "video/mp4"},
    ],
}

PIPED_DOC = {
    "audioStreams": [
        {"url": "https://piped.example/a.webm", "bitrate": 160000, "mimeType": "audio/webm"},
        {"url": "https://piped.example/a.m4a", "bitrate": 128000, "mimeType": "audio/mp4"},
    ],
    "videoStreams": [
        {"url": "https://piped.example/v720.mp4", "quality": "720p", "mimeType": "video/mp4", "videoOnly": False},
        {"url": "https://piped.example/v1080.mp4", "quality": "1080p", "mimeType": "video/mp4", "videoOnly": True},
    ],
}


# ── parsing ────────────────────────────────────────────────────────────────
def test_invidious_audio_picks_the_highest_bitrate_audio_only():
    stream = parse_invidious(INVIDIOUS_DOC, "inv.test")
    assert stream is not None
    assert stream.url == "https://cdn.example/high.m4a?mime=audio%2Fmp4"
    assert stream.mime == "audio/mp4" and stream.ext == "m4a"
    assert stream.source == "invidious:inv.test"


def test_invidious_video_respects_the_height_cap():
    stream = parse_invidious_video(INVIDIOUS_DOC, "inv.test", 480)
    assert stream is not None and stream.url == "https://cdn.example/360.mp4"
    assert stream.height == 360


def test_piped_audio_and_video_parsing():
    audio = parse_piped(PIPED_DOC, "piped.test")
    assert audio is not None and audio.url.endswith("a.webm")
    assert audio.ext == "webm" and audio.mime == "audio/webm"
    video = parse_piped_video(PIPED_DOC, "piped.test", 720)
    assert video is not None and video.url.endswith("v720.mp4")
    assert video.height == 720


def test_empty_documents_are_not_guessed_at():
    assert parse_invidious({}, "x") is None
    assert parse_piped({}, "x") is None
    assert parse_invidious_video({"formatStreams": []}, "x", 720) is None


# ── provider selection ─────────────────────────────────────────────────────
def test_resolve_uses_the_first_healthy_mirror(monkeypatch):
    streams = PublicStreams()
    streams.invidious = ("dead.example",)
    streams.piped = ("alive.example",)

    async def fake_json(url):
        if "dead.example" in url:
            return None
        return PIPED_DOC

    monkeypatch.setattr(streams, "_json", fake_json)
    stream = asyncio.run(streams.resolve("dQw4w9WgXcQ"))
    assert stream is not None and stream.source == "piped:alive.example"


def test_resolve_rejects_obvious_junk():
    streams = PublicStreams()
    assert asyncio.run(streams.resolve("not a video id !!")) is None


# ── the downloader ladder ──────────────────────────────────────────────────
def _settings(tmp_path):
    from vyron.config import settings as real

    return dataclasses.replace(
        real,
        data_dir=tmp_path,
        downloads_dir=tmp_path / "downloads",
        max_download_mb=50,
        stream_fallback=False,
    )


def _downloader(tmp_path):
    from vyron.core.downloader import Downloader

    dl = Downloader(_settings(tmp_path))
    dl.settings.ensure_dirs()
    return dl


def test_downloader_walks_the_client_ladder_then_succeeds(tmp_path, monkeypatch):
    from vyron.core import downloader as module

    attempts: list[dict] = []

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            attempts.append(opts)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            index = len(attempts)
            if index < 3:
                # Different clients fail differently — that is what tells the
                # ladder the problem is the client, not the server.
                raise RuntimeError(f"client {index} rejected the signature (403)")
            from pathlib import Path

            Path(self.opts["outtmpl"].replace("%(ext)s", "m4a")).write_bytes(b"ID3" + b"0" * 64)

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", FakeYDL)
    dl = _downloader(tmp_path)
    track = Track(id="abcdefghijk", title="Ladder", duration=60, uploader="x")

    path = dl._download_ytdlp(track, video=False)

    assert len(attempts) == 3  # default → android_vr → ios (then it worked)
    assert attempts[0].get("extractor_args") is None
    assert attempts[1]["extractor_args"]["youtube"]["player_client"] == ["android_vr"]
    assert attempts[2]["extractor_args"]["youtube"]["player_client"] == ["ios"]
    assert path.stat().st_size > 0 and path.suffix == ".m4a"
    # the temp work directory never survives a call
    assert not list(dl.settings.downloads_dir.glob(".work-*"))


def test_identical_refusals_stop_the_client_ladder(tmp_path, monkeypatch):
    """Production: four clients, 49 s, the same sentence four times."""
    from vyron.core import downloader as module

    attempts: list[int] = []

    class WallYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            attempts.append(len(attempts) + 1)
            raise RuntimeError(
                "ERROR: [youtube] abc: Failed to extract any player response"
            )

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", WallYDL)
    dl = _downloader(tmp_path)
    track = Track(id="abcdefghijk", title="Walled", duration=60, uploader="x")

    with pytest.raises(module.DownloadError):
        dl._download_ytdlp(track, video=False)

    assert len(attempts) == 2  # not the whole ladder


def test_a_walled_server_skips_the_yt_dlp_ladder(tmp_path, monkeypatch):
    """If the resolver already knows, the download must not re-prove it."""
    dl = _downloader(tmp_path)
    track = Track(id="abcdefghijk", title="Walled", duration=60, uploader="x")

    monkeypatch.setattr(dl, "_youtube_walled", lambda: True)
    monkeypatch.setattr(
        dl, "_download_ytdlp", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("yt-dlp must not run while walled")
        )
    )

    async def mirror(_track, *, video=False, on_progress=None):
        path = dl.settings.downloads_dir / "mirror.m4a"
        path.write_bytes(b"ID3" + b"0" * 32)
        return path

    monkeypatch.setattr(dl, "_download_direct", mirror)

    path = asyncio.run(dl.audio(track))
    assert path.read_bytes().startswith(b"ID3")


def test_downloader_falls_back_to_a_mirror(tmp_path, monkeypatch):
    from vyron.core import downloader as module

    class DeadYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download(self, urls):
            raise RuntimeError("confirm you're not a bot")

    class FakeStreams:
        async def resolve(self, video_id, height=0):
            return DirectStream(url="https://cdn.example/audio.m4a", source="invidious:test", ext="m4a")

    monkeypatch.setattr(module.yt_dlp, "YoutubeDL", DeadYDL)
    monkeypatch.setattr("vyron.core.public_streams.get_public_streams", lambda *a, **k: FakeStreams())
    monkeypatch.setattr(module, "ffmpeg_path", lambda: "")

    dl = _downloader(tmp_path)
    dl.settings = dataclasses.replace(dl.settings, stream_fallback=True)

    async def fake_fetch(url, target, headers, on_progress, total=0):
        target.write_bytes(b"ID3" + b"0" * 32)

    monkeypatch.setattr(dl, "_fetch_to", fake_fetch)
    track = Track(id="abcdefghijk", title="Mirror", duration=60, uploader="x")

    path = asyncio.run(dl.audio(track))
    assert path.suffix == ".m4a" and path.stat().st_size > 0
    assert dl.cached(track) is not None  # findable on the next request


def test_cached_files_of_any_extension_are_reused(tmp_path):
    dl = _downloader(tmp_path)
    track = Track(id="abcdefghijk", title="Cache", duration=60, uploader="x")
    alt = dl.settings.downloads_dir / "youtube-abcdefghijk.m4a"
    alt.write_bytes(b"ID3")
    assert dl.cached(track) == alt


# ── jobs ───────────────────────────────────────────────────────────────────
class _FakeDownloader:
    def __init__(self, path):
        self.path = path
        self.seen: list[tuple[str, bool]] = []

    async def fetch(self, track, *, video=False, on_progress=None):
        self.seen.append((track.id, video))
        if on_progress:
            on_progress(0.5, "downloading 50%")
        await asyncio.sleep(0)
        return self.path


def test_job_runs_to_ready_and_reports_progress(tmp_path, monkeypatch):
    from vyron.core import downloadjobs
    from vyron.runtime import runtime

    file = tmp_path / "song.mp3"
    file.write_bytes(b"ID3" + b"0" * 16)
    fake = _FakeDownloader(file)
    monkeypatch.setattr(runtime, "downloader", fake)
    downloadjobs.reset_download_jobs()

    async def scenario():
        jobs = downloadjobs.get_download_jobs()
        job = jobs.submit(Track(id="abcdefghijk", title="Job", duration=1, uploader="u"), kind="audio", owner="key_a")
        for _ in range(50):
            await asyncio.sleep(0.01)
            if job.status in {"ready", "failed"}:
                break
        return job, jobs

    job, jobs = asyncio.run(scenario())
    assert job.status == "ready" and job.progress == 1.0
    assert fake.seen == [("abcdefghijk", False)]
    payload = job.to_json("/v1")
    assert payload["download_url"] == f"/v1/downloads/{job.id}/file"
    assert payload["size"] == len(b"ID3" + b"0" * 16)
    assert "path" not in payload  # never leak a filesystem path
    assert jobs.can_access(job, "key_a") and not jobs.can_access(job, "key_b")
    downloadjobs.reset_download_jobs()


def test_failed_job_carries_a_clean_error(tmp_path, monkeypatch):
    from vyron.core import downloadjobs
    from vyron.runtime import runtime

    class Angry:
        async def fetch(self, track, *, video=False, on_progress=None):
            raise RuntimeError("every engine failed")

    monkeypatch.setattr(runtime, "downloader", Angry())
    downloadjobs.reset_download_jobs()

    async def scenario():
        jobs = downloadjobs.get_download_jobs()
        job = jobs.submit(Track(id="abcdefghijk", title="Bad", duration=1, uploader="u"), kind="video")
        for _ in range(50):
            await asyncio.sleep(0.01)
            if job.status in {"ready", "failed"}:
                break
        return job

    job = asyncio.run(scenario())
    assert job.status == "failed" and "every engine failed" in job.error
    downloadjobs.reset_download_jobs()


# ── HTTP surface ──────────────────────────────────────────────────────────
class _FakeYoutube:
    async def search(self, query, limit=5, requester=(0, "")):
        return [Track(id="abc12345678", title=f"{query} hit", duration=90, uploader="Tester")]

    async def resolve(self, target, requester=(0, "")):
        video_id = target.rsplit("=", 1)[-1] if "watch?v=" in target else "abc12345678"
        return Track(id=video_id, title="Fake Track", duration=90, uploader="Tester")


def _music_api(tmp_path, monkeypatch, **overrides):
    from vyron.config import settings as real
    from vyron.core.musicapi import MusicAPI
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(real, data_dir=tmp_path))
    asyncio.run(storage.connect())
    monkeypatch.setattr(MusicAPI, "_storage", staticmethod(lambda: storage))
    return MusicAPI(settings=dataclasses.replace(real, **overrides))


@pytest.mark.skipif(not __import__("importlib").util.find_spec("aiohttp"), reason="aiohttp missing")
def test_v1_download_job_roundtrip(tmp_path, monkeypatch):
    from aiohttp.test_utils import TestClient, TestServer

    from vyron.core import downloadjobs
    from vyron.runtime import runtime
    from vyron.utils.health import build_app

    api = _music_api(tmp_path, monkeypatch, music_api_open=False)
    monkeypatch.setattr(runtime, "youtube", _FakeYoutube())
    audio = tmp_path / "ready.mp3"
    audio.write_bytes(b"ID3" + b"0" * 200)
    monkeypatch.setattr(runtime, "downloader", _FakeDownloader(audio))
    monkeypatch.setattr("vyron.api.security.get_music_api", lambda: api)
    monkeypatch.setattr("vyron.api.routes.get_music_api", lambda: api)
    downloadjobs.reset_download_jobs()

    async def scenario():
        record, _ = await api.issue(99, "dl")
        headers = {"X-API-Key": record["key"]}
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            submitted = await client.post(
                "/v1/downloads", json={"video_id": "abc12345678"}, headers=headers
            )
            assert submitted.status == 202
            body = await submitted.json()
            assert body["ok"] and body["status"] in {"queued", "running"}
            job_id = body["job_id"]

            polled = None
            for _ in range(60):
                response = await client.get(f"/v1/downloads/{job_id}", headers=headers)
                polled = await response.json()
                if polled["status"] == "ready":
                    break
                await asyncio.sleep(0.02)
            assert polled["status"] == "ready"
            assert polled["download_url"].endswith(f"/downloads/{job_id}/file")

            fetched = await client.get(f"/v1/downloads/{job_id}/file", headers=headers)
            assert fetched.status == 200
            assert fetched.headers["Content-Type"].startswith("audio/")
            assert (await fetched.read()).startswith(b"ID3")

            listed = await client.get("/v1/downloads", headers=headers)
            listing = await listed.json()
            assert listing["count"] >= 1

            cancelled = await client.delete(f"/v1/downloads/{job_id}", headers=headers)
            assert cancelled.status == 202

            other, _ = await api.issue(100, "other")
            stranger = await client.get(
                f"/v1/downloads/{job_id}", headers={"X-API-Key": other["key"]}
            )
            assert stranger.status == 404

    asyncio.run(scenario())
    downloadjobs.reset_download_jobs()


def test_openapi_documents_the_download_routes():
    from vyron.api import openapi

    request = types.SimpleNamespace(
        headers={}, scheme="https", host="vyron.test", app={}, query={}
    )
    spec = openapi.spec(request)
    for path in ("/downloads", "/downloads/{job_id}", "/downloads/{job_id}/file"):
        assert path in spec["paths"]
    assert "DownloadJob" in spec["components"]["schemas"]


# ── video when YouTube will not give up a picture ───────────────────────────
def test_a_walled_video_request_becomes_the_same_song_in_a_real_mp4(tmp_path, monkeypatch):
    """The file people asked for must still exist: audio + artwork → MP4."""
    from vyron.core import downloader as module

    dl = _downloader(tmp_path)
    track = Track(
        id="pY9QhZkvBCQ",
        title="Believer",
        duration=204,
        uploader="Imagine Dragons",
        thumbnail="https://img.example/cover.jpg",
    )

    async def fake_find(_track, *, settings=None, fresh=False):
        return Track(
            id="saavn:1",
            title="Believer",
            duration=204,
            uploader="Imagine Dragons",
            url="https://cdn.example/believer.mp3",
            source="jiosaavn",
        )

    async def fake_stream(_track, *, on_progress=None):
        path = dl.settings.downloads_dir / "saavn-1.mp3"
        path.write_bytes(b"ID3" + b"0" * 64)
        return path

    async def fake_frame(_track):
        return b"\xff\xd8\xff" + b"0" * 32

    built: list[list[str]] = []

    class Result:
        returncode = 0
        stderr = b""

    def fake_run(args, **kwargs):
        built.append(list(args))
        from pathlib import Path

        Path(args[-1]).write_bytes(b"\x00" * 128)  # a non-empty "mp4"
        return Result()

    monkeypatch.setattr("vyron.core.alternate.find", fake_find)
    monkeypatch.setattr(dl, "_download_stream", fake_stream)
    monkeypatch.setattr(dl, "_video_frame", fake_frame)
    monkeypatch.setattr(module, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(module.subprocess, "run", fake_run)

    path = asyncio.run(dl._video_from_substitute(track))

    assert path.suffix == ".mp4" and path.stat().st_size > 0
    assert "-loop" in built[0] and "libx264" in built[0]
    assert "1280:720" in " ".join(built[0])
    # the frame working directory never survives
    assert not list(dl.settings.downloads_dir.glob(".video-*"))


def test_a_video_request_falls_back_before_it_gives_up(tmp_path, monkeypatch):
    """yt-dlp refused, no mirror had a URL — the substitute engine still runs."""
    from vyron.core import downloader as module

    dl = _downloader(tmp_path)
    track = Track(id="abcdefghijk", title="Believer", duration=204, uploader="x")

    def dead_ydl(_track, *, video=False, on_progress=None):
        raise module.DownloadError("failed to extract any player response")

    async def dead_direct(_track, *, video=False, on_progress=None):
        raise module.DownloadError("no mirror had a downloadable URL")

    async def built(_track, *, on_progress=None):
        path = dl.settings.downloads_dir / "youtube-abcdefghijk.mp4"
        path.write_bytes(b"\x00" * 64)
        return path

    monkeypatch.setattr(dl, "_download_ytdlp", dead_ydl)
    monkeypatch.setattr(dl, "_download_direct", dead_direct)
    monkeypatch.setattr(dl, "_video_from_substitute", built)

    path = asyncio.run(dl.video(track))

    assert path.suffix == ".mp4" and path.stat().st_size > 0


# ── a direct stream keeps the container it actually is ─────────────────────
def test_a_direct_m4a_is_not_labelled_mp3(tmp_path, monkeypatch):
    from vyron.core import accelerator, downloader as module

    dl = _downloader(tmp_path)
    monkeypatch.setattr(module, "ffmpeg_path", lambda: "")

    async def fake_fetch(url, target, **kwargs):
        target.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"0" * 64)

    monkeypatch.setattr(accelerator, "fetch", fake_fetch)
    track = Track(
        id="saavn1", title="Kesariya", duration=268, source="jiosaavn",
        url="https://cdn.example/kesariya.m4a",
    )

    path = asyncio.run(dl._download_stream(track))

    assert path.suffix == ".m4a"
    assert dl.cached(track) is not None  # still found by the cache
    assert not list(dl.settings.downloads_dir.glob(".stream-*"))


def test_a_direct_m4a_is_kept_instead_of_re_encoded(tmp_path, monkeypatch):
    """AAC in m4a is already what every player we serve accepts.

    Transcoding it to 320k MP3 was ten seconds of CPU per download and a worse
    file; the download is moved into the cache as it is.
    """
    from vyron.core import accelerator, downloader as module

    dl = _downloader(tmp_path)
    monkeypatch.setattr(module, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    async def fake_fetch(url, target, **kwargs):
        target.write_bytes(b"\x00\x00\x00\x20ftypM4A " + b"0" * 64)

    def boom(*args, **kwargs):  # pragma: no cover - ffmpeg must not run
        raise AssertionError("an m4a must not be re-encoded")

    monkeypatch.setattr(accelerator, "fetch", fake_fetch)
    monkeypatch.setattr(module.subprocess, "run", boom)
    track = Track(
        id="saavn2", title="Kesariya", duration=268, source="jiosaavn",
        url="https://cdn.example/kesariya.m4a",
    )

    path = asyncio.run(dl._download_stream(track))

    assert path.suffix == ".m4a" and path.stat().st_size > 0
    assert dl.cached(track) == path


def test_a_direct_webm_is_transcoded_to_mp3_when_ffmpeg_can(tmp_path, monkeypatch):
    """Telegram's audio player is picky: opus-in-webm is still converted."""
    from vyron.core import accelerator, downloader as module

    dl = _downloader(tmp_path)
    monkeypatch.setattr(module, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")

    async def fake_fetch(url, target, **kwargs):
        target.write_bytes(b"\x1a\x45\xdf\xa3" + b"0" * 64)

    built: list[list[str]] = []

    def fake_run(args, **kwargs):
        built.append(list(args))
        from pathlib import Path

        Path(args[-1]).write_bytes(b"ID3" + b"0" * 128)

        class Result:
            returncode = 0
            stderr = b""

        return Result()

    monkeypatch.setattr(accelerator, "fetch", fake_fetch)
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    track = Track(
        id="piped2", title="Kesariya", duration=268, source="soundcloud",
        url="https://cdn.example/kesariya.webm",
    )

    path = asyncio.run(dl._download_stream(track))

    assert path.suffix == ".mp3" and path.stat().st_size > 0
    assert f"{module.MP3_KBPS}k" in built[0]
    assert "libmp3lame" in built[0]


def test_the_download_honours_the_proxy_the_resolver_already_uses(tmp_path):
    """Only PROXY was read here, so YOUTUBE_PROXY proxied the metadata and left
    the download on the datacenter IP — the exact wall the proxy exists to avoid."""
    import dataclasses

    from vyron.core.downloader import Downloader

    proxied = dataclasses.replace(
        _settings(tmp_path),
        proxy="",
        youtube_proxy="http://proxy.example:8080",
    )
    downloader = Downloader(proxied)
    downloader.settings.ensure_dirs()
    assert downloader._base_opts()["proxy"] == "http://proxy.example:8080"

    # …and a plain PROXY still works, as does nothing at all.
    plain = Downloader(dataclasses.replace(proxied, youtube_proxy="", proxy="socks5://p.example:1080"))
    plain.settings.ensure_dirs()
    assert plain._base_opts()["proxy"] == "socks5://p.example:1080"

    bare = Downloader(dataclasses.replace(proxied, youtube_proxy="", proxy=""))
    bare.settings.ensure_dirs()
    assert "proxy" not in bare._base_opts()


def test_a_walled_ip_is_named_in_the_failure(tmp_path, monkeypatch):
    """"no mirror had a downloadable URL" told the operator nothing.

    When YouTube refuses the server, the download cannot be fixed by retrying —
    the message now says what is wrong and what to set.
    """
    from types import SimpleNamespace

    from vyron.runtime import runtime

    downloader = _downloader(tmp_path)
    monkeypatch.setattr(
        runtime,
        "youtube",
        SimpleNamespace(walled=lambda: True),
        raising=False,
    )
    reason = downloader._no_mirror_reason()
    assert "YOUTUBE_PROXY" in reason and "refusing this server" in reason

    monkeypatch.setattr(runtime, "youtube", SimpleNamespace(walled=lambda: False), raising=False)
    assert downloader._no_mirror_reason() == "no mirror had a downloadable URL"


def test_a_download_impersonates_the_browser_the_resolver_already_does(tmp_path, monkeypatch):
    """Naming a video as Chrome and downloading it as aiohttp is the wall.

    Search sets `impersonate` (TLS/JA3 fingerprint, header order); the download
    options did not, so a datacenter IP could find a song perfectly and then be
    refused when it asked for the bytes.
    """
    from vyron.core import search as search_module

    monkeypatch.setattr(search_module, "impersonate_target", lambda settings: "chrome-target")
    downloader = _downloader(tmp_path)
    assert downloader._base_opts().get("impersonate") == "chrome-target"

    monkeypatch.setattr(search_module, "impersonate_target", lambda settings: "")
    assert "impersonate" not in downloader._base_opts()


# ── the head start: yt-dlp first, the mirrors too if it is slow ─────────────
def _yt_track(ident: str = "ytrace1") -> Track:
    return Track(id=ident, title="Kesariya", duration=268, uploader="Arijit Singh", source="youtube")


def test_a_healthy_extraction_never_pays_for_a_second_download(tmp_path, monkeypatch):
    """The ladder keeps its head start: a normal download is never duplicated."""
    from vyron.core import downloader as module

    downloader = _downloader(tmp_path)
    started: list[int] = []

    def fake_ytdlp(track, *, video, on_progress=None, dest=None):
        path = dest or downloader.audio_path(track)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"from-yt-dlp")
        return path

    async def fake_tail(track, *, on_progress=None, errors=None):
        started.append(1)
        raise AssertionError("the fallbacks must not run for a fast extraction")

    monkeypatch.setattr(module, "HEAD_START", 5.0)
    monkeypatch.setattr(downloader, "_download_ytdlp", fake_ytdlp)
    monkeypatch.setattr(downloader, "_audio_tail", fake_tail)

    path = asyncio.run(downloader.fetch(_yt_track()))

    assert path.read_bytes() == b"from-yt-dlp"
    assert started == []


def test_a_slow_extraction_is_raced_by_the_mirrors(tmp_path, monkeypatch):
    """Twenty seconds of a failing ladder must not be the listener's problem."""
    import time

    from vyron.core import downloader as module

    downloader = _downloader(tmp_path)

    def slow_ytdlp(track, *, video, on_progress=None, dest=None):
        time.sleep(1.0)  # still running when the head start expires
        path = dest or downloader.audio_path(track)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"too-late")
        return path

    async def fast_tail(track, *, on_progress=None, errors=None):
        await asyncio.sleep(0.05)
        path = downloader.audio_path(track)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"from-a-mirror")
        return path

    monkeypatch.setattr(module, "HEAD_START", 0.2)
    monkeypatch.setattr(downloader, "_download_ytdlp", slow_ytdlp)
    monkeypatch.setattr(downloader, "_audio_tail", fast_tail)

    started = time.monotonic()
    path = asyncio.run(downloader.fetch(_yt_track()))
    elapsed = time.monotonic() - started

    assert path.read_bytes() == b"from-a-mirror"
    assert elapsed < 2.0, f"took {elapsed:.1f}s — the slow extraction was awaited"


def test_the_raced_extraction_cannot_overwrite_the_winner(tmp_path, monkeypatch):
    """A losing yt-dlp thread writes to its own path, never the cache."""
    import time

    from vyron.core import downloader as module

    downloader = _downloader(tmp_path)

    def late_ytdlp(track, *, video, on_progress=None, dest=None):
        assert dest is not None and dest != downloader.audio_path(track)
        time.sleep(0.3)  # the mirror wins the race
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"loser")
        return dest

    async def winning_tail(track, *, on_progress=None, errors=None):
        path = downloader.audio_path(track)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"winner")
        return path

    monkeypatch.setattr(module, "HEAD_START", 0.05)
    monkeypatch.setattr(downloader, "_download_ytdlp", late_ytdlp)
    monkeypatch.setattr(downloader, "_audio_tail", winning_tail)

    path = asyncio.run(downloader.fetch(_yt_track("ytrace2")))

    assert path.read_bytes() == b"winner"


def test_when_everything_fails_both_reasons_are_kept(tmp_path, monkeypatch):
    from vyron.core import downloader as module

    downloader = _downloader(tmp_path)

    def dead_ytdlp(track, *, video, on_progress=None, dest=None):
        raise module.DownloadError("Failed to extract any player response")

    async def dead_tail(track, *, on_progress=None, errors=None):
        # The real tail joins what the ladder already reported.
        raise module.DownloadError(" · ".join([*(errors or []), "mirror: no mirror had a downloadable URL"]))

    monkeypatch.setattr(module, "HEAD_START", 0.05)
    monkeypatch.setattr(downloader, "_download_ytdlp", dead_ytdlp)
    monkeypatch.setattr(downloader, "_audio_tail", dead_tail)

    try:
        asyncio.run(downloader.fetch(_yt_track("ytrace3")))
    except module.DownloadError as exc:
        text = str(exc)
        assert "player response" in text and "mirror" in text
    else:  # pragma: no cover
        raise AssertionError("a total failure must raise")


def test_a_raced_copy_keeps_its_real_container(tmp_path, monkeypatch):
    """AAC-in-m4a must not be renamed to .mp3 when it is adopted."""
    from vyron.core import downloader as module

    downloader = _downloader(tmp_path)

    def m4a_ytdlp(track, *, video, on_progress=None, dest=None):
        produced = (dest or downloader.audio_path(track)).with_suffix(".m4a")
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_bytes(b"aac")
        return produced

    monkeypatch.setattr(downloader, "_download_ytdlp", m4a_ytdlp)
    monkeypatch.setattr(module, "HEAD_START", 5.0)

    path = asyncio.run(downloader.fetch(_yt_track("ytrace4")))

    assert path.suffix == ".m4a"
    assert path.read_bytes() == b"aac"
    assert downloader.cached(_yt_track("ytrace4")) == path


# ── the last mirror tier: a URL, not a JSON document ───────────────────────
def _invidious_server(state: dict):
    """An instance whose JSON API is throttled but whose media endpoint works."""
    from aiohttp import web

    async def api(request):
        return web.Response(status=429, text="slow down")

    async def latest(request):
        state["asked"] += 1
        if state.get("broken"):
            return web.Response(status=404, text="no")
        raise web.HTTPFound("/media.m4a")

    async def media(request):
        return web.Response(body=b"\x00" * 64, content_type="audio/mp4")

    app = web.Application()
    app.router.add_get("/api/v1/videos/{vid}", api)
    app.router.add_get("/latest_version", latest)
    app.router.add_get("/media.m4a", media)
    return app


def test_a_media_endpoint_is_used_when_the_json_api_refuses():
    """`/latest_version?id=…&itag=140` needs no JSON and no API quota."""
    from aiohttp.test_utils import TestServer

    state = {"asked": 0}

    async def go():
        server = TestServer(_invidious_server(state))
        await server.start_server()
        try:
            host = str(server.make_url("/")).rstrip("/")  # keeps its scheme
            streams = PublicStreams()
            streams.invidious = (host,)
            streams.piped = ()
            streams.cobalt = ()
            stream = await streams.resolve("dQw4w9WgXcQ")
            assert stream is not None
            assert "/latest_version" in stream.url and "itag=140" in stream.url
            assert stream.kind == "audio" and stream.ext == "m4a"
            assert state["asked"] == 1
        finally:
            await server.close()

    asyncio.run(go())


def test_a_dead_media_endpoint_is_silent():
    from aiohttp.test_utils import TestServer

    state = {"asked": 0, "broken": True}

    async def go():
        server = TestServer(_invidious_server(state))
        await server.start_server()
        try:
            host = str(server.make_url("/")).rstrip("/").replace("http://", "")
            streams = PublicStreams()
            streams.invidious = (host,)
            streams.piped = ()
            streams.cobalt = ()
            assert await streams.resolve("dQw4w9WgXcQ") is None
        finally:
            await server.close()

    asyncio.run(go())


def test_a_failed_race_does_not_run_the_tail_twice(tmp_path, monkeypatch):
    """Both engines were just asked; asking the loser again only adds latency."""
    import time

    from vyron.core import downloader as module

    downloader = _downloader(tmp_path)
    calls = {"tail": 0}

    def slow_ytdlp(track, *, video, on_progress=None, dest=None):
        time.sleep(0.2)  # the head start expires first, so the race happens
        raise module.DownloadError("Failed to extract any player response")

    async def failing_tail(track, *, on_progress=None, errors=None):
        calls["tail"] += 1
        await asyncio.sleep(0.05)
        # The real tail records its reasons as each engine fails.
        (errors if errors is not None else []).append("mirror: no downloadable URL")
        raise module.DownloadError("mirror: no downloadable URL")

    monkeypatch.setattr(module, "HEAD_START", 0.05)
    monkeypatch.setattr(downloader, "_download_ytdlp", slow_ytdlp)
    monkeypatch.setattr(downloader, "_audio_tail", failing_tail)

    try:
        asyncio.run(downloader.fetch(_yt_track("ytrace5")))
    except module.DownloadError as exc:
        text = str(exc)
        assert "mirror" in text and text.strip(), text
    else:  # pragma: no cover
        raise AssertionError("a total failure must raise")
    assert calls["tail"] == 1, calls  # the race already asked it once
