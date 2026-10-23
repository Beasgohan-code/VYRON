# ---------------------------------------------------------------------------
#  VYRON — diagnostics & access
#
#  /speedtest  — bot API round-trip, media CDN throughput, voice-chat health
#  /sudoers    — who can operate the bot (owner + SUDO_USERS)
#  /whoami     — quick card with your id, rights and current chat
#
#  Operational diagnostics for a self-hosted deployment.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import human_time, truncate
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import display_name, is_owner

logger = logging.getLogger(__name__)

_SPEED_URL = "https://speed.cloudflare.com/__down?bytes=2000000"
_SPEED_BYTES = 2_000_000


async def _api_latency(client: Client) -> float | None:
    started = time.perf_counter()
    try:
        await client.get_me()
        return (time.perf_counter() - started) * 1000
    except Exception:
        return None


async def _throughput() -> tuple[float, float] | None:
    """Return (megabits/s, seconds) for a small CDN download."""
    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            started = time.perf_counter()
            received = 0
            async with session.get(_SPEED_URL) as response:
                if response.status != 200:
                    return None
                async for chunk in response.content.iter_chunked(65536):
                    received += len(chunk)
                    if received >= _SPEED_BYTES:
                        break
            elapsed = max(0.001, time.perf_counter() - started)
            return (received * 8) / elapsed / 1_000_000, elapsed
    except Exception as exc:
        logger.debug("speedtest download failed: %s", exc)
        return None


def register(client: Client) -> None:
    # ── /speedtest ─────────────────────────────────────────────────────────
    @client.on_message(filters.command(["speedtest", "speed", "spt"]))
    async def _speedtest(_: Client, message: Message) -> None:
        started = time.perf_counter()
        status = await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('bolt')} speed test", 3) + B.note(f"{B.think()} Measuring…"),
            reply_to=message.id,
            editable=True,
        )
        if status is None:
            return

        latency, throughput = await asyncio.gather(_api_latency(client), _throughput())
        total = (time.perf_counter() - started) * 1000

        rows: list[tuple[str, str]] = []
        if latency is not None:
            grade = "excellent" if latency < 150 else "good" if latency < 400 else "slow"
            rows.append((f"{E('bolt')} api latency", f"<b>{latency:.0f} ms</b> · {grade}"))
            rows.append((f"{E('clock')} total round-trip", f"<b>{total:.0f} ms</b>"))
        else:
            rows.append((f"{E('warn')} api latency", "<b>unreachable</b>"))

        if throughput:
            mbits, seconds = throughput
            rows.append(
                (f"{E('download')} media cdn", f"<b>{mbits:.1f} Mb/s</b> · {seconds:.2f}s for 2 MB")
            )
        else:
            rows.append((f"{E('download')} media cdn", "<b>unavailable</b> (blocked or offline)"))

        rows.append(
            (
                f"{E('live')} voice chat",
                f"<b>{'streaming ready' if runtime.streaming_ready else 'file mode only'}</b>",
            )
        )
        rows.append((f"{E('stats')} uptime", f"<b>{human_time(runtime.uptime)}</b>"))
        if runtime.player:
            rows.append((f"{E('queue')} active chats", f"<b>{len(runtime.player.active_chats())}</b>"))

        await rich.edit(
            client,
            message.chat.id,
            status.id,
            B.heading(f"{E('bolt')} speed test", 3)
            + B.kv(rows)
            + B.footer(f"{E('note')} measured from the server, not from your device"),
        )

    # ── /sudoers ───────────────────────────────────────────────────────────
    @client.on_message(filters.command(["sudoers", "sudo", "owners"]) & owner)
    async def _sudoers(_: Client, message: Message) -> None:
        ids = sorted(settings.owners)
        names: dict[int, str] = {}
        if ids:
            try:
                async for user in client.get_users(ids):
                    names[user.id] = display_name(user)
            except Exception:  # pragma: no cover - network
                pass
        lines = []
        for user_id in ids:
            role = "owner" if user_id == settings.owner_id else "sudo"
            who = rich.esc(names.get(user_id) or "unknown")
            lines.append(f"• <code>{user_id}</code> — {who} <i>({role})</i>")
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('shield')} sudoers", 3)
            + (B.bullets(lines) if lines else B.note(f"{E('warn')} No owners configured."))
            + B.footer(
                f"{E('note')} add ids via <code>SUDO_USERS=1,2,3</code> in .env, then restart"
            ),
            reply_to=message.id,
        )

    # ── /whoami ────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["whoami", "myid"]))
    async def _whoami(_: Client, message: Message) -> None:
        user = message.from_user
        rows = [
            (f"{E('user')} name", rich.esc(display_name(user))),
            (f"{E('id')} user id", f"<code>{user.id if user else '-'}</code>"),
            (f"{E('chat')} chat", rich.esc(truncate(message.chat.title or "private", 34))),
            (f"{E('id')} chat id", f"<code>{message.chat.id}</code>"),
            (f"{E('shield')} role", "<b>owner</b>" if is_owner(user.id if user else 0) else "<b>listener</b>"),
        ]
        if runtime.player:
            state = runtime.player.queues.get(message.chat.id)
            rows.append((f"{E('queue')} your queue", f"<b>{len(state.queue)}</b> tracks"))
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('info')} whoami", 3) + B.kv(rows),
            reply_to=message.id,
        )


__all__ = ["register"]
