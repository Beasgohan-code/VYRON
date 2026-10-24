# ---------------------------------------------------------------------------
#  VYRON — file downloads (audio / video) with an on-disk cache
# ---------------------------------------------------------------------------
# Downloading is where music bots usually fall over, so this module is built
# around three rules:
#
#   1. **Never trust one yt-dlp invocation.** YouTube issues a different set of
#      formats to each player client and rotates which ones need a PO token.
#      The download therefore walks the same client ladder the stream resolver
#      uses (default → android_vr → ios) and only gives up after all of them.
#   2. **Never leave a half file where the cache will find it.** yt-dlp writes
#      into a private temp directory; the finished file is moved into place in
#      one atomic rename. A crashed download can no longer masquerade as a
#      cached track and be served forever.
#   3. **Have a second engine.** If yt-dlp cannot produce a file at all, the
#      direct URL from Invidious/Piped is transcoded with ffmpeg (or saved raw
#      when ffmpeg is missing) — the exact fallback chain the music API and
#      `/song` share.
from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

import yt_dlp

from vyron.config import Settings
from vyron.core.queue import Track

logger = logging.getLogger(__name__)

_SAFE_RE = re.compile(r"[^\w\-. ()\[\]]+", re.UNICODE)
AUDIO_EXTS = ("mp3", "m4a", "opus", "webm", "ogg", "aac")
VIDEO_EXTS = ("mp4", "webm", "mkv")

# yt-dlp clients, in the order that keeps working when web starts demanding a
# PO token. `None` means "whatever yt-dlp picks", which is still the best first
# bet on an IP that YouTube likes.
CLIENT_LADDER: tuple[str | None, ...] = (None, "android_vr", "ios", "tv")

ProgressHook = Callable[[float, str], None]

#: MP3 bitrate for anything this module has to transcode. 320 is the ceiling
#: listeners can hear on a phone, and the catalogues already serve that.
MP3_KBPS = "320"
#: AAC bitrate inside the generated MP4 — the video's sound, not its picture.
VIDEO_AUDIO_KBPS = "256"


class DownloadError(RuntimeError):
    pass


def safe_stem(text: str, limit: int = 70) -> str:
    cleaned = _SAFE_RE.sub("_", text or "track").strip(" ._")
    return (cleaned or "track")[:limit]


def ffmpeg_path() -> str:
    """`ffmpeg` on PATH, or "" — the Docker image ships it, bare hosts may not."""
    return shutil.which("ffmpeg") or ""


