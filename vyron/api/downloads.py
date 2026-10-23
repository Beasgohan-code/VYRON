# ---------------------------------------------------------------------------
#  VYRON API — asynchronous download endpoints
# ---------------------------------------------------------------------------
#   POST   /v1/downloads                submit a job      → 202 {job}
#   GET    /v1/downloads                recent jobs for this key
#   GET    /v1/downloads/{job_id}       poll one job
#   GET    /v1/downloads/{job_id}/file  the finished file (Range friendly)
#   DELETE /v1/downloads/{job_id}       cancel a queued/running job
#
# The synchronous `POST /v1/tracks` stays the one-shot path; this is the one a
# client uses when it wants a progress bar, and the one the Mini App's download
# sheet calls. Both share `runtime.downloader`, so a file fetched either way is
# cached once.
from __future__ import annotations

import logging
from urllib.parse import quote
from aiohttp import web

from vyron.api.errors import ApiError
from vyron.api.metrics import METRICS
from vyron.api.routes import base_url, payload, video_id_from
from vyron.api.security import headers_for
from vyron.core.downloadjobs import get_download_jobs
from vyron.core.musicapi import get_music_api
from vyron.runtime import runtime

logger = logging.getLogger(__name__)

MIME_BY_EXT = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "opus": "audio/ogg",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
    "mp4": "video/mp4",
    "mkv": "video/x-matroska",
}


def _owner(auth) -> str:
    """Identity for job ownership: the key prefix, or the auth mode."""
    if auth.record:
        return str(auth.record.get("prefix") or auth.record.get("id") or "key")
    if auth.owner:
        return "owner"
    return "open"


def _is_admin(auth) -> bool:
    return bool(auth.owner or "admin" in (auth.scopes or ()))


def _disposition(title: str, video_id: str, ext: str, *, inline: bool = False) -> str:
    """Latin-1-safe Content-Disposition with the RFC 5987 form for Unicode."""
    safe = (
        f"{title[:60]} [{video_id}]"
        .replace("/", "-")
        .replace('"', "")
        .replace("\\", "-")
        .replace("\n", " ")
        .replace("\r", " ")
    )
    ascii_name = safe.encode("ascii", "ignore").decode().strip() or str(video_id)
    encoded = quote(f"{safe}.{ext}", safe="")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_name}.{ext}\"; filename*=UTF-8''{encoded}"


def _ensure_ready() -> None:
    if runtime.youtube is None or runtime.downloader is None:
        raise ApiError("not_ready")


async def _resolve_track(data: dict):
    """A query, a URL or a bare id — one Track, or a clean error."""
    raw = str(data.get("video_id") or data.get("id") or data.get("url") or "").strip()
    query = str(data.get("query") or data.get("q") or "").strip()
    try:
        if raw:
            video_id = video_id_from({"video_id": raw})
            return await runtime.youtube.resolve(f"https://www.youtube.com/watch?v={video_id}")
        if query:
            results = await runtime.youtube.search(query, limit=1)
            if not results:
                raise ApiError("upstream_failed", f"nothing found for “{query[:60]}”")
            return results[0]
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError("upstream_failed", str(exc)) from exc
    raise ApiError("bad_request", "send video_id, url or query")


# ── endpoints ──────────────────────────────────────────────────────────────
async def submit(request: web.Request) -> web.StreamResponse:
    auth = await _authorize(request)
    _ensure_ready()
    data = await payload(request)
    kind = str(data.get("format") or data.get("kind") or "audio").strip().lower()
    if kind in {"mp3", "m4a", "music", "song"}:
        kind = "audio"
    if kind in {"mp4", "video", "vid"}:
        kind = "video"
    if kind not in {"audio", "video"}:
        raise ApiError("bad_request", "format must be audio or video")

    track = await _resolve_track(data)
    job = get_download_jobs().submit(track, kind=kind, owner=_owner(auth))
    body = job.to_json(base_url(request))
    body["ok"] = True
    body["poll"] = f"{base_url(request)}/downloads/{job.id}"
    return web.json_response(body, status=202, headers=headers_for(auth))


