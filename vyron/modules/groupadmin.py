# ---------------------------------------------------------------------------
#  VYRON — group administration
#  rules · chat info · title/description/photo · slow mode · invites · pinning
#  approvals · deleted-account cleanup · reports — one consistent card style.
#
#  Everything here complements `moderation.py` (ban/kick/mute/warn/purge) and
#  `locks.py` (content locks + anti-flood); it does not duplicate a command.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatMembersFilter, ParseMode
from pyrogram.errors import RPCError
from pyrogram.types import ChatPermissions, Message

from vyron.core import chatcfg
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.ui.theme import E
from vyron.ui.progress import truncate
from vyron.utils.helpers import (
    command_args,
    display_name,
    is_chat_admin,
    is_owner,
    parse_duration,
)
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

GROUP = filters.group

_report_seen: dict[tuple[int, int], float] = {}


# ── helpers ─────────────────────────────────────────────────────────────────
def _pretty_name(user) -> str:
    if user is None:
        return "this chat"
    return truncate(display_name(user) or "user", 36)


async def _can_manage(client: Client, message: Message) -> bool:
    """Admins and owners only; silently ignores anonymous admins."""
    user = message.from_user
    if user is None:
        return False
    if is_owner(user.id):
        return True
    return await is_chat_admin(client, message.chat.id, user.id)


async def _deny(client: Client, message: Message) -> None:
    await rich.send(
        client,
        message.chat.id,
        cards.notice_card(
            "Admins only",
            "This one changes the chat itself — ask an admin.",
            tone="warn",
            icon="shield",
        ),
        reply_to=message.id,
    )


def _reply_text(message: Message) -> str:
    reply = message.reply_to_message
    if reply is None:
        return ""
    return (reply.text or reply.caption or "").strip()


def _argument_or_reply(message: Message) -> str:
    return command_args(message).strip() or _reply_text(message)


async def _bot_is_admin(client: Client, chat_id: int) -> bool:
    me = getattr(client, "me", None)
    if me is None:
        return False
    try:
        member = await client.get_chat_member(chat_id, me.id)
    except Exception:
        return False
    status = getattr(getattr(member, "status", None), "name", "")
    return status in {"ADMINISTRATOR", "OWNER"}


def _approved_ids(raw) -> list[int]:
    ids: list[int] = []
    for entry in raw or []:
        try:
            ids.append(int(entry))
        except (TypeError, ValueError):
            continue
    return ids


async def _approved(chat_id: int) -> list[int]:
    return _approved_ids(await chatcfg.get(chat_id, "approved", []))


async def _target_id(client: Client, message: Message) -> int | None:
    """Resolve a reply, ``@username`` or a numeric id into a user id."""
    reply = message.reply_to_message
    if reply is not None and getattr(reply, "from_user", None):
        return reply.from_user.id
    args = command_args(message).split()
    if not args:
        return None
    raw = args[0]
    if raw.lstrip("-").isdigit():
        return int(raw)
    if raw.startswith("@"):
        try:
            user = await client.get_users(raw)
            return getattr(user, "id", None)
        except Exception:
            return None
    return None


