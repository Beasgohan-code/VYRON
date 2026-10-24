# ---------------------------------------------------------------------------
#  VYRON — /doctor
#
#  One command that answers "why will nothing play?" on a fresh deployment.
#  Every row is a check that was actually run, not a guess:
#
#    · config       required variables present (secrets masked)
#    · yt-dlp       installed, and which version
#    · cookies      a cookie file exists (the usual Render/YouTube fix)
#    · ffmpeg       conversion available (mp3/mp4 instead of raw m4a)
#    · mirror tier  Invidious/Piped fallbacks that rescue a failed resolve
#    · search       a live resolve against YouTube
#    · voice engine assistant session + PyTgCalls
#    · storage      mongo / local, and whether it answers
#    · web app      bundle mounted and where
#    · music API    mounted and in which auth mode
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron import __build__, __version__
from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.theme import E
from vyron.utils.helpers import is_owner

logger = logging.getLogger(__name__)

PROBE_VIDEO = "dQw4w9WgXcQ"  # a video that has been public for 15 years


def _row(label: str, ok: bool | None, value: str) -> tuple[str, str]:
    mark = "ok" if ok else ("warn" if ok is None else "fail")
    return (f"{label}", f"<b>{mark}</b> · {value}")


async def _probe_search() -> tuple[bool, str]:
    youtube = runtime.youtube
    if youtube is None:
        return False, "resolver not started"
    started = time.perf_counter()
    try:
        track = await asyncio.wait_for(
            youtube.resolve(f"https://youtu.be/{PROBE_VIDEO}"), timeout=20
        )
    except asyncio.TimeoutError:
        return False, "no answer in 20s — this server cannot reach YouTube"
    except Exception as exc:
        from vyron.core.search import explain

        message = str(exc)
        meaning, _fix = explain(message)
        if meaning:
            # "YouTube thinks this server is a bot" beats a stack-trace excerpt
            return False, f"<b>{rich.esc(meaning)}</b> · /sources for the tier that works"
        return False, f"{type(exc).__name__}: {rich.esc(message[:80])}"
    took = (time.perf_counter() - started) * 1000
    return True, f"{int(took)} ms · {rich.esc(str(getattr(track, 'title', '') or '')[:40])}"


async def _probe_storage() -> tuple[bool | None, str]:
    storage = runtime.storage
    if storage is None:
        return False, "not configured"
    backend = getattr(storage, "backend", "unknown")
    try:
        await asyncio.wait_for(storage.counters(), timeout=8)
    except Exception as exc:
        return False, f"{backend} · {type(exc).__name__}"
    return True, backend


def _cookies_state() -> tuple[bool | None, str]:
    from pathlib import Path

    configured = settings.cookies_file or settings.cookies_text
    if not configured:
        return None, "none (YouTube may bot-check this IP)"
    if settings.cookies_file and Path(settings.cookies_file).is_file():
        size = Path(settings.cookies_file).stat().st_size
        return True, f"file · {size} bytes"
    if settings.cookies_text:
        return True, "from env (written at boot)"
    return False, "set but missing on disk"


def _impersonate_row() -> tuple[str, str]:
    """Browser impersonation — the no-cookie fix for a datacenter IP."""
    requested = (settings.impersonate or "").strip()
    if requested.lower() in {"", "off", "none", "0", "false"}:
        return _row(f"{E('shield')} impersonation", None, "IMPERSONATE=off")
    try:
        import curl_cffi  # noqa: F401
    except Exception:
        return _row(
            f"{E('shield')} impersonation",
            False,
            "on but curl_cffi is missing — pip install curl_cffi (best no-cookie fix)",
        )
    return _row(f"{E('shield')} impersonation", True, f"{requested or 'chrome'} · curl_cffi ready")


def _resolver_row() -> tuple[str, str] | None:
    from vyron.core.resolvers import HEALTH

    summary = HEALTH.summary()
    best = summary.get("best")
    if not best:
        return None
    return _row(
        f"{E('bolt')} best resolver",
        True,
        f"{rich.esc(best['source'])} · {int(best['latency_ms'])} ms · /sources for the full sweep",
    )


def _disk_state() -> tuple[bool, str]:
    """Can the bot actually write a downloaded track?"""
    target = settings.downloads_dir
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".doctor"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        return False, f"{target} · {type(exc).__name__}"
    free_mb = 0
    try:
        import shutil

        free_mb = int(shutil.disk_usage(target).free / (1024 * 1024))
    except Exception:  # pragma: no cover - exotic filesystems
        pass
    return True, f"{free_mb} MB free" if free_mb else str(target)


