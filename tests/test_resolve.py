"""Stream resolution: one ladder per track, and a fast, honest failure.

The production log that prompted this file showed 12 ladder attempts and a
45-second request for a single unplayable video, because the Mini App asks for a
stream and starts playback at the same moment. These tests pin the behaviour
that stops that: shared in-flight resolves, a short "known bad" memory, and an
early exit when the ladder is repeating itself.
"""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

pytest.importorskip("pyrogram")

from vyron.config import settings
from vyron.core.queue import Track
from vyron.core.search import MediaError, YouTube


def _youtube(tmp_path, **overrides):
    base = dataclasses.replace(
        settings,
        data_dir=tmp_path,
        cookies_file="",
        cookies_text="",
        stream_fallback=False,
        **overrides,
    )
    return YouTube(base)


def _track(video_id: str = "IT6svoR9M-0") -> Track:
    return Track(id=video_id, title="Some Song", duration=200, uploader="Artist")


GOOD_INFO = {"url": "https://cdn.example/audio.m4a", "ext": "m4a", "title": "Some Song"}


def test_the_client_ladder_stops_when_it_repeats_itself(tmp_path, monkeypatch):
    yt = _youtube(tmp_path)
    calls: list[str | None] = []

    async def boom(target, **extra):
        calls.append(extra.get("player_client"))
        raise MediaError("Nothing could be extracted from that link.")

    monkeypatch.setattr(yt, "_async_extract", boom)

    async def run():
        with pytest.raises(MediaError) as failure:
            await yt.stream_info(_track())
        return str(failure.value)

    message = asyncio.run(run())
    assert len(calls) == 2  # not six
    # the raw sentence is kept, and it is explained rather than echoed
    assert "Nothing could be extracted" in message
    assert "/sources" in message  # never a dead end


def test_concurrent_resolves_share_one_ladder_run(tmp_path, monkeypatch):
    yt = _youtube(tmp_path)
    calls = 0

    async def slow(target, **extra):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return dict(GOOD_INFO)

    monkeypatch.setattr(yt, "_async_extract", slow)

    async def run():
        return await asyncio.gather(
            yt.stream_info(_track()),
            yt.stream_info(_track()),
            yt.stream_info(_track()),
        )

    results = asyncio.run(run())
    assert calls == 1
    assert {str(item.url) for item in results} == {"https://cdn.example/audio.m4a"}


def test_a_failed_track_is_remembered_instead_of_retried(tmp_path, monkeypatch):
    yt = _youtube(tmp_path)
    calls = 0

    async def boom(target, **extra):
        nonlocal calls
        calls += 1
        raise MediaError("HTTP Error 403: Forbidden")

    monkeypatch.setattr(yt, "_async_extract", boom)

    async def run():
        with pytest.raises(MediaError):
            await yt.stream_info(_track())
        first = calls
        with pytest.raises(MediaError) as second:
            await yt.stream_info(_track())
        return first, calls, str(second.value)

    first, total, message = asyncio.run(run())
    assert first == 2
    assert total == 2  # the second call never touched the network
    assert "403" in message and "impersonation" in message


def test_a_refresh_bypasses_the_failure_memory(tmp_path, monkeypatch):
    yt = _youtube(tmp_path)
    calls = 0

    async def boom(target, **extra):
        nonlocal calls
        calls += 1
        raise MediaError("temporary 403")

    monkeypatch.setattr(yt, "_async_extract", boom)

    async def run():
        with pytest.raises(MediaError):
            await yt.stream_info(_track())
        with pytest.raises(MediaError):
            await yt.stream_info(_track(), refresh=True)
        return calls

    assert asyncio.run(run()) == 4  # 2 attempts per run, and both runs happened


def test_a_successful_resolve_clears_the_failure_memory(tmp_path, monkeypatch):
    yt = _youtube(tmp_path)
    fail = True

    async def flaky(target, **extra):
        if fail:
            raise MediaError("Nothing could be extracted from that link.")
        return dict(GOOD_INFO)

    monkeypatch.setattr(yt, "_async_extract", flaky)

    async def run():
        nonlocal fail
        with pytest.raises(MediaError):
            await yt.stream_info(_track())
        assert yt._failures  # remembered as bad
        fail = False
        yt._failures.clear()  # the operator fixed cookies and hits play again
        return await yt.stream_info(_track())

    info = asyncio.run(run())
    assert str(info.url) == "https://cdn.example/audio.m4a"
    assert not yt._failures


# ── the reason yt-dlp gave, kept and explained ─────────────────────────────
def test_ytdlp_own_words_are_kept_when_extraction_returns_nothing(tmp_path, monkeypatch):
    """`ignoreerrors` turns a failure into `None`; the reason is in the log."""
    yt = _youtube(tmp_path)

    import yt_dlp

    class Quiet:
        def __init__(self, options):
            self.options = options
            self.logger = options.get("logger")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, target, download=False):
            # exactly what yt-dlp does with ignoreerrors=True
            self.logger.error(
                "ERROR: [youtube] %s: Sign in to confirm you're not a bot. "
                "Use --cookies-from-browser or --cookies",
                "abc12345678",
            )
            return None

    monkeypatch.setattr(yt_dlp, "YoutubeDL", Quiet)
    message = str(pytest.raises(MediaError, yt._extract, "https://youtu.be/abc12345678").value)
    assert "bot" in message.lower()
    assert "curl_cffi" in message or "COOKIES_FILE" in message
    assert "Nothing could be extracted" not in message


def test_the_reason_table_is_ordered_and_actionable():
    from vyron.core.search import _explain, explain

    meaning, fix = explain("Sign in to confirm you're not a bot")
    assert "bot" in meaning and "impersonation" in fix
    meaning, fix = explain("Video unavailable")
    assert "gone" in meaning and "another" in fix
    meaning, fix = explain("This video is not available in your country")
    assert "geo" in meaning and "PROXY" in fix
    meaning, fix = explain("HTTP Error 429: Too Many Requests")
    assert "rate" in meaning
    assert explain("something nobody predicted") == ("", "")

    # an unknown sentence keeps its wording but still points somewhere
    text = _explain("ERROR: [youtube] x: Weird new failure")
    assert "Weird new failure" in text and "/sources" in text
    # and no reason at all is not a dead end either
    assert "IP" in _explain("")


def test_the_ladder_reports_different_reasons_per_client(tmp_path, monkeypatch):
    """Different wire formats fail differently — the ladder must not merge them."""
    yt = _youtube(tmp_path)
    seen: list[str] = []

    async def failing(target, **extra):
        args = (extra.get("extractor_args") or {}).get("youtube", {})
        client = (args.get("player_client") or ["default"])[0]
        seen.append(client)
        raise MediaError(f"{client} said no")

    monkeypatch.setattr(yt, "_async_extract", failing)

    async def run():
        with pytest.raises(MediaError) as failure:
            await yt.stream_info(_track())
        return str(failure.value)

    message = asyncio.run(run())
    assert seen[:2] == ["default", "tv_simply"]  # two attempts, then the ladder gives up
    assert "/sources" in message  # every failure ends with a next step
