# ---------------------------------------------------------------------------
#  VYRON — /sources
#
#  "Why won't this song play?" has exactly three honest answers: the video is
#  gone, YouTube does not like this server's IP, or a mirror is down. /doctor
#  says whether the deployment is configured; /sources says which *tier*
#  actually produced a URL in the last few seconds — measured, not guessed.
#
#    · every yt-dlp player client we ship, tried in ladder order
#    · every Invidious, Piped and Cobalt host that is configured
#    · the scoreboard (wins / failures / cooldown) from live traffic
#
#  Owner only: it makes outbound requests and prints infrastructure detail.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

from pyrogram import Client
from pyrogram.types import Message

from vyron.config import settings
from vyron.core.resolvers import HEALTH
from vyron.runtime import runtime
from vyron.ui import blocks as B, cards
from vyron.ui import rich
from vyron.ui.theme import BULLET, E
from vyron.utils.helpers import is_owner
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

DEFAULT_VIDEO = "dQw4w9WgXcQ"
PROBE_TIMEOUT = 14


def _fmt_ms(ms: float) -> str:
    return f"{int(ms)} ms" if ms else "—"


def _verdict(rows: list[tuple[str, str]]) -> str:
    ok = sum(1 for _, value in rows if "<b>ok</b>" in value)
    if not ok:
        return (
            f"{E('warn')} <b>No tier answered.</b> That is the IP, not the track: "
            "install <code>curl_cffi</code> (browser impersonation), point "
            "<code>COBALT_URL</code> at a self-hosted Cobalt, or try a proxy."
        )
    if ok == 1:
        return f"{E('check')} One tier works — playback will use it, the rest are skipped."
    return f"{E('check')} <b>{ok} tiers answered.</b> Playback picks the fastest healthy one."


async def _probe_ytdlp(video_id: str) -> list[tuple[str, str]]:
    """Try every player client, one at a time, and report each."""
    youtube = runtime.youtube
    if youtube is None:
        return [("yt-dlp", "<b>fail</b> · resolver not started")]

    rows: list[tuple[str, str]] = []
    target = f"https://www.youtube.com/watch?v={video_id}"
    for client in ["default", "tv_simply", "web_embedded", "android_vr", "ios", "tv", "web_safari", "mweb"]:
        started = time.perf_counter()
        try:
            info = await asyncio.wait_for(
                youtube._async_extract(  # noqa: SLF001 - the ladder is the point here
                    target,
                    format="bestaudio[ext=m4a]/bestaudio[acodec!=none]/best",
                    **youtube._client_opts(None if client == "default" else client),  # noqa: SLF001
                ),
                timeout=PROBE_TIMEOUT,
            )
            took = (time.perf_counter() - started) * 1000
            url = str(info.get("url") or "") if isinstance(info, dict) else ""
            if url:
                rows.append((f"yt-dlp · {client}", f"<b>ok</b> · {_fmt_ms(took)}"))
            else:
                rows.append((f"yt-dlp · {client}", "<b>fail</b> · no direct url"))
        except asyncio.TimeoutError:
            rows.append((f"yt-dlp · {client}", f"<b>fail</b> · no answer in {PROBE_TIMEOUT}s"))
        except Exception as exc:
            rows.append((f"yt-dlp · {client}", f"<b>fail</b> · {rich.esc(str(exc)[:60])}"))
    return rows


async def _probe_mirrors(video_id: str) -> list[tuple[str, str]]:
    from vyron.core.public_streams import get_public_streams

    streams = get_public_streams(settings)
    try:
        results = await asyncio.wait_for(streams.probe(video_id), timeout=PROBE_TIMEOUT + 8)
    except Exception as exc:  # pragma: no cover - a probe must not crash a command
        return [("mirrors", f"<b>fail</b> · {rich.esc(str(exc)[:60])}")]
    if not results:
        return [("mirrors", "<b>off</b> · STREAM_FALLBACK=off or no hosts configured")]
    rows: list[tuple[str, str]] = []
    for item in sorted(results, key=lambda entry: (not entry["ok"], entry["ms"])):
        label = item["source"].replace(":", " · ")
        if item["ok"]:
            rows.append((label, f"<b>ok</b> · {_fmt_ms(item['ms'])} · {rich.esc(item.get('detail') or '')}"))
        else:
            rows.append((label, f"<b>fail</b> · {_fmt_ms(item['ms'])} · {rich.esc(item.get('error') or '')}"))
    return rows


