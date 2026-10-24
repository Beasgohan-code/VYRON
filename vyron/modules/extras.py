# ---------------------------------------------------------------------------
#  VYRON — owner & operations extras
#  block/unblock · activevc · sysstats · leaveall · sudo list
#  Maintenance and broadcast commands.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.ui import blocks as B, cards
from vyron.ui import rich
from vyron.ui.progress import human_size, human_time, truncate
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args, display_name, is_owner
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

BLOCKED_USERS: set[int] = set()
BLOCKED_CHATS: set[int] = set()


async def load(storage) -> int:
    """Restore both blocklists from storage. Returns how many entries loaded."""
    if storage is None:
        return 0
    try:
        users = await storage.chat_settings(0) or {}
    except Exception:
        return 0
    for value in users.get("blocked_users") or []:
        try:
            BLOCKED_USERS.add(int(value))
        except (TypeError, ValueError):
            continue
    for value in users.get("blocked_chats") or []:
        try:
            BLOCKED_CHATS.add(int(value))
        except (TypeError, ValueError):
            continue
    return len(BLOCKED_USERS) + len(BLOCKED_CHATS)


def register(client: Client) -> None:
    # ── blocklist ──────────────────────────────────────────────────────────
    @client.on_message(cmd(["block"]) & owner)
    async def _block(_: Client, message: Message) -> None:
        """Block a user (reply/id) or a whole chat (negative id).

        A blocked chat is ignored outright — no command runs, nothing is
        played — which is what `/block -100123…` means to an owner whose bot
        was added to a group they do not want to serve.
        """
        arg = command_args(message).strip()
        reply_user = message.reply_to_message.from_user if message.reply_to_message else None
        target: int | None = None
        as_chat = False
        if arg.lstrip("-").isdigit():
            target = int(arg)
            as_chat = target < 0
        elif reply_user:
            target = reply_user.id
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                cards.info_card("Reply to a user, or pass an id.\n"
                    "<code>/block 123456789</code> · <code>/block -1001234567890</code> (chat)"),
                reply_to=message.id,
            )
            return
        bucket, store, label = (
            (BLOCKED_CHATS, "blocked_chats", "chat") if as_chat
            else (BLOCKED_USERS, "blocked_users", "user")
        )
        bucket.add(int(target))
        if runtime.storage:
            await runtime.storage.set_chat_setting(0, store, sorted(bucket))
        await rich.send(
            client,
            message.chat.id,
            B.row(
                B.btn(
                    f"{E('cross')} Blocked {label} {target}",
                    data="v:noop",
                    style="danger",
                )
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["unblock"]) & owner)
    async def _unblock(_: Client, message: Message) -> None:
        arg = command_args(message).strip()
        reply_user = message.reply_to_message.from_user if message.reply_to_message else None
        target = int(arg) if arg.lstrip("-").isdigit() else None
        if target is None and reply_user:
            target = reply_user.id
        if target is None:
            await rich.send(
                client, message.chat.id, cards.info_card("Reply to a user or pass an id.")
            )
            return
        was = int(target) in BLOCKED_USERS or int(target) in BLOCKED_CHATS
        BLOCKED_USERS.discard(int(target))
        BLOCKED_CHATS.discard(int(target))
        if runtime.storage:
            await runtime.storage.set_chat_setting(0, "blocked_users", sorted(BLOCKED_USERS))
            await runtime.storage.set_chat_setting(0, "blocked_chats", sorted(BLOCKED_CHATS))
        await rich.send(
            client,
            message.chat.id,
            B.row(
                B.btn(
                    f"{E('check')} {'Unblocked' if was else 'Was not blocked:'} {target}",
                    data="v:noop",
                    style="success",
                )
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["blocklist"]))
    async def _blocklist(_: Client, message: Message) -> None:
        if not is_owner(message.from_user.id):
            return
        users = sorted(BLOCKED_USERS)
        chats = sorted(BLOCKED_CHATS)
        if not users and not chats:
            await rich.send(
                client,
                message.chat.id,
                B.banner("blocklist", glyph="shield")
                + B.note(
                    f"{E('check')} Nobody is blocked.\n"
                    f"{E('info')} Use <code>/block</code> (reply or id) to add someone."
                ),
                reply_to=message.id,
            )
            return
        rows = []
        for uid in users[:20]:
            label = str(uid)
            try:
                user = await client.get_users(uid)
                label = f"{rich.esc(display_name(user))} · <code>{uid}</code>"
            except Exception:
                label = f"<code>{uid}</code>"
            rows.append((label, "user"))
        for cid in chats[:10]:
            label = f"<code>{cid}</code>"
            try:
                peer = await client.get_chat(cid)
                label = f"{rich.esc(truncate(peer.title or 'chat', 26))} · <code>{cid}</code>"
            except Exception:
                pass
            rows.append((label, "chat"))
        buttons = B.row(
            *[
                B.btn(f"{E('cross')} {uid}", data=f"v:unblock:{uid}", style="danger")
                for uid in users[:4]
            ]
        )
        await rich.send(
            client,
            message.chat.id,
            B.banner("blocklist", glyph="shield")
            + B.table(["who", "type"], rows)
            + B.note(
                f"{E('info')} {len(users)} user{'s' if len(users) != 1 else ''} · "
                f"{len(chats)} chat{'s' if len(chats) != 1 else ''} — "
                "tap to lift a block, or <code>/unblock &lt;id&gt;</code>."
            )
            + (buttons if users else ""),
            reply_to=message.id,
        )

    # ── active voice chats ─────────────────────────────────────────────────
    @client.on_message(cmd(["vc"]) & owner)
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
            B.banner("active voice chats", glyph="live")
            + (B.table(["chat", "title", "track"], rows) if rows else B.note("no active sessions")),
        )

    # ── system stats ───────────────────────────────────────────────────────
    @client.on_message(cmd(["sysstats"]) & owner)
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
                (f"{E('spark')} Streaming", f"<b>{'on' if runtime.streaming_ready else 'off'}</b>"),
            ]
        )
        await rich.send(client, message.chat.id, B.banner("system", glyph="stats") + body)

    # ── leave every voice chat ─────────────────────────────────────────────
    @client.on_message(cmd(["leavevc"]) & owner)
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

    # ── restart hint ───────────────────────────────────────────────────────
    @client.on_message(cmd(["restart"]) & owner)
    async def _restart(_: Client, message: Message) -> None:
        await rich.send(
            client,
            message.chat.id,
            cards.info_card("Restarting in 2 seconds…\n"
                "<i>With Docker/Render the supervisor brings the process back.</i>"),
        )
        await asyncio.sleep(2)
        # Self-restart: the same interpreter running the same module.
        os.execv(sys.executable, [sys.executable, "-m", "vyron"])  # noqa: S606

    @client.on_callback_query(filters.regex(r"^v:unblock:"))
    async def _unblock_cb(_: Client, cq) -> None:
        if not is_owner(cq.from_user.id):
            await cq.answer("Owner only.", show_alert=True)
            return
        try:
            target = int((cq.data or "").rsplit(":", 1)[-1])
        except ValueError:
            await cq.answer("Bad id.")
            return
        BLOCKED_USERS.discard(target)
        await runtime.storage.set_chat_setting(0, "blocked_users", sorted(BLOCKED_USERS))
        await cq.answer(f"{target} unblocked")
        try:
            await cq.message.edit_text(
                B.note(f"{E('check')} <code>{target}</code> is no longer blocked.")
            )
        except Exception:
            pass

    # ── block enforcement ─────────────────────────────────────────────────
    # A blocked chat never reaches another handler: the message is deleted and
    # propagation stops, so no command, no queue, no download is started.
    @client.on_message(filters.all, group=-3)
    async def _blocked_guard(_: Client, message: Message) -> None:
        user = message.from_user
        chat_id = message.chat.id if message.chat else 0
        blocked = bool(chat_id and chat_id in BLOCKED_CHATS)
        blocked = blocked or bool(user and user.id in BLOCKED_USERS)
        if not blocked:
            return
        try:
            await message.delete()
        except Exception:
            pass
        try:
            message.stop_propagation()  # do not let any other handler react
        except Exception:
            pass


__all__ = ["BLOCKED_CHATS", "BLOCKED_USERS", "load", "register"]
