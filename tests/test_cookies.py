"""Cookie tests — a stale jar is the wall coming back, so the file looks after itself.

The rules under test:

* only a real Netscape jar is ever installed (a placeholder or an HTML error page
  must never overwrite a working file);
* `COOKIES_FILE` wins over everything and is never rewritten;
* `COOKIES_URL` is re-read when it is older than `REFRESH_SECONDS`, or on demand
  after a detected wall;
* nothing here ever raises into the caller.
"""
from __future__ import annotations

import asyncio
import dataclasses
import time
from pathlib import Path

from vyron.config import Settings
from vyron.core import cookies

JAR = (
    "# Netscape HTTP Cookie File\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1900000000\tSID\treal-session-value\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1900000000\tHSID\tanother-real-value\n"
)


def settings_for(tmp_path: Path, **overrides) -> Settings:
    base = dataclasses.replace(Settings(), data_dir=str(tmp_path), **overrides)
    return base


def test_a_real_jar_is_usable_and_placeholders_are_not():
    assert cookies.usable(JAR) is True
    assert cookies.usable("") is False
    assert cookies.usable("# Netscape HTTP Cookie File\n") is False
    assert cookies.usable("<html><body>404</body></html>") is False
    assert cookies.usable('{"cookies": []}') is False
    assert cookies.usable(".youtube\tTRUE\t/\tTRUE\t1900\tSID\tpaste-your-cookies") is False
    # too few columns to be a jar at all
    assert cookies.usable("youtube.com\tSID\tabc") is False


def test_install_writes_the_file_and_marks_the_source(tmp_path):
    cookies.reset()
    target = tmp_path / "youtube-cookies.txt"

    installed = cookies.install(JAR, target)

    assert installed == str(target)
    assert target.read_text(encoding="utf-8").endswith("\n")
    assert cookies.path() == str(target)
    assert cookies.source() == "url"
    # 0600 unless the filesystem has no modes
    assert target.stat().st_mode & 0o077 == 0
    cookies.reset()


def test_a_url_jar_is_downloaded_once_then_reused(tmp_path, monkeypatch):
    cookies.reset()
    calls: list[str] = []

    async def fake_download(url, timeout=20.0):
        calls.append(url)
        return JAR

    monkeypatch.setattr(cookies, "download", fake_download)
    settings = settings_for(tmp_path, cookies_url="https://example.invalid/jar.txt")

    first = asyncio.run(cookies.refresh(settings))
    second = asyncio.run(cookies.refresh(settings))

    assert first == second == str(tmp_path / "youtube-cookies.txt")
    assert calls == ["https://example.invalid/jar.txt"]  # the second call was a no-op
    cookies.reset()


def test_a_bad_body_never_replaces_a_working_jar(tmp_path, monkeypatch):
    cookies.reset()
    target = tmp_path / "youtube-cookies.txt"
    target.write_text(JAR, encoding="utf-8")
    cookies.adopt(str(target))
    before = target.read_text(encoding="utf-8")

    async def broken_download(url, timeout=20.0):
        return "<html>502 bad gateway</html>"

    monkeypatch.setattr(cookies, "download", broken_download)
    settings = settings_for(tmp_path, cookies_url="https://example.invalid/jar.txt")

    kept = asyncio.run(cookies.refresh(settings, force=True))

    assert kept == str(target)
    assert target.read_text(encoding="utf-8") == before
    cookies.reset()


def test_a_network_error_is_not_fatal(tmp_path, monkeypatch):
    cookies.reset()

    async def boom(url, timeout=20.0):
        raise OSError("no route to host")

    monkeypatch.setattr(cookies, "download", boom)
    settings = settings_for(tmp_path, cookies_url="https://example.invalid/jar.txt")

    assert asyncio.run(cookies.refresh(settings, force=True)) == ""
    cookies.reset()


def test_cookies_file_wins_and_is_never_rewritten(tmp_path, monkeypatch):
    cookies.reset()
    operator = tmp_path / "mine.txt"
    operator.write_text(JAR, encoding="utf-8")

    async def should_not_run(url, timeout=20.0):  # pragma: no cover - guarded
        raise AssertionError("COOKIES_FILE must win over COOKIES_URL")

    monkeypatch.setattr(cookies, "download", should_not_run)
    settings = settings_for(
        tmp_path,
        cookies_file=str(operator),
        cookies_url="https://example.invalid/jar.txt",
    )

    assert asyncio.run(cookies.refresh(settings, force=True)) == str(operator)
    assert cookies.source() == "file"
    cookies.reset()


def test_age_tracks_the_file_on_disk(tmp_path):
    cookies.reset()
    target = tmp_path / "youtube-cookies.txt"
    cookies.install(JAR, target)
    old = time.time() - 7200
    import os

    os.utime(target, (old, old))
    assert 7000 < cookies.age() < 7400
    cookies.reset()


def test_refresh_without_a_url_or_file_is_a_no_op(tmp_path):
    cookies.reset()
    assert asyncio.run(cookies.refresh(settings_for(tmp_path))) == ""
    cookies.reset()


def test_maintenance_refreshes_cookies_each_sweep(monkeypatch):
    """Housekeeping owns the freshness: no operator should have to remember."""
    from vyron.core import maintenance

    seen: list[bool] = []

    async def fake_refresh(settings, *, force=False):
        seen.append(force)
        return "/tmp/jar.txt"

    monkeypatch.setattr(cookies, "refresh", fake_refresh)
    monkeypatch.setattr(maintenance, "purge_keys", lambda days=None: _noop())

    result = asyncio.run(maintenance.run_once())

    assert seen == [False]
    assert set(result) == {"files", "rows", "keys"}


async def _noop():
    return 0


def test_a_real_http_server_jar_is_downloaded_end_to_end(tmp_path):
    """No fakes: a local HTTP server, the real transport, the real parse."""
    import http.server
    import threading

    served = tmp_path / "served"
    served.mkdir()
    (served / "cookies.txt").write_text(JAR, encoding="utf-8")

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(served), **kwargs)

        def log_message(self, *args):  # keep the test output clean
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        cookies.reset()
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/cookies.txt"
        target = tmp_path / "data"
        settings = settings_for(target, cookies_url=url)

        installed = asyncio.run(cookies.refresh(settings, force=True))

        assert installed == str(target / "youtube-cookies.txt")
        assert Path(installed).read_text(encoding="utf-8").strip() == JAR.strip()
        assert cookies.usable(Path(installed).read_text(encoding="utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        cookies.reset()
        # The transport is shared across the process; close it so the test run
        # does not end on aiohttp's "unclosed client session" warning.
        from vyron.utils import net

        asyncio.run(net.close())
