# ---------------------------------------------------------------------------
#  VYRON — group management
#  ban · kick · mute · warn · purge · pin · welcome/goodbye · admin list
#  Admin commands with a single consistent card UI.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMembersFilter, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import ChatPrivileges, Message

from vyron.core import chatcfg
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, display_name, is_chat_admin, is_owner

logger = logging.getLogger(__name__)

BOT_ADMIN = filters.group


def _target(message: Message):
    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user
    arg = command_args(message).split()[0] if command_args(message) else ""
    if arg.lstrip("@").isdigit():
        return int(arg)
    if arg.startswith("@"):
        return arg
    return None


async def _resolve_id(client: Client, target) -> int | None:
    if target is None:
        return None
    if isinstance(target, int):
        return target
    if isinstance(target, str):
        try:
            chat = await client.get_users(target)
            return chat.id
        except Exception:
            return None
    return getattr(target, "id", None)


def _pretty(user) -> str:
    name = display_name(user) if user is not None else "user"
    return rich.to_html(B.esc(truncate(name, 32)))


async def _require_admin(client: Client, message: Message) -> bool:
    if is_owner(message.from_user.id):
        return True
    if await is_chat_admin(client, message.chat.id, message.from_user.id):
        return True
    await rich.send(
        client,
        message.chat.id,
        B.row(
            B.btn(f"{E('shield')} You need to be an admin", data="v:noop", style="danger")
        ),
        reply_to=message.id,
    )
    return False


async def _log(client: Client, text: str) -> None:
    if not runtime.settings.logger_id:
        return
    try:
        await client.send_message(runtime.settings.logger_id, text, parse_mode=ParseMode.HTML)
    except Exception:
        pass