def _scoreboard_rows(limit: int = 6) -> list[tuple[str, str]]:
    stats = HEALTH.stats()
    rows: list[tuple[str, str]] = []
    for name, stat in sorted(stats.items(), key=lambda item: -item[1]["wins"])[:limit]:
        if not stat["tries"]:
            continue
        state = f"<b>ok</b> · {stat['wins']}/{stat['tries']} · {_fmt_ms(stat['latency_ms'])}"
        if stat["cooling"]:
            state = f"<b>warn</b> · cooling {int(stat['cooling'])}s"
        rows.append((name.replace(":", " · "), state))
    return rows


def _env_rows() -> list[tuple[str, str]]:
    impersonate = "on" if settings.impersonate not in {"", "off", "none", "0"} else "off"
    try:
        import curl_cffi  # noqa: F401

        impersonate += " · curl_cffi present"
    except Exception:
        impersonate += " · curl_cffi missing"
    from vyron.core.public_streams import COBALT_HOSTS, INVIDIOUS_HOSTS, PIPED_HOSTS

    cobalt = settings.cobalt_urls or ("off" if settings.disable_cobalt else f"{len(COBALT_HOSTS)} public")
    from vyron.core import accelerator

    return [
        (f"{E('shield')} impersonation", f"<b>{impersonate}</b>"),
        (f"{E('download')} fallback tier", "on" if settings.stream_fallback else "off"),
        (f"{E('bolt')} download tier", f"<b>{accelerator.describe()}</b>"),
        (f"{E('cloud')} hosts", f"{len(INVIDIOUS_HOSTS)} invidious · {len(PIPED_HOSTS)} piped · {cobalt} cobalt"),
        (f"{E('key')} cookies", "set" if (settings.cookies_file or settings.cookies_text) else "not set (fine)"),
    ]


def register(client: Client) -> None:
    @client.on_message(cmd(["sources"]))
    async def _sources(_: Client, message: Message) -> None:
        user = message.from_user
        if not (user and is_owner(user.id)):
            await rich.send(
                client,
                message.chat.id,
                cards.locked_card("/sources probes this server's resolvers — owner only."),
                reply_to=message.id,
            )
            return

        parts = (message.text or "").split(maxsplit=1)
        video_id = (parts[1].strip() if len(parts) > 1 else "") or DEFAULT_VIDEO
        if len(video_id) != 11 or not all(c.isalnum() or c in "-_" for c in video_id):
            video_id = DEFAULT_VIDEO

        status = await rich.send(
            client,
            message.chat.id,
            B.head("probing every resolver", glyph="clock")
            + B.context(
                "One video, every tier, same second — this is what this server "
                "can actually reach."
            ),
            reply_to=message.id,
        )

        started = time.perf_counter()
        ytdlp, mirrors = await asyncio.gather(
            _probe_ytdlp(video_id), _probe_mirrors(video_id)
        )
        took = (time.perf_counter() - started)

        rows = ytdlp + mirrors
        head = B.banner(f"resolvers {BULLET} <code>{rich.esc(video_id)}</code>", glyph="download")
        body = (
            B.table(["source", "result"], rows)
            + B.divider()
            + B.banner("scored from live traffic", glyph="bolt")
            + B.table(["source", "wins"], _scoreboard_rows() or [("—", "no traffic yet")])
            + B.divider()
            + B.banner("configuration", glyph="settings")
            + B.kv(_env_rows())
            + B.note(_verdict(rows))
            + B.footer(f"probe took {took:.1f}s · /doctor for the deployment check")
        )
        markup = head + body
        if status:
            await rich.edit(client, message.chat.id, status.id, markup)
        else:
            await rich.send(client, message.chat.id, markup, reply_to=message.id)


__all__ = ["register"]