# ── registration ────────────────────────────────────────────────────────────
def register(client: Client) -> None:
    # ── the map ────────────────────────────────────────────────────────────
    @client.on_message(cmd(["gadmin"]) & GROUP)
    async def _panel(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        chat_id = message.chat.id
        raw_locks = await chatcfg.get(chat_id, "locks", {})
        flood = await chatcfg.get(chat_id, "flood", {})
        locked = len([1 for value in (raw_locks or {}).values() if value])
        if flood.get("enabled"):
            locked += 1
        await rich.send(
            client,
            chat_id,
            cards.group_admin_card(
                rules=await chatcfg.get(chat_id, "rules", ""),
                slowmode=int(await chatcfg.get(chat_id, "slowmode", 0) or 0),
                captcha=bool(await chatcfg.get(chat_id, "captcha", False)),
                approved=len(await _approved(chat_id)),
                locked=locked,
                warn_limit=int(await chatcfg.get(chat_id, "warn_limit", 3) or 3),
                bot_admin=await _bot_is_admin(client, chat_id),
            ),
            reply_to=message.id,
        )

    # ── rules ──────────────────────────────────────────────────────────────
    @client.on_message(cmd("rules") & GROUP)
    async def _rules(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        text = await chatcfg.get(chat_id, "rules", "") or ""
        can_edit = await _can_manage(client, message) if message.from_user else False
        admins = 0
        try:
            admins = (await client.get_chat(chat_id)).admins_count or 0
        except Exception:
            admins = 0
        await rich.send(
            client,
            chat_id,
            cards.rules_card(
                message.chat.title or "this chat",
                text,
                admins=admins,
                can_edit=can_edit,
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["setrules"]) & GROUP)
    async def _setrules(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        text = _argument_or_reply(message)
        if not text:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Usage",
                    "<code>/setrules Be kind · no spam · no links</code>\n"
                    "Replying to a message also works.",
                    tone="info",
                ),
                reply_to=message.id,
            )
            return
        await chatcfg.set(message.chat.id, "rules", truncate(text, 900, suffix=""))
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Rules saved",
                "Members can read them with <code>/rules</code>.",
                extra=[("Preview", rich.to_html(truncate(text, 120)))],
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["delrules"]) & GROUP)
    async def _clearrules(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        await chatcfg.set(message.chat.id, "rules", "")
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card("Rules cleared", "The rulebook is empty again.", tone="info"),
            reply_to=message.id,
        )

    # ── chat info ──────────────────────────────────────────────────────────
    @client.on_message(cmd(["chatinfo"]) & GROUP)
    async def _info(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        info: dict = {"id": chat_id, "title": message.chat.title}
        try:
            chat = await client.get_chat(chat_id)
        except RPCError:
            chat = None
        if chat is not None:
            info.update(
                {
                    "title": chat.title or message.chat.title,
                    "username": chat.username,
                    "members": chat.members_count,
                    "admins": chat.admins_count,
                    "online": chat.online_count,
                    "slowmode": chat.slow_mode_delay,
                    "description": chat.description,
                    "protected": chat.has_protected_content,
                    "forum": chat.is_forum,
                    "dc": chat.dc_id,
                    "invite": chat.invite_link,
                    "pinned": getattr(getattr(chat, "pinned_message", None), "text", None),
                }
            )
            if chat.linked_chat:
                info["linked"] = chat.linked_chat.title or chat.linked_chat.username or "linked"
        if not info.get("members"):
            try:
                info["members"] = await client.get_chat_members_count(chat_id)
            except Exception:
                info["members"] = 0
        if not info.get("admins"):
            try:
                count = 0
                async for _member in client.get_chat_members(
                    chat_id, filter=ChatMembersFilter.ADMINISTRATORS
                ):
                    count += 1
                info["admins"] = count
            except Exception:
                info["admins"] = 0
        await rich.send(client, chat_id, cards.chat_info_card(info), reply_to=message.id)

    # ── title · description · photo ────────────────────────────────────────
    @client.on_message(cmd(["settitle"]) & GROUP)
    async def _settitle(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        title = _argument_or_reply(message)
        if not (1 <= len(title) <= 128):
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Title needs 1–128 characters",
                    "Usage: <code>/settitle Chill Vibes</code>",
                    tone="warn",
                ),
                reply_to=message.id,
            )
            return
        try:
            await client.set_chat_title(message.chat.id, title)
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Telegram refused", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card("Chat renamed", f"Now called <b>{rich.esc(title)}</b>."),
            reply_to=message.id,
        )

    @client.on_message(cmd(["setdesc"]) & GROUP)
    async def _setdesc(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        text = _argument_or_reply(message)
        try:
            await client.set_chat_description(message.chat.id, text[:255])
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Telegram refused", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Description updated" if text else "Description cleared",
                rich.esc(truncate(text, 160)) if text else "The chat has no description now.",
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["setchatphoto"]) & GROUP)
    async def _setphoto(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        reply = message.reply_to_message
        photo = getattr(reply, "photo", None) if reply else None
        if photo is None:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Reply to a photo",
                    "Send an image, then reply to it with <code>/setgphoto</code>.",
                    tone="info",
                ),
                reply_to=message.id,
            )
            return
        try:
            await client.set_chat_photo(message.chat.id, photo=photo.file_id)
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Telegram refused", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card("Chat photo updated", "Looks sharp."),
            reply_to=message.id,
        )

    @client.on_message(cmd(["delchatphoto"]) & GROUP)
    async def _delphoto(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        try:
            await client.delete_chat_photo(message.chat.id)
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Telegram refused", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card("Chat photo removed", tone="info"),
            reply_to=message.id,
        )

    # ── slow mode ──────────────────────────────────────────────────────────
    @client.on_message(cmd("slowmode") & GROUP)
    async def _slowmode(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        raw = command_args(message).strip().lower()
        seconds = parse_duration(raw) if raw else None
        if seconds is None:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Usage",
                    "<code>/slowmode 30s</code> · <code>/slowmode 1m</code> · "
                    "<code>/slowmode off</code>",
                    tone="info",
                ),
                reply_to=message.id,
            )
            return
        seconds = max(0, min(seconds, 21600))
        try:
            await client.set_slow_mode(message.chat.id, seconds)
        except (RPCError, AttributeError) as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Telegram refused",
                    rich.esc(exc) + "\nSlow mode needs an admin with the *change info* right.",
                    tone="error",
                ),
                reply_to=message.id,
            )
            return
        await chatcfg.set(message.chat.id, "slowmode", seconds)
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Slow mode updated",
                "New messages will be spaced out." if seconds else "Slow mode is off.",
                extra=[("Interval", cards.slow_label(seconds))],
            ),
            reply_to=message.id,
        )

    # ── pinning ────────────────────────────────────────────────────────────
    @client.on_message(cmd("unpinall") & GROUP)
    async def _unpinall(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        try:
            await client.unpin_all_chat_messages(message.chat.id)
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Telegram refused", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card("All messages unpinned", tone="info"),
            reply_to=message.id,
        )

    @client.on_message(cmd(["pinned"]) & GROUP)
    async def _pinned(_: Client, message: Message) -> None:
        pinned = getattr(message.chat, "pinned_message", None)
        text = None
        if pinned is not None:
            text = pinned.text or pinned.caption or "a media message"
        if not text:
            try:
                chat = await client.get_chat(message.chat.id)
                pinned = getattr(chat, "pinned_message", None)
                if pinned is not None:
                    text = pinned.text or pinned.caption or "a media message"
            except Exception:
                text = None
        if not text:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Nothing pinned", "An admin can pin with /pin on a reply.", tone="info"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Pinned message",
                rich.esc(truncate(text, 300)),
                tone="info",
                icon="star",
                footer="open the chat's pin bar to jump there",
            ),
            reply_to=message.id,
        )

    # ── invites ────────────────────────────────────────────────────────────
    @client.on_message(cmd(["invitelink"]) & GROUP)
    async def _invite(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        try:
            link = await client.export_chat_invite_link(message.chat.id)
        except RPCError:
            try:
                created = await client.create_chat_invite_link(message.chat.id)
                link = created.invite_link
            except RPCError as exc:
                await rich.send(
                    client,
                    message.chat.id,
                    cards.notice_card(
                        "Telegram refused",
                        rich.esc(exc) + "\nGive me the *invite users* right.",
                        tone="error",
                    ),
                    reply_to=message.id,
                )
                return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Invite link",
                f"<code>{rich.esc(str(link))}</code>",
                extra=[("Chat", rich.esc(truncate(message.chat.title or "", 40)))],
                footer="/revokeinvite invalidates it",
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd("revokeinvite") & GROUP)
    async def _revoke(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        try:
            link = await client.export_chat_invite_link(message.chat.id)
            await client.revoke_chat_invite_link(message.chat.id, link)
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Telegram refused", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Invite link revoked",
                "Everyone with the old link can no longer join.\n"
                "Use <code>/invitelink</code> for a fresh one.",
                tone="warn",
            ),
            reply_to=message.id,
        )

    # ── reports ────────────────────────────────────────────────────────────
    @client.on_message(cmd("report") & GROUP)
    async def _report(_: Client, message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        reply = message.reply_to_message
        if reply is None:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Reply to the message you are reporting",
                    "Usage: reply → <code>/report spam</code>",
                    tone="info",
                ),
                reply_to=message.id,
            )
            return

        now = time.monotonic()
        last = _report_seen.get((message.chat.id, user.id), 0)
        if now - last < 30:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Already reported",
                    "Give the admins a moment to look at the last one.",
                    tone="warn",
                ),
                reply_to=message.id,
            )
            return
        if len(_report_seen) > 2048:
            _report_seen.clear()
        _report_seen[(message.chat.id, user.id)] = now

        admins: list[str] = []
        try:
            async for member in client.get_chat_members(
                message.chat.id, filter=ChatMembersFilter.ADMINISTRATORS
            ):
                person = getattr(member, "user", None)
                if person and not person.is_bot and person.id != user.id:
                    admins.append(person.mention)
        except Exception:
            admins = []

        reason = command_args(message).strip()
        link = ""
        try:
            link = message.link or ""
        except Exception:
            link = ""

        detail = f"{user.mention} flagged a message"
        if reason:
            detail += f" — <i>{rich.esc(truncate(reason, 80))}</i>"
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Report sent",
                detail,
                tone="warn",
                icon="warn",
                extra=[("Admins notified", str(len(admins)))],
                footer="abuse of /report is itself a warnable offence",
            ),
            reply_to=reply.id,
        )
        if admins:
            try:
                await client.send_message(
                    message.chat.id,
                    " ".join(admins[:6]) + f"\n{E('warn')} reported by {user.mention}",
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=reply.id,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
        await _log(client, f"report in <code>{message.chat.id}</code> by {user.id} · {link}")

    # ── approvals (locks / anti-flood exemptions) ──────────────────────────
    @client.on_message(cmd("approve") & GROUP)
    async def _approve(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        target = await _target_id(client, message)
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Who should I approve?",
                    "Reply to a user or pass an id: <code>/approve 123456</code>",
                    tone="info",
                ),
                reply_to=message.id,
            )
            return
        ids = await _approved(message.chat.id)
        if target in ids:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Already approved", f"<code>{target}</code> is exempt.", tone="info"),
                reply_to=message.id,
            )
            return
        ids.append(target)
        await chatcfg.set(message.chat.id, "approved", ids[-200:])
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "User approved",
                "They now skip locks and the flood limiter.",
                extra=[("ID", f"<code>{target}</code>")],
                actions=B.row(
                    B.btn("See the list", data="v:grp:approved", style="link"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd("unapprove") & GROUP)
    async def _unapprove(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        target = await _target_id(client, message)
        ids = await _approved(message.chat.id)
        if target is None or target not in ids:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Not on the list", "That user is not approved.", tone="warn"),
                reply_to=message.id,
            )
            return
        ids.remove(target)
        await chatcfg.set(message.chat.id, "approved", ids)
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Approval revoked",
                "Locks and anti-flood apply to them again.",
                extra=[("ID", f"<code>{target}</code>")],
                tone="info",
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd("approved") & GROUP)
    async def _approved_list(_: Client, message: Message) -> None:
        ids = await _approved(message.chat.id)
        entries = [(f"user {index + 1}", str(uid)) for index, uid in enumerate(ids)]
        await rich.send(
            client, message.chat.id, cards.approved_card(entries), reply_to=message.id
        )

    # ── deleted accounts ───────────────────────────────────────────────────
    @client.on_message(cmd(["zombies"]) & GROUP)
    async def _zombies(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        kick = command_args(message).strip().lower() in {"kick", "clean", "purge"}
        cap = 1500
        scanned = 0
        found: list[tuple[str, str]] = []
        progress = await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                "Scanning members…",
                "This walks the member list — big groups take a moment.",
                tone="info",
                icon="bolt",
            ),
            reply_to=message.id,
        )
        try:
            async for member in client.get_chat_members(message.chat.id):
                person = getattr(member, "user", None)
                if person is None:
                    continue
                scanned += 1
                if getattr(person, "is_deleted", False):
                    found.append((_pretty_name(person), str(person.id)))
                if scanned >= cap:
                    break
        except RPCError as exc:
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card("Could not list members", rich.esc(exc), tone="error"),
                reply_to=message.id,
            )
            return

        kicked = 0
        if kick and found:
            for _name, uid in found:
                try:
                    await client.ban_chat_member(message.chat.id, int(uid))
                    await client.unban_chat_member(message.chat.id, int(uid))
                    kicked += 1
                except RPCError:
                    continue
        card = cards.zombies_card(found, scanned=scanned, kicked=kicked, capped=scanned >= cap)
        if progress is not None:
            await rich.edit(client, message.chat.id, progress.id, card)
        else:
            await rich.send(client, message.chat.id, card, reply_to=message.id)
        if found:
            await _log(client, f"zombies: {len(found)} found, {kicked} kicked in <code>{message.chat.id}</code>")

    # ── captcha gate ───────────────────────────────────────────────────────
    @client.on_message(cmd("captcha") & GROUP)
    async def _captcha_toggle(_: Client, message: Message) -> None:
        if not await _can_manage(client, message):
            await _deny(client, message)
            return
        current = bool(await chatcfg.get(message.chat.id, "captcha", False))
        arg = command_args(message).strip().lower()
        enabled = (arg in {"on", "yes", "1", "true"}) if arg else not current
        await chatcfg.set(message.chat.id, "captcha", enabled)
        await rich.send(
            client,
            message.chat.id,
            cards.notice_card(
                f"Captcha {'on' if enabled else 'off'}",
                "New members get one button to tap before they can talk."
                if enabled
                else "New members can talk straight away.",
                tone="ok" if enabled else "info",
                icon="shield",
                footer="give me the *restrict members* right so I can mute them",
            ),
            reply_to=message.id,
        )

    @client.on_message(filters.new_chat_members)
    async def _gate(_: Client, message: Message) -> None:
        if not await chatcfg.get(message.chat.id, "captcha", False):
            return
        for member in message.new_chat_members or []:
            if member is None or getattr(member, "is_bot", False):
                continue
            try:
                await client.restrict_chat_member(
                    message.chat.id,
                    member.id,
                    ChatPermissions(can_send_messages=False),
                )
            except Exception:
                continue
            await rich.send(
                client,
                message.chat.id,
                cards.captcha_card(member.mention, user_id=member.id),
            )

    # ── fallback: reply to any unknown /group-style help ───────────────────
    @client.on_message(cmd(["adminhelp"]) & GROUP)
    async def _grouphelp(_: Client, message: Message) -> None:
        await rich.send(
            client,
            message.chat.id,
            cards.help_card("social"),
            markup_keyboard=keyboards.help_nav("social"),
            reply_to=message.id,
        )


async def verify_captcha(client: Client, query, chat_id: int, arg: str) -> None:
    """Unmute a new member who tapped their captcha button."""
    user = getattr(query, "from_user", None)
    if user is None:
        return
    if arg not in {"", "self"} and str(user.id) != str(arg):
        await rich.answer(query, "That button is not for you.", show_alert=True)
        return
    try:
        await client.restrict_chat_member(
            chat_id,
            user.id,
            ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
    except Exception as exc:
        await rich.answer(query, f"Could not verify: {truncate(str(exc), 60)}", show_alert=True)
        return
    message = getattr(query, "message", None)
    if message is not None:
        await rich.edit(
            client,
            chat_id,
            message.id,
            cards.notice_card(
                "Verified",
                f"{user.mention} can talk now. Welcome aboard.",
                icon="check",
            ),
        )
    await rich.answer(query, "Verified — welcome!")


async def _log(client: Client, text: str) -> None:
    """Mirror destructive actions into the logger channel when configured."""
    target = getattr(runtime.settings, "logger_id", 0)
    if not target:
        return
    try:
        await client.send_message(target, text, parse_mode=ParseMode.HTML)
    except Exception:
        logger.debug("logger channel unavailable", exc_info=True)


__all__ = ["register", "verify_captcha"]