def _atomic_move(source: Path, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() == target.resolve():
        return target
    try:
        source.replace(target)
    except OSError:  # different filesystems
        shutil.copyfile(source, target)
        source.unlink(missing_ok=True)
    return target


class Downloader:
    """Downloads one track at a time per call, reusing previously cached files."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self._locks: dict[str, asyncio.Lock] = {}

    # ── what the resolver already knows ────────────────────────────────────
    def _youtube_walled(self) -> bool:
        """True while the stream resolver knows YouTube is refusing this host.

        Production showed the cost of not asking: a walled server still walked
        four yt-dlp clients (16 s each, 49 s in total) before falling back to
        the mirror that actually had the song. The wall is the *same* fact for
        both engines, so the downloader reads it instead of re-proving it.
        """
        try:
            from vyron.runtime import runtime

            engine = getattr(runtime, "youtube", None)
            return bool(engine is not None and engine.walled())
        except Exception:  # pragma: no cover - runtime not up yet
            return False

    def _note_wall(self, message: str) -> None:
        """Tell the resolver what this attempt just learned about YouTube."""
        try:
            from vyron.runtime import runtime

            engine = getattr(runtime, "youtube", None)
            if engine is not None:
                engine._note_wall(message)
        except Exception:  # pragma: no cover - runtime not up yet
            pass

    # ── paths ──────────────────────────────────────────────────────────────
    def audio_path(self, track: Track) -> Path:
        return self.settings.downloads_dir / f"{track.source}-{track.id}.mp3"

    def video_path(self, track: Track) -> Path:
        return self.settings.downloads_dir / f"{track.source}-{track.id}.mp4"

    def _existing(self, track: Track, exts: tuple[str, ...]) -> Path | None:
        for ext in exts:
            path = self.settings.downloads_dir / f"{track.source}-{track.id}.{ext}"
            if path.is_file() and path.stat().st_size > 0:
                return path
        return None

    def cached(self, track: Track, *, video: bool = False) -> Path | None:
        path = self._existing(track, VIDEO_EXTS if video else AUDIO_EXTS)
        if path:
            path.touch()
        return path

    def _lock(self, key: str) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    # ── accelerators ───────────────────────────────────────────────────────
    def accelerator_order(self) -> tuple[str, ...]:
        """`DOWNLOAD_ACCELERATOR` → the tools to try, in order."""
        preference = (getattr(self.settings, "download_accelerator", "") or "auto").lower()
        if preference in {"none", "off", "aiohttp", "builtin"}:
            return ()
        if preference in {"aria2", "aria2c"}:
            return ("aria2", "curl")
        if preference == "curl":
            return ("curl", "aria2")
        return ("aria2", "curl")

    def _external_downloader(self) -> dict:
        """yt-dlp's own hand-off: aria2c gets the media, yt-dlp gets the info.

        This is what makes a `.m4a` land in two seconds instead of twenty, and
        unlike a post-download accelerator it works for formats that need the
        extractor to authorise each fragment.
        """
        import shutil

        preference = (getattr(self.settings, "download_accelerator", "") or "auto").lower()
        if preference not in {"auto", "aria2", "aria2c"}:
            return {}
        binary = shutil.which("aria2c")
        if not binary:
            return {}
        return {
            "external_downloader": {"default": binary},
            "external_downloader_args": {
                "default": [
                    "-x", "16",
                    "-s", "16",
                    "-k", "1M",
                    "--min-split-size=1M",
                    "--file-allocation=none",
                    "--console-log-level=error",
                ]
            },
        }

    # ── yt-dlp options ─────────────────────────────────────────────────────
    def _base_opts(self) -> dict:
        opts: dict = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "geo_bypass": True,
            "nocheckcertificate": True,
            "noplaylist": True,
            "ignoreerrors": False,
            # Retries are *per request*; the client ladder below handles the
            # case where the whole extraction is refused.
            "retries": 3,
            "fragment_retries": 4,
            "socket_timeout": 20,
            "max_filesize": self.settings.max_download_mb * 1024 * 1024,
            "nopart": False,
            "overwrites": True,
        }
        if self.settings.cookies_file:
            opts["cookiefile"] = self.settings.cookies_file
        if self.settings.proxy:
            opts["proxy"] = self.settings.proxy
        if self.settings.ytdlp_args:
            try:
                from vyron.core.search import YouTube

                opts.update(YouTube._parse_ytdlp_args(self.settings.ytdlp_args))
            except Exception:  # pragma: no cover - operator args are advisory
                pass
        opts.update(self._external_downloader())
        return opts

    def _attempts(self) -> list[tuple[str, dict]]:
        attempts: list[tuple[str, dict]] = []
        for client in CLIENT_LADDER:
            extra: dict = {}
            if client:
                extra["extractor_args"] = {"youtube": {"player_client": [client]}}
            attempts.append((client or "default", extra))
        return attempts

    @staticmethod
    def _hook(on_progress: ProgressHook | None, label: str):
        def hook(data: dict) -> None:
            if not on_progress:
                return
            status = str(data.get("status") or "")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                done = data.get("downloaded_bytes") or 0
                fraction = float(done) / float(total) if total else 0.0
                on_progress(min(0.99, fraction), f"{label} {int(fraction * 100)}%")
            elif status == "finished":
                on_progress(0.99, f"{label} — converting")
            elif status == "postprocessing":
                on_progress(0.99, f"{label} — finishing")

        return hook

    # ── yt-dlp engine ──────────────────────────────────────────────────────
    def _download_ytdlp(
        self,
        track: Track,
        *,
        video: bool,
        on_progress: ProgressHook | None = None,
    ) -> Path:
        height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
            self.settings.video_quality, 720
        )
        final = self.video_path(track) if video else self.audio_path(track)
        work = self.settings.downloads_dir / f".work-{track.id}"
        work.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None

        same_error = 0
        for name, extra in self._attempts():
            work.mkdir(parents=True, exist_ok=True)
            for leftover in work.glob("*"):
                try:
                    leftover.unlink()
                except OSError:
                    pass
            opts = self._base_opts()
            opts.update(extra)
            opts.update(
                {
                    "outtmpl": str(work / "track.%(ext)s"),
                    "progress_hooks": [self._hook(on_progress, "downloading")],
                }
            )
            if video:
                opts.update(
                    {
                        "format": (
                            f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
                            f"best[height<={height}][ext=mp4]/best[height<={height}]/best"
                        ),
                        "merge_output_format": "mp4",
                    }
                )
            else:
                opts.update(
                    {
                        "format": "bestaudio[ext=m4a]/bestaudio[acodec!=none]/best",
                        "postprocessors": (
                            [
                                {
                                    "key": "FFmpegExtractAudio",
                                    "preferredcodec": "mp3",
                                    "preferredquality": MP3_KBPS,
                                },
                                {"key": "FFmpegMetadata", "add_metadata": True},
                            ]
                            if ffmpeg_path()
                            else []
                        ),
                    }
                )
            try:
                if on_progress:
                    on_progress(0.02, f"resolving ({name})")
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([track.url or track.watch_url])
                produced = sorted(
                    (p for p in work.glob("track.*") if p.is_file() and p.stat().st_size > 0),
                    key=lambda p: p.stat().st_size,
                    reverse=True,
                )
                if not produced:
                    raise DownloadError("no file was produced")
                source = produced[0]
                if source.stat().st_size > self.settings.max_download_mb * 1024 * 1024:
                    raise DownloadError("that file is larger than the allowed size")
                target = final if source.suffix == final.suffix else final.with_suffix(source.suffix)
                _atomic_move(source, target)
                return target
            except Exception as exc:
                message = str(exc)
                # Two identical sentences mean the *server* is the problem, not
                # the player client: another two attempts only cost 32 more
                # seconds before the same answer.
                same_error = same_error + 1 if last_error is not None and str(last_error) == message else 1
                last_error = exc
                logger.info("download via %s failed for %s: %s", name, track.id, exc)
                self._note_wall(message)
                if same_error >= 2:
                    logger.info(
                        "download for %s is deterministic, stopping the client ladder", track.id
                    )
                    break
            finally:
                shutil.rmtree(work, ignore_errors=True)

        raise DownloadError(
            f"yt-dlp could not download this track ({type(last_error).__name__}: {last_error})"
            if last_error
            else "yt-dlp could not download this track"
        )

    # ── direct-URL engine (Invidious / Piped + ffmpeg) ─────────────────────
    async def _download_direct(
        self,
        track: Track,
        *,
        video: bool,
        on_progress: ProgressHook | None = None,
    ) -> Path:
        from vyron.core.public_streams import get_public_streams

        if not getattr(self.settings, "stream_fallback", True):
            raise DownloadError("no fallback resolver is enabled")
        height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
            self.settings.video_quality, 720
        )
        direct = await get_public_streams(self.settings).resolve(
            track.id, height=height if video else 0
        )
        if not direct:
            raise DownloadError("no mirror had a downloadable URL")

        if on_progress:
            on_progress(0.1, f"downloading from {direct.source.split(':')[0]}")
        final = (self.video_path(track) if video else self.audio_path(track)).with_suffix(
            "." + (direct.ext or ("mp4" if video else "m4a"))
        )
        work = self.settings.downloads_dir / f".direct-{track.id}"
        work.mkdir(parents=True, exist_ok=True)
        raw = work / f"source.{direct.ext or 'm4a'}"
        try:
            await self._fetch_to(direct.url, raw, direct.headers, on_progress)
            if raw.stat().st_size == 0:
                raise DownloadError("the mirror sent an empty file")
            if raw.stat().st_size > self.settings.max_download_mb * 1024 * 1024:
                raise DownloadError("that file is larger than the allowed size")

            binary = ffmpeg_path()
            if not binary or raw.suffix == final.suffix:
                return _atomic_move(raw, final)

            if on_progress:
                on_progress(0.85, "converting with ffmpeg")
            args = (
                [binary, "-y", "-loglevel", "error", "-i", str(raw), "-vn", "-c:a", "libmp3lame",
                 "-b:a", f"{MP3_KBPS}k", str(final)]
                if not video
                else [binary, "-y", "-loglevel", "error", "-i", str(raw), "-c", "copy",
                      "-movflags", "+faststart", str(final)]
            )
            result = await asyncio.to_thread(
                subprocess.run, args, capture_output=True, timeout=900
            )
            if result.returncode != 0 or not final.is_file() or final.stat().st_size == 0:
                logger.info("ffmpeg fallback failed: %s", (result.stderr or b"")[:400])
                return _atomic_move(raw, final.with_suffix(raw.suffix))
            return final
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ── video from a substitute (the walled-IP answer) ─────────────────────
    async def _artwork(self, track: Track) -> bytes | None:
        """The cover bytes for *track*, or ``None`` when there is no picture."""
        url = str(getattr(track, "thumbnail", "") or "").strip()
        if not url.startswith("http"):
            return None
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return None
                    return await response.read()
        except Exception as exc:  # pragma: no cover - network
            logger.info("artwork fetch failed for %s: %s", track.id, exc)
            return None

    async def _video_from_substitute(
        self, track: Track, *, on_progress: ProgressHook | None = None
    ) -> Path:
        """An MP4 of the same song when YouTube will not hand over its video.

        A walled IP has no video to give. Rather than fail the request, take the
        song from a catalogue that serves audio and build a real 720p MP4 around
        it: the poster as the picture, the audio as the sound. It is the file
        people actually wanted — something that plays, everywhere.
        """
        from vyron.core import alternate

        binary = ffmpeg_path()
        if not binary:
            raise DownloadError("ffmpeg is not installed, so a video cannot be built")

        if on_progress:
            on_progress(0.05, "finding the same song")
        found = await alternate.find(track, settings=self.settings)
        if found is None or not found.url:
            raise DownloadError("no catalogue carries this song")

        audio = await self._download_stream(found)
        frame = await self._video_frame(track)
        if frame is None:
            raise DownloadError("no artwork to build the picture from")

        if on_progress:
            on_progress(0.55, "building the video")
        final = self.video_path(track).with_suffix(".mp4")
        work = self.settings.downloads_dir / f".video-{track.id}"
        work.mkdir(parents=True, exist_ok=True)
        frame_path = work / "frame.jpg"
        frame_path.write_bytes(frame)
        args = [
            binary, "-y", "-loglevel", "error",
            # A still picture held for the length of the song: one frame in,
            # 2 fps out, which keeps the encode fast without a judder.
            "-loop", "1", "-framerate", "2", "-i", str(frame_path),
            "-i", str(audio),
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,"
            "pad=1280:720:(ow-iw)/2:(oh-ih)/2,format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
            "-r", "2", "-c:a", "aac", "-b:a", f"{VIDEO_AUDIO_KBPS}k",
            "-shortest", "-movflags", "+faststart", str(final),
        ]
        try:
            result = await asyncio.to_thread(
                subprocess.run, args, capture_output=True, timeout=1800
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if result.returncode != 0 or not final.is_file() or final.stat().st_size == 0:
            raise DownloadError(
                f"ffmpeg could not build the video ({(result.stderr or b'')[:160]})"
            )
        logger.info(
            "built a %s video for %r from %s", self.settings.video_quality, track.title, found.source
        )
        return final

    async def _video_frame(self, track: Track) -> bytes | None:
        """A 1280×720 still: the rendered poster, or the raw cover art."""
        art = await self._artwork(track)
        from vyron.utils import thumbnails

        if thumbnails.PIL_AVAILABLE:
            try:
                from vyron.core.queue import ChatState

                frame = await asyncio.to_thread(
                    thumbnails.render, ChatState(chat_id=0, current=track), track, art
                )
                if frame:
                    return frame
            except Exception as exc:  # pragma: no cover - render paths
                logger.info("poster render failed for %s: %s", track.id, exc)
        return art

    async def _fetch_to(
        self,
        url: str,
        target: Path,
        headers: dict[str, str],
        on_progress: ProgressHook | None,
    ) -> None:
        """Fetch *url* into *target* with aria2 → curl → aiohttp.

        A signed media URL is a plain HTTP file, so the accelerator that wins is
        simply the fastest one installed: aria2 pulls it over 16 connections,
        curl over one ranged transfer, and the pure-Python client covers images
        that have neither binary.
        """
        from vyron.core import accelerator

        cap = self.settings.max_download_mb * 1024 * 1024

        def progress(written: int, total: int) -> None:
            if on_progress and total:
                on_progress(min(0.8, 0.1 + 0.7 * written / total), "downloading")

        try:
            await accelerator.fetch(
                url,
                target,
                headers=headers or {},
                timeout=900,
                cap=cap,
                on_progress=progress,
                order=self.accelerator_order(),
            )
        except Exception as exc:
            raise DownloadError(f"could not fetch the file ({exc})") from exc

    # ── public API ─────────────────────────────────────────────────────────
    async def fetch(
        self,
        track: Track,
        *,
        video: bool = False,
        on_progress: ProgressHook | None = None,
    ) -> Path:
        """Cached file → yt-dlp ladder → direct-URL mirror. Always a real file."""
        cached = self.cached(track, video=video)
        if cached:
            if on_progress:
                on_progress(1.0, "cached")
            return cached

        async with self._lock(f"{track.id}:{'v' if video else 'a'}"):
            cached = self.cached(track, video=video)
            if cached:
                return cached
            from vyron.core.sources import DIRECT_SOURCES

            if track.source in DIRECT_SOURCES and track.url:
                # A direct stream: no extraction, no ladder — just the
                # accelerator writing bytes into the cache.
                return await self._download_stream(track, on_progress=on_progress)
            errors: list[str] = []
            if self._youtube_walled():
                errors.append("yt-dlp: skipped — YouTube is refusing this server")
                logger.info(
                    "skipping the yt-dlp ladder for %s — YouTube is walled, using a mirror",
                    track.id,
                )
            else:
                try:
                    return await asyncio.to_thread(
                        self._download_ytdlp, track, video=video, on_progress=on_progress
                    )
                except Exception as exc:
                    errors.append(f"yt-dlp: {exc}")
                    logger.warning("yt-dlp download failed for %s: %s", track.id, exc)
            try:
                return await self._download_direct(
                    track, video=video, on_progress=on_progress
                )
            except Exception as exc:
                errors.append(f"mirror: {exc}")
                logger.warning("direct download failed for %s: %s", track.id, exc)
            # The same song from a catalogue that serves its own audio (JioSaavn,
            # Audius…). A listener who asked for "Kesariya" wants the song, not
            # the exact upload — and a 403 from YouTube is not their problem.
            if not video:
                try:
                    from vyron.core import alternate

                    found = await alternate.find(track, settings=self.settings)
                    if found is not None:
                        logger.info(
                            "downloading %r from %s instead (%s)", track.title, found.source, found.id
                        )
                        return await self._download_stream(found, on_progress=on_progress)
                except Exception as exc:
                    errors.append(f"substitute: {exc}")
                    logger.warning("substitution download failed for %s: %s", track.id, exc)
            else:
                # A video request has a third engine the audio path does not
                # need: the same song, wrapped in its own artwork.
                try:
                    return await self._video_from_substitute(track, on_progress=on_progress)
                except Exception as exc:
                    errors.append(f"video: {exc}")
                    logger.warning("video fallback failed for %s: %s", track.id, exc)
            raise DownloadError(" · ".join(errors))

    async def _download_stream(
        self, track: Track, *, on_progress: ProgressHook | None = None
    ) -> Path:
        """Fetch a track whose `url` *is* the audio (Audius, direct files)."""
        from vyron.core import accelerator

        target = self.settings.downloads_dir / f"{track.source}-{track.id}.mp3"
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")

        def _progress(done: int, total: int) -> None:
            if on_progress and total:
                on_progress(min(1.0, done / total), "download")

        try:
            await accelerator.fetch(
                track.url,
                partial,
                cap=self.settings.max_download_mb * 1024 * 1024,
                on_progress=_progress,
                order=self.accelerator_order(),
            )
            partial.replace(target)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise DownloadError(f"could not fetch the stream ({exc})") from exc
        if on_progress:
            on_progress(1.0, "done")
        return target

    async def audio(
        self,
        track: Track,
        *,
        progress: Callable[[str], None] | None = None,
        on_progress: ProgressHook | None = None,
    ) -> Path:
        callback = on_progress
        if progress and not callback:
            callback = lambda _fraction, text: progress(text)  # noqa: E731
        return await self.fetch(track, video=False, on_progress=callback)

    async def video(
        self,
        track: Track,
        *,
        progress: Callable[[str], None] | None = None,
        on_progress: ProgressHook | None = None,
    ) -> Path:
        callback = on_progress
        if progress and not callback:
            callback = lambda _fraction, text: progress(text)  # noqa: E731
        return await self.fetch(track, video=True, on_progress=callback)

    # ── maintenance ────────────────────────────────────────────────────────
    def clear(self) -> int:
        """Delete every cached download (used by `/clearcache`)."""
        removed = 0
        for path in self.settings.downloads_dir.iterdir():
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
                else:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def cleanup(self) -> int:
        """Delete cache entries older than DOWNLOAD_CACHE_HOURS."""
        cutoff = time.time() - self.settings.download_cache_hours * 3600
        removed = 0
        for path in self.settings.downloads_dir.glob("*"):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
                elif path.is_dir() and path.name.startswith((".work-", ".direct-")):
                    shutil.rmtree(path, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def cache_size(self) -> int:
        total = 0
        for path in self.settings.downloads_dir.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total


__all__ = ["DownloadError", "Downloader", "ffmpeg_path", "safe_stem"]