def register(client: Client) -> None:
    # ── ban / unban / kick ─────────────────────────────────────────────────
    @client.on_message(filters.command(["ban", "dban"]) & BOT_ADMIN)
    async def _ban(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.ban_chat_member(message.chat.id, target)
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('shield')} Banned", data="v:noop", style="danger")),
            )
            await _log(client, f"🔨 <b>ban</b> · {target} in <code>{message.chat.id}</code>")
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    @client.on_message(filters.command("unban") & BOT_ADMIN)
    async def _unban(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.unban_chat_member(message.chat.id, target)
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('check')} Unbanned", data="v:noop", style="success")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    @client.on_message(filters.command(["kick", "dkick"]) & BOT_ADMIN)
    async def _kick(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.ban_chat_member(message.chat.id, target)
            await client.unban_chat_member(message.chat.id, target)
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('bolt')} Kicked", data="v:noop", style="danger")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    # ── mute / unmute ──────────────────────────────────────────────────────
    @client.on_message(filters.command(["mute", "tmute"]) & BOT_ADMIN)
    async def _mute(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.restrict_chat_member(
                message.chat.id,
                target,
                ChatPrivileges(can_send_messages=False),
            )
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('mute')} Muted", data="v:noop", style="danger")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    @client.on_message(filters.command("unmute") & BOT_ADMIN)
    async def _unmute(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.restrict_chat_member(
                message.chat.id,
                target,
                ChatPrivileges(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                ),
            )
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('volume')} Unmuted", data="v:noop", style="success")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    # ── promote / demote ───────────────────────────────────────────────────
    @client.on_message(filters.command("promote") & BOT_ADMIN)
    async def _promote(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.promote_chat_member(
                message.chat.id,
                target,
                ChatPrivileges(
                    can_change_info=True,
                    can_delete_messages=True,
                    can_invite_users=True,
                    can_restrict_members=True,
                    can_pin_messages=True,
                    can_manage_video_chats=True,
                    can_promote_members=True,
                ),
            )
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('crown')} Promoted", data="v:noop", style="success")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    @client.on_message(filters.command("demote") & BOT_ADMIN)
    async def _demote(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        try:
            await client.promote_chat_member(
                message.chat.id,
                target,
                ChatPrivileges(
                    can_change_info=False,
                    can_delete_messages=False,
                    can_invite_users=False,
                    can_restrict_members=False,
                    can_pin_messages=False,
                    can_manage_video_chats=False,
                    can_promote_members=False,
                ),
            )
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('user')} Demoted", data="v:noop")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    # ── warns ──────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["warn", "dwarn"]) & BOT_ADMIN)
    async def _warn(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        count, limit = await chatcfg.add_warn(message.chat.id, target)
        if count >= limit:
            try:
                await client.ban_chat_member(message.chat.id, target)
            except RPCError:
                pass
            await chatcfg.remove_warn(message.chat.id, target)
            markup = B.row(
                B.btn(
                    f"{E('shield')} {count}/{limit} warns — user banned",
                    data="v:noop",
                    style="danger",
                )
            )
        else:
            markup = B.row(
                B.btn(
                    f"{E('warn')} Warning {count}/{limit}",
                    data="v:noop",
                    style="primary" if count < limit - 1 else "danger",
                )
            )
        await rich.send(client, message.chat.id, markup)

    @client.on_message(filters.command(["warns", "warnings"]) & BOT_ADMIN)
    async def _warns(_: Client, message: Message) -> None:
        target = await _resolve_id(client, _target(message))
        if not target:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to a user or pass an id.")
            return
        count = await chatcfg.warns_of(message.chat.id, target)
        limit = int(await chatcfg.get(message.chat.id, "warn_limit", 3) or 3)
        await rich.send(
            client,
            message.chat.id,
            B.table(["user", "warns", "limit"], [(f"<code>{target}</code>", str(count), str(limit))]),
        )

    @client.on_message(filters.command(["resetwarns", "rmwarns", "unwarn"]) & BOT_ADMIN)
    async def _resetwarns(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        target = await _resolve_id(client, _target(message))
        if not target:
            cleared = await chatcfg.reset_warns(message.chat.id)
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('check')} Cleared {cleared} warnings", data="v:noop", style="success")),
            )
            return
        warns = await chatcfg.get(message.chat.id, "warns", {})
        warns.pop(str(target), None)
        await chatcfg.set(message.chat.id, "warns", warns)
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Warnings cleared", data="v:noop", style="success")),
        )

    @client.on_message(filters.command(["setwarnlimit", "warnlimit"]) & BOT_ADMIN)
    async def _warnlimit(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        arg = command_args(message)
        if not arg.isdigit() or not (1 <= int(arg) <= 10):
            await rich.send(client, message.chat.id, f"{E('info')} Use <code>/setwarnlimit 3</code> (1-10).")
            return
        await chatcfg.set(message.chat.id, "warn_limit", int(arg))
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Warn limit set to {arg}", data="v:noop", style="success")),
        )

    # ── purge / pin ────────────────────────────────────────────────────────
    @client.on_message(filters.command(["purge", "del"]) & BOT_ADMIN)
    async def _purge(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        reply = message.reply_to_message
        if not reply:
            await rich.send(client, message.chat.id, f"{E('info')} Reply to the first message to delete.")
            return
        ids = list(range(reply.id, message.id + 1))
        removed = 0
        for index in range(0, len(ids), 100):
            chunk = ids[index : index + 100]
            try:
                await client.delete_messages(message.chat.id, chunk)
                removed += len(chunk)
            except RPCError:
                break
        try:
            await message.delete()
        except RPCError:
            pass
        if removed:
            sent = await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('check')} Purged {removed} messages", data="v:noop", style="success")),
            )
            if sent:
                try:
                    import asyncio

                    await asyncio.sleep(4)
                    await sent.delete()
                except Exception:
                    pass

    @client.on_message(filters.command("pin") & BOT_ADMIN)
    async def _pin(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        reply = message.reply_to_message or message
        try:
            await client.pin_chat_message(message.chat.id, reply.id, disable_notification=True)
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('star')} Pinned", data="v:noop", style="success")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    @client.on_message(filters.command("unpin") & BOT_ADMIN)
    async def _unpin(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        try:
            await client.unpin_chat_message(message.chat.id)
            await rich.send(
                client,
                message.chat.id,
                B.row(B.btn(f"{E('check')} Unpinned", data="v:noop")),
            )
        except RPCError as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")

    # ── welcome / goodbye ──────────────────────────────────────────────────
    @client.on_message(filters.command("setwelcome") & BOT_ADMIN)
    async def _setwelcome(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        text = command_args(message)
        if not text:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    "Usage: <code>/setwelcome Welcome {mention} to {chat}!</code>\n"
                    "Placeholders: <code>{mention}</code> <code>{first}</code> "
                    "<code>{chat}</code> <code>{id}</code> <code>{count}</code>"
                ),
            )
            return
        await chatcfg.set(message.chat.id, "welcome", text)
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Welcome message saved", data="v:noop", style="success")),
        )

    @client.on_message(filters.command(["welcome", "welcomemode"]) & BOT_ADMIN)
    async def _welcome_status(_: Client, message: Message) -> None:
        text = await chatcfg.get(message.chat.id, "welcome", "")
        await rich.send(
            client,
            message.chat.id,
            B.kv(
                [
                    (f"{E('users')} Welcome", "on" if text else "off"),
                    (f"{E('info')} Message", rich.esc(truncate(text, 80)) or "—"),
                ]
            ),
        )

    @client.on_message(filters.command("setgoodbye") & BOT_ADMIN)
    async def _setgoodbye(_: Client, message: Message) -> None:
        if not await _require_admin(client, message):
            return
        text = command_args(message)
        if not text:
            await rich.send(
                client,
                message.chat.id,
                B.note("Usage: <code>/setgoodbye {first} just left {chat}</code>"),
            )
            return
        await chatcfg.set(message.chat.id, "goodbye", text)
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Goodbye message saved", data="v:noop", style="success")),
        )

    @client.on_message(filters.new_chat_members)
    async def _greet(_: Client, message: Message) -> None:
        template = await chatcfg.get(message.chat.id, "welcome", "") or runtime.settings.welcome_default
        if not template:
            return
        for member in message.new_chat_members:
            if not member or getattr(member, "is_bot", False):
                continue
            try:
                count = await client.get_chat_members_count(message.chat.id)
            except Exception:
                count = 0
            text = chatcfg.render(
                template,
                mention=member.mention,
                first=display_name(member),
                chat=message.chat.title or "the chat",
                id=member.id,
                count=max(0, count),
            )
            await client.send_message(message.chat.id, text)

    @client.on_message(filters.left_chat_member)
    async def _farewell(_: Client, message: Message) -> None:
        template = await chatcfg.get(message.chat.id, "goodbye", "")
        if not template:
            return
        member = message.left_chat_member
        text = chatcfg.render(
            template,
            mention=member.mention if member else "someone",
            first=display_name(member),
            chat=message.chat.title or "the chat",
            id=getattr(member, "id", 0),
        )
        await client.send_message(message.chat.id, text)

    # ── admin list ─────────────────────────────────────────────────────────
    @client.on_message(filters.command(["admins", "adminlist"]) & BOT_ADMIN)
    async def _admins(_: Client, message: Message) -> None:
        try:
            rows = []
            async for member in client.get_chat_members(
                message.chat.id, filter=ChatMembersFilter.ADMINISTRATORS
            ):
                if getattr(member, "user", None):
                    rows.append(
                        (
                            member.user.mention,
                            member.status.name.lower(),
                        )
                    )
            await rich.send(
                client,
                message.chat.id,
                B.heading(f"{E('shield')} administrators", 3)
                + B.table(["admin", "role"], rows[:40]),
            )
        except Exception as exc:
            await rich.send(client, message.chat.id, f"{E('warn')} {rich.esc(exc)}")


__all__ = ["register"]
