# ---------------------------------------------------------------------------
#  VYRON — file downloads (audio / video) with an on-disk cache
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Callable

import yt_dlp

from vyron.config import Settings
from vyron.core.queue import Track

logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^\w\-. ()\[\]]+", re.UNICODE)


class DownloadError(RuntimeError):
    pass


def safe_stem(text: str, limit: int = 70) -> str:
    cleaned = _SAFE_RE.sub("_", text or "track").strip(" ._")
    return (cleaned or "track")[:limit]


class Downloader:
    """Downloads one track at a time per call, reusing previously cached files."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()

    # ── paths ──────────────────────────────────────────────────────────────
    def audio_path(self, track: Track) -> Path:
        return self.settings.downloads_dir / f"{track.source}-{track.id}.mp3"

    def video_path(self, track: Track) -> Path:
        return self.settings.downloads_dir / f"{track.source}-{track.id}.mp4"

    def cached(self, track: Track, *, video: bool = False) -> Path | None:
        path = self.video_path(track) if video else self.audio_path(track)
        if path.is_file() and path.stat().st_size > 0:
            return path
        return None

    # ── yt-dlp options ─────────────────────────────────────────────────────
    def _base_opts(self) -> dict:
        opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "geo_bypass": True,
            "nocheckcertificate": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 20,
            "max_filesize": self.settings.max_download_mb * 1024 * 1024,
            "outtmpl": str(self.settings.downloads_dir / "%(autonumber)s-%(id)s.%(ext)s"),
            "noplaylist": True,
        }
        if self.settings.cookies_file:
            opts["cookiefile"] = self.settings.cookies_file
        if self.settings.proxy:
            opts["proxy"] = self.settings.proxy
        return opts

    # ── public API ─────────────────────────────────────────────────────────
    async def audio(
        self,
        track: Track,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        cached = self.cached(track)
        if cached:
            cached.touch()
            return cached

        def _work() -> Path:
            target = self.audio_path(track)
            opts = self._base_opts()
            opts.update(
                {
                    "format": "bestaudio/best",
                    "outtmpl": str(target),
                    "postprocessors": [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": "mp3",
                            "preferredquality": "192",
                        },
                        {"key": "FFmpegMetadata", "add_metadata": True},
                        {"key": "EmbedThumbnail", "already_have_thumbnail": False},
                    ],
                    "writethumbnail": True,
                }
            )
            if progress:
                progress("downloading")
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([track.url or track.watch_url])
            if not target.is_file():
                raise DownloadError("The audio file could not be created.")
            if target.stat().st_size > self.settings.max_download_mb * 1024 * 1024:
                target.unlink(missing_ok=True)
                raise DownloadError("That file is larger than the allowed size.")
            return target

        try:
            return await asyncio.to_thread(_work)
        except DownloadError:
            raise
        except Exception as exc:
            logger.warning("audio download failed: %s", exc)
            raise DownloadError(str(exc)) from exc

    async def video(
        self,
        track: Track,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> Path:
        cached = self.cached(track, video=True)
        if cached:
            cached.touch()
            return cached

        height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
            self.settings.video_quality, 720
        )

        def _work() -> Path:
            target = self.video_path(track)
            opts = self._base_opts()
            opts.update(
                {
                    "format": (
                        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                        f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
                    ),
                    "outtmpl": str(target),
                    "merge_output_format": "mp4",
                }
            )
            if progress:
                progress("downloading")
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([track.url or track.watch_url])
            if not target.is_file():
                raise DownloadError("The video file could not be created.")
            return target

        try:
            return await asyncio.to_thread(_work)
        except DownloadError:
            raise
        except Exception as exc:
            logger.warning("video download failed: %s", exc)
            raise DownloadError(str(exc)) from exc

    # ── maintenance ────────────────────────────────────────────────────────
    def cleanup(self) -> int:
        """Delete cache entries older than DOWNLOAD_CACHE_HOURS."""
        cutoff = time.time() - self.settings.download_cache_hours * 3600
        removed = 0
        for path in self.settings.downloads_dir.glob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def cache_size(self) -> int:
        total = 0
        for path in self.settings.downloads_dir.glob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total


__all__ = ["DownloadError", "Downloader", "safe_stem"]