async def _authorize(request: web.Request):
    from vyron.api.security import authorize

    return await authorize(request, "download")


async def listing(request: web.Request) -> web.StreamResponse:
    auth = await _authorize(request)
    jobs = get_download_jobs()
    owner = None if _is_admin(auth) else _owner(auth)
    items = [job.to_json(base_url(request)) for job in jobs.list(owner=owner, limit=25)]
    return web.json_response(
        {"ok": True, "count": len(items), "jobs": items, "stats": jobs.snapshot()},
        headers=headers_for(auth),
    )


def _owned_job(request: web.Request, auth):
    jobs = get_download_jobs()
    job = jobs.get(request.match_info.get("job_id", ""))
    if job is None:
        raise ApiError("not_found", "no such download job — jobs are forgotten after a restart")
    if not jobs.can_access(job, _owner(auth), admin=_is_admin(auth)):
        # 404, not 403: another key's job id must not be confirmed to exist.
        raise ApiError("not_found", "no such download job")
    return job


async def status(request: web.Request) -> web.StreamResponse:
    auth = await _authorize(request)
    job = _owned_job(request, auth)
    body = job.to_json(base_url(request))
    body["ok"] = True
    return web.json_response(body, headers=headers_for(auth))


async def cancel(request: web.Request) -> web.StreamResponse:
    auth = await _authorize(request)
    job = _owned_job(request, auth)
    await get_download_jobs().cancel(job.id)
    body = job.to_json(base_url(request))
    body["ok"] = True
    return web.json_response(body, status=202, headers=headers_for(auth))


async def file(request: web.Request) -> web.StreamResponse:
    auth = await _authorize(request)
    job = _owned_job(request, auth)
    if job.status != "ready" or not job.ready:
        raise ApiError(
            "bad_request",
            f"the file is not ready yet (status: {job.status})",
            status=409,
            hint="poll the job url until status is ready",
        )

    path = job.path
    ext = job.extension
    size = job.size or 0
    await get_music_api().note_use(auth.record, size=size)
    METRICS.note_download(size)

    download = request.query.get("download") in {"1", "true", "yes"}
    disposition = _disposition(job.title or job.video_id, job.video_id, ext, inline=not download)
    headers = {
        **headers_for(auth),
        "Content-Disposition": disposition,
        "Content-Type": MIME_BY_EXT.get(ext, "application/octet-stream"),
        "X-Job-Id": job.id,
        "X-Track-Id": job.video_id,
        "X-Track-Size": str(size),
        "Access-Control-Expose-Headers": "X-Job-Id, X-Track-Id, X-Track-Size, Content-Disposition",
    }
    # FileResponse handles Range requests, which is what makes a resumable
    # download and an <audio> tag seek work.
    return web.FileResponse(path, headers=headers)


async def by_url(request: web.Request) -> web.StreamResponse:
    """`GET /v1/downloads/by-video-id/{id}` — one call, no JSON body."""
    auth = await _authorize(request)
    _ensure_ready()
    video_id = request.match_info.get("video_id", "")
    track = await _resolve_target(video_id)
    job = get_download_jobs().submit(
        track, kind="video" if request.query.get("format") == "video" else "audio",
        owner=_owner(auth),
    )
    body = job.to_json(base_url(request))
    body["ok"] = True
    return web.json_response(body, status=202, headers=headers_for(auth))


async def _resolve_target(video_id: str):
    try:
        clean = video_id_from({"video_id": video_id})
        return await runtime.youtube.resolve(f"https://www.youtube.com/watch?v={clean}")
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError("upstream_failed", str(exc)) from exc


__all__ = ["by_url", "cancel", "file", "listing", "status", "submit"]
