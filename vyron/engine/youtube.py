# ---------------------------------------------------------------------------
#  VYRON — the download engine
# ---------------------------------------------------------------------------
# Derived from the Eldian Music API (github.com/Eldian-Network/eldian-music-api),
# MIT License — Copyright (c) 2026 Eldian Network.
#
# What is theirs: the yt-dlp option set, the retry ladder, proxy/cookies
# validation, the "one directory per request, delete it afterwards" lifecycle
# and the stale-directory sweep.
# What is VYRON's: the settings layer, cancellation-friendly async wrapper,
# typed errors instead of framework exceptions, and the HTTP surface in
# routes.py (paths, keys, envelopes, headers).
#
# The MIT notice lives here, above the code it covers.
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import yt_dlp

from vyron.config import Settings, settings

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https", "socks4", "socks5"}
_PARTIAL_SUFFIXES = {".part", ".ytdl", ".temp"}


class EngineError(RuntimeError):
    """A download failure carrying the HTTP status the API should answer with."""

    def __init__(self, message: str, status: int = 502, *, code: str = "download_failed") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


# ── input validation ───────────────────────────────────────────────────────
def validate_proxy(proxy: str) -> str:
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.netloc:
        raise EngineError("Invalid proxy URL", 400, code="bad_config")
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise EngineError("Unsupported proxy scheme", 400, code="bad_config")
    return proxy


def validate_cookies(cookies: str | None, cookies_file: str | None) -> None:
    if cookies and cookies_file:
        raise EngineError("Provide either cookies or a cookies file, not both", 400, code="bad_config")
    if cookies is not None and not cookies.strip():
        raise EngineError("Cookies string cannot be empty", 400, code="bad_config")
    if cookies_file is not None and not Path(cookies_file).exists():
        raise EngineError("Cookies file does not exist", 400, code="bad_config")


def _first_line(path: str | None) -> str | None:
    """First usable proxy from a list file (Eldian's proxies.txt rule)."""
    if not path:
        return None
    candidate = Path(path)
    if not candidate.exists():
        return None
    for line in candidate.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        return cleaned
    return None


# ── yt-dlp ─────────────────────────────────────────────────────────────────
def build_options(cfg: Settings, output_dir: Path, video_id: str) -> dict:
    """The upstream option set, with VYRON's settings object as the source."""
    options: dict = {
        "format": cfg.yt_dlp_format,
        "outtmpl": str(output_dir / f"{video_id}.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": cfg.yt_dlp_socket_timeout,
        "retries": cfg.yt_dlp_retries,
        "fragment_retries": cfg.yt_dlp_retries,
        "continuedl": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "max_filesize": cfg.max_download_mb * 1024 * 1024,
    }

    cookies_text = (cfg.cookies_text or "").strip() or None
    cookies_file = cfg.youtube_cookies_file or cfg.cookies_file or None
    validate_cookies(cookies_text, cookies_file)
    if cookies_text:
        # A cookie *string* is not a cookie jar: hand it over as a header so a
        # deploy with no writable volume can still use an authenticated login.
        options["http_headers"] = {"Cookie": cookies_text}
    elif cookies_file:
        options["cookiefile"] = cookies_file

    proxy = cfg.youtube_proxy or cfg.proxy or _first_line(getattr(cfg, "youtube_proxy_file", None))
    if proxy:
        options["proxy"] = validate_proxy(proxy)
    return options


def _pick(directory: Path, video_id: str) -> Path | None:
    candidates = [
        candidate
        for candidate in sorted(directory.glob(f"{video_id}.*"))
        if candidate.is_file()
        and candidate.suffix not in _PARTIAL_SUFFIXES
        and candidate.stat().st_size > 0
    ]
    return candidates[0] if candidates else None


def download_audio(
    video_id: str,
    output_dir: Path,
    *,
    cfg: Settings | None = None,
    attempts: int | None = None,
) -> Path:
    """Download the audio track for `video_id` into `output_dir` (blocking)."""
    cfg = cfg or settings
    output_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://www.youtube.com/watch?v={video_id}"
    options = build_options(cfg, output_dir, video_id)
    tries = max(1, attempts or cfg.yt_dlp_retries)

    last_error: Exception | None = None
    info: dict | None = None
    for attempt in range(1, tries + 1):
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except Exception as exc:  # yt-dlp raises a wide family of errors
            last_error = exc
            logger.warning(
                "engine: attempt %s/%s failed for %s: %s", attempt, tries, video_id, exc
            )
            if attempt < tries:
                time.sleep(min(4, attempt))

    if info is None:
        raise EngineError(f"Unable to download track after retries: {last_error}")

    path = _pick(output_dir, video_id)
    if path is None:
        raise EngineError("Downloaded file was not created", 500)
    return path


async def download_audio_async(
    video_id: str,
    output_dir: Path,
    *,
    cfg: Settings | None = None,
    attempts: int | None = None,
) -> Path:
    """Run :func:`download_audio` off the event loop."""
    return await asyncio.to_thread(
        download_audio, video_id, output_dir, cfg=cfg, attempts=attempts
    )


# ── lifecycle ──────────────────────────────────────────────────────────────
def new_request_dir(base: Path | None = None, *, cfg: Settings | None = None) -> Path:
    cfg = cfg or settings
    path = (base or cfg.downloads_dir) / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_download(path: Path) -> None:
    if path.exists():
        path.unlink(missing_ok=True)
    parent = path.parent
    if parent.exists() and not any(parent.iterdir()):
        shutil.rmtree(parent, ignore_errors=True)


def cleanup_stale_downloads(base_dir: Path, *, cfg: Settings | None = None) -> int:
    """Delete per-request directories older than DOWNLOAD_CLEANUP_SECONDS."""
    cfg = cfg or settings
    if not base_dir.exists():
        return 0
    cutoff = time.time() - cfg.download_cleanup_seconds
    removed = 0
    for candidate in base_dir.iterdir():
        if not candidate.is_dir():
            continue
        try:
            if candidate.stat().st_mtime < cutoff:
                shutil.rmtree(candidate, ignore_errors=True)
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def engine_status(cfg: Settings | None = None) -> dict:
    """Non-secret description of the engine, for /vyron/health."""
    cfg = cfg or settings
    return {
        "format": cfg.yt_dlp_format,
        "socket_timeout": cfg.yt_dlp_socket_timeout,
        "retries": cfg.yt_dlp_retries,
        "cleanup_seconds": cfg.download_cleanup_seconds,
        "cookies": bool(cfg.cookies_text or cfg.youtube_cookies_file or cfg.cookies_file),
        "proxy": bool(cfg.youtube_proxy or cfg.proxy),
        "downloads_dir": str(cfg.downloads_dir),
    }


__all__ = [
    "EngineError",
    "build_options",
    "cleanup_download",
    "cleanup_stale_downloads",
    "download_audio",
    "download_audio_async",
    "engine_status",
    "new_request_dir",
    "validate_cookies",
    "validate_proxy",
]
