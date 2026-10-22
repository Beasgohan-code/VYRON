# ---------------------------------------------------------------------------
#  VYRON — owner & operations extras
#  block/unblock · activevc · sysstats · leaveall · gcast · sudo list
#  Ideas and command surface modelled on FallenMusic (AnonymousX1025) and Videl.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import human_size, human_time
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args, is_chat_admin, is_owner

logger = logging.getLogger(__name__)

BLOCKED_USERS: set[int] = set()
BLOCKED_CHATS: set[int] = set()


def _blocked_store():
    """Persist blocklists inside the shared storage document."""
    return runtime.storage


def register(client: Client) -> None:
    # ── blocklist ──────────────────────────────────────────────────────────
    @client.on_message(filters.command(["block"]) & owner)
    async def _block(_: Client, message: Message) -> None:
        arg = command_args(message)
        target = None
        if message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user.id
        elif arg.lstrip("-").isdigit():
            target = int(arg)
        if target is None:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        BLOCKED_USERS.add(int(target))
        await runtime.storage.set_chat_setting(0, "blocked_users", sorted(BLOCKED_USERS))
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('cross')} Blocked {target}", data="v:noop", style="danger")),
        )

    @client.on_message(filters.command(["unblock"]) & owner)
    async def _unblock(_: Client, message: Message) -> None:
        arg = command_args(message)
        target = int(arg) if arg.lstrip("-").isdigit() else None
        if target is None and message.reply_to_message and message.reply_to_message.from_user:
            target = message.reply_to_message.from_user.id
        if target is None:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        BLOCKED_USERS.discard(int(target))
        await runtime.storage.set_chat_setting(0, "blocked_users", sorted(BLOCKED_USERS))
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Unblocked {target}", data="v:noop", style="success")),
        )

    @client.on_message(filters.command(["blocklist", "blocked"]))
    async def _blocklist(_: Client, message: Message) -> None:
        if not is_owner(message.from_user.id):
            return
        rows = [(f"<code>{uid}</code>", "user") for uid in sorted(BLOCKED_USERS)[:40]]
        rows += [(f"<code>{cid}</code>", "chat") for cid in sorted(BLOCKED_CHATS)[:10]]
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('shield')} blocklist", 3)
            + (B.table(["id", "type"], rows) if rows else B.note("nothing blocked")),
        )

    # ── active voice chats ─────────────────────────────────────────────────
    @client.on_message(filters.command(["activevc", "vc", "sessions"]) & owner)
    async def _activevc(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        rows = []
        for chat_id in runtime.player.active_chats():
            state = runtime.player.queues.get(chat_id)
            title = ""
            try:
                chat = await client.get_chat(chat_id)
                title = chat.title or chat.first_name or ""
            except Exception:
                title = "private or unknown"
            rows.append(
                (
                    f"<code>{chat_id}</code>",
                    rich.esc(title[:30]),
                    rich.esc((state.current.title[:26] if state.current else "—")),
                )
            )
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('live')} active voice chats", 3)
            + (B.table(["chat", "title", "track"], rows) if rows else B.note("no active sessions")),
        )

    # ── system stats ───────────────────────────────────────────────────────
    @client.on_message(filters.command(["sysstats", "system"]) & owner)
    async def _sysstats(_: Client, message: Message) -> None:
        uptime = runtime.uptime
        try:
            import resource

            ram = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            ram_text = f"{ram:.0f} MB"
        except Exception:
            ram_text = "n/a"
        try:
            load = ", ".join(f"{v:.2f}" for v in os.getloadavg())
        except Exception:
            load = "n/a"
        disk_free = "n/a"
        try:
            stat = os.statvfs(runtime.settings.downloads_dir)
            disk_free = human_size(stat.f_bavail * stat.f_frsize)
        except Exception:
            pass
        body = B.kv(
            [
                (f"{E('clock')} Uptime", f"<b>{human_time(uptime)}</b>"),
                (f"{E('code')} Python", f"<b>{platform.python_version()}</b>"),
                (f"{E('cloud')} Host", f"<b>{platform.system()} {platform.release()}</b>"),
                (f"{E('bolt')} Load", f"<b>{load}</b>"),
                (f"{E('stats')} Memory", f"<b>{ram_text}</b>"),
                (f"{E('download')} Disk free", f"<b>{disk_free}</b>"),
                (f"{E('chat')} Active VC", f"<b>{len(runtime.player.active_chats()) if runtime.player else 0}</b>"),
                (f"{E('spark')} Streaming", f"<b>{'yes' if runtime.streaming_ready else 'file mode'}</b>"),
            ]
        )
        await rich.send(client, message.chat.id, B.heading(f"{E('stats')} system", 3) + body)

    # ── leave every voice chat ─────────────────────────────────────────────
    @client.on_message(filters.command(["leaveall", "leavevc"]) & owner)
    async def _leaveall(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        chats = runtime.player.active_chats()
        for chat_id in chats:
            await runtime.player.leave(chat_id)
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Left {len(chats)} voice chats", data="v:noop", style="success")),
        )

    # ── broadcast alias (gcast) ────────────────────────────────────────────
    @client.on_message(filters.command(["gcast"]) & owner)
    async def _gcast(_: Client, message: Message) -> None:
        text = command_args(message)
        target = message.reply_to_message
        if not text and not target:
            await rich.send(client, message.chat.id, f"{E('info')} Usage: <code>/gcast hello</code>")
            return
        chats = await runtime.storage.all_chat_ids()
        sent = failed = 0
        for chat_id in chats:
            try:
                if target:
                    await target.copy(chat_id)
                else:
                    await client.send_message(chat_id, text)
                sent += 1
            except Exception:
                failed += 1
            await asyncio.sleep(0.05)
        await rich.send(
            client,
            message.chat.id,
            B.row(
                B.btn(
                    f"{E('rocket')} gcast: {sent} sent · {failed} failed",
                    data="v:noop",
                    style="success",
                )
            ),
        )

    # ── restart hint ───────────────────────────────────────────────────────
    @client.on_message(filters.command(["restart"]) & owner)
    async def _restart(_: Client, message: Message) -> None:
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('rocket')} Restarting in 2 seconds…\n"
                "<i>With Docker/Render the supervisor brings the process back.</i>"
            ),
        )
        await asyncio.sleep(2)
        os.execv(sys.executable, [sys.executable, "-m", "vyron"])

    # ── block enforcement ─────────────────────────────────────────────────
    @client.on_message(filters.all, group=-3)
    async def _blocked_guard(_: Client, message: Message) -> None:
        user = message.from_user
        if not user or user.id not in BLOCKED_USERS:
            return
        try:
            await message.delete()
        except Exception:
            pass
        try:
            message.stop_propagation()  # do not let any other handler react
        except Exception:
            pass


__all__ = ["BLOCKED_CHATS", "BLOCKED_USERS", "register"]