def _engine_state() -> tuple[bool, str]:
    if runtime.calls is None:
        reason = "STRING_SESSION missing" if not settings.session_string else "session failed to start"
        return False, reason
    return True, "PyTgCalls ready"


def register(client: Client) -> None:
    @client.on_message(filters.command(["doctor"]))
    async def _doctor(_: Client, message: Message) -> None:
        user = message.from_user
        if not (user and is_owner(user.id)):
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('shield')} /doctor prints deployment internals — owner only."),
                reply_to=message.id,
            )
            return

        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} <b>Running checks…</b>",
            reply_to=message.id,
        )

        problems = settings.validate()
        rows: list[tuple[str, str]] = [
            _row(
                f"{E('rocket')} build",
                True,
                f"v{__version__} · {__build__}",
            ),
            _row(
                f"{E('key')} config",
                not problems,
                "all required variables set" if not problems else "; ".join(problems)[:90],
            )
        ]

        try:
            import yt_dlp

            from vyron.core import ytdlp_update

            version = yt_dlp.version.__version__
            update = ytdlp_update.status()
            note = f"v{version}"
            if update["latest"]:
                if ytdlp_update.is_newer(update["latest"], version):
                    note += f" · {update['latest']} available"
                else:
                    note += " · current"
            elif update["error"]:
                note += " · version check failed"
            rows.append(_row(f"{E('download')} yt-dlp", True, note))
        except Exception as exc:  # pragma: no cover - packaging problem
            rows.append(_row(f"{E('download')} yt-dlp", False, str(exc)[:60]))

        cookies_ok, cookies_note = _cookies_state()
        rows.append(_row(f"{E('code')} cookies", cookies_ok, cookies_note))

        from vyron.core.downloader import ffmpeg_path

        rows.append(
            _row(
                f"{E('bolt')} ffmpeg",
                bool(ffmpeg_path()),
                ffmpeg_path() or "missing — mp3 conversion is off, m4a is used instead",
            )
        )

        if settings.stream_fallback:
            from vyron.core.public_streams import PublicStreams

            streams = PublicStreams(settings)
            hosts = list(streams.invidious) + list(streams.piped)
            cobalt = len(streams.cobalt)
            rows.append(
                _row(
                    f"{E('download')} mirror tier",
                    True,
                    f"{len(hosts)} hosts · cobalt {cobalt} · {hosts[0] if hosts else 'none'}",
                )
            )
        else:
            rows.append(_row(f"{E('download')} mirror tier", None, "STREAM_FALLBACK=off (yt-dlp only)"))

        rows.append(_impersonate_row())
        resolver_row = _resolver_row()
        if resolver_row:
            rows.append(resolver_row)

        search_ok, search_note = await _probe_search()
        rows.append(_row(f"{E('search')} youtube", search_ok, search_note))

        engine_ok, engine_note = _engine_state()
        rows.append(_row(f"{E('live')} voice engine", engine_ok, engine_note))

        storage_ok, storage_note = await _probe_storage()
        rows.append(_row(f"{E('cloud')} storage", storage_ok, storage_note))

        from vyron.web.server import WEB_DIR

        rows.append(
            _row(
                f"{E('interface')} web app",
                (WEB_DIR / "index.html").is_file(),
                str(WEB_DIR),
            )
        )
        rows.append(
            _row(
                f"{E('api')} music api",
                settings.music_api,
                "open" if settings.music_api_open else "keyed",
            )
        )
        rows.append(
            _row(
                f"{E('download')} download api",
                settings.vyron_api,
                "/vyron/v1 · 2 at a time" if settings.vyron_api else "VYRON_API=off",
            )
        )
        disk_ok, disk_note = _disk_state()
        rows.append(_row(f"{E('cloud')} download dir", disk_ok, disk_note))
        rows.append(
            _row(
                f"{E('play')} playback",
                True,
                "download → local file" if settings.play_from_disk else "stream URLs",
            )
        )

        failures = sum(1 for _, value in rows if "<b>fail</b>" in value)
        head = B.heading(f"{E('shield')} doctor · v{__version__}", 2)
        body = B.table(["check", "result"], rows)
        tail = B.note(
            f"{E('check')} Everything that matters is answering."
            if not failures
            else f"{E('warn')} {failures} check(s) failed — the reason is in the row above."
        )
        markup = head + body + tail
        if status:
            await rich.edit(client, message.chat.id, status.id, markup)
        else:
            await rich.send(client, message.chat.id, markup, reply_to=message.id)


__all__ = ["register"]
