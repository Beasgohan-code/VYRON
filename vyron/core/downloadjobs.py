# ---------------------------------------------------------------------------
#  VYRON — download jobs (the engine behind /v1/downloads)
# ---------------------------------------------------------------------------
# `POST /v1/tracks` answers with the file itself, which is what a script wants
# but a phone on a slow uplink cannot use: the request blocks for a minute and
# any hiccup loses the work. The job API is the same download split in two —
# submit, then poll — so a client can show progress, resume polling after an
# app switch, and fetch the file once it exists.
#
# Jobs are deliberately in-memory: they describe work happening in *this*
# process, and the files themselves live in the shared download cache, so a
# restart leaves the cache intact and only forgets the receipts.
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vyron.core.queue import Track

logger = logging.getLogger(__name__)

MAX_JOBS = 200
JOB_TTL = 6 * 3600  # a finished job is kept for an hour of polling, then swept
SERVE_CONCURRENCY = 2


def _now() -> float:
    return time.time()


@dataclass
class DownloadJob:
    id: str
    kind: str  # "audio" | "video"
    video_id: str
    title: str = ""
    artist: str = ""
    status: str = "queued"  # queued · running · ready · failed · cancelled
    progress: float = 0.0
    message: str = "queued"
    size: int = 0
    path: str = ""
    error: str = ""
    owner: str = ""
    created: float = field(default_factory=_now)
    updated: float = field(default_factory=_now)

    @property
    def ready(self) -> bool:
        return self.status == "ready" and bool(self.path) and Path(self.path).is_file()

    @property
    def extension(self) -> str:
        return Path(self.path).suffix.lstrip(".") if self.path else ("mp4" if self.kind == "video" else "mp3")

    def to_json(self, base: str = "/v1") -> dict[str, Any]:
        """Public shape — no absolute paths, no owner identifiers."""
        payload: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "kind": self.kind,
            "video_id": self.video_id,
            "title": self.title,
            "artist": self.artist,
            "progress": round(self.progress, 3),
            "message": self.message,
            "size": self.size,
            "created_at": round(self.created, 3),
            "updated_at": round(self.updated, 3),
        }
        if self.status == "ready":
            payload["download_url"] = f"{base}/downloads/{self.id}/file"
            payload["format"] = self.extension
        if self.error:
            payload["error"] = self.error
        return payload


class DownloadJobs:
    """Submit, track and cancel downloads; keeps the last MAX_JOBS receipts."""

    def __init__(self) -> None:
        self._jobs: "OrderedDict[str, DownloadJob]" = OrderedDict()
        self._tasks: dict[str, asyncio.Task] = {}
        self._slots: asyncio.Semaphore | None = None

    # ── internals ──────────────────────────────────────────────────────────
    def _sem(self) -> asyncio.Semaphore:
        if self._slots is None:
            self._slots = asyncio.Semaphore(SERVE_CONCURRENCY)
        return self._slots

    def _remember(self, job: DownloadJob) -> None:
        self._jobs[job.id] = job
        while len(self._jobs) > MAX_JOBS:
            oldest_id, _ = self._jobs.popitem(last=False)
            self._tasks.pop(oldest_id, None)

    # ── public API ─────────────────────────────────────────────────────────
    def submit(self, track: Track, *, kind: str, owner: str = "") -> DownloadJob:
        job = DownloadJob(
            id="dl_" + secrets.token_hex(5),
            kind="video" if kind == "video" else "audio",
            video_id=str(track.id),
            title=track.title,
            artist=track.uploader,
            owner=owner,
        )
        self._remember(job)
        self._tasks[job.id] = asyncio.create_task(self._run(job, track))
        return job

    async def _run(self, job: DownloadJob, track: Track) -> None:
        from vyron.runtime import runtime

        job.status = "running"
        job.updated = _now()

        def report(fraction: float, message: str) -> None:
            job.progress = max(0.0, min(1.0, float(fraction)))
            job.message = message
            job.updated = _now()

        try:
            async with self._sem():
                downloader = runtime.downloader
                if downloader is None:
                    raise RuntimeError("the downloader is not ready")
                video = job.kind == "video"
                if hasattr(downloader, "fetch"):
                    path = await downloader.fetch(track, video=video, on_progress=report)
                else:  # older/patched downloaders only expose audio()/video()
                    path = await (downloader.video(track) if video else downloader.audio(track))
                    report(1.0, "ready")
            job.path = str(path)
            job.size = path.stat().st_size
            job.progress = 1.0
            job.status = "ready"
            job.message = "ready"
        except asyncio.CancelledError:  # pragma: no cover - cancellation path
            job.status = "cancelled"
            job.message = "cancelled"
            raise
        except Exception as exc:
            logger.warning("download job %s failed: %s", job.id, exc)
            job.status = "failed"
            job.error = str(exc)[:300]
            job.message = "failed"
        finally:
            job.updated = _now()
            self._tasks.pop(job.id, None)

    def get(self, job_id: str) -> DownloadJob | None:
        return self._jobs.get(job_id)

    def list(self, *, owner: str | None = None, limit: int = 20) -> list[DownloadJob]:
        jobs = [job for job in self._jobs.values() if owner is None or job.owner == owner]
        return jobs[-limit:][::-1]

    def can_access(self, job: DownloadJob, owner: str, *, admin: bool = False) -> bool:
        return admin or not job.owner or job.owner == owner

    async def cancel(self, job_id: str) -> DownloadJob | None:
        job = self._jobs.get(job_id)
        if job is None:
            return None
        task = self._tasks.get(job_id)
        if task and not task.done():
            task.cancel()
            job.status = "cancelled"
            job.message = "cancelled"
            job.updated = _now()
        return job

    def sweep(self) -> int:
        """Drop finished receipts after JOB_TTL; returns how many were removed."""
        cutoff = _now() - JOB_TTL
        stale = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status in {"ready", "failed", "cancelled"} and job.updated < cutoff
        ]
        for job_id in stale:
            self._jobs.pop(job_id, None)
        return len(stale)

    def snapshot(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for job in self._jobs.values():
            counts[job.status] = counts.get(job.status, 0) + 1
        return {"jobs": len(self._jobs), "by_status": counts}


_jobs: DownloadJobs | None = None


def get_download_jobs() -> DownloadJobs:
    global _jobs
    if _jobs is None:
        _jobs = DownloadJobs()
    return _jobs


def reset_download_jobs() -> None:
    global _jobs
    _jobs = None


__all__ = ["DownloadJob", "DownloadJobs", "get_download_jobs", "reset_download_jobs"]
