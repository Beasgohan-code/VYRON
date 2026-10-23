# ---------------------------------------------------------------------------
#  VYRON — content locks + anti-flood
#  Locks are enforced in handler group 1, so commands (group 0) always win.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

from pyrogram import Client, filters
from pyrogram.errors import RPCError
from pyrogram.types import ChatPermissions, Message

from vyron.core import chatcfg
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, rich
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, display_name

logger = logging.getLogger(__name__)

LOCK_LABELS = {
    "media": ("song", "Media"),
    "links": ("link", "Links"),
    "forwards": ("back", "Forwards"),
    "stickers": ("star", "Stickers"),
    "bots": ("code", "Bots"),
    "commands": ("tools", "Commands"),
    "nsfw": ("cross", "NSFW"),
}

_URL_RE = re.compile(r"(https?://|t\.me/|www\.)", re.I)
_NSFW_RE = re.compile(r"(porn|xxx|nude|nsfw|sex|18\+)", re.I)


def _store() -> dict[int, dict[int, deque]]:
    return defaultdict(lambda: defaultdict(deque))


_buckets = _store()
_punished: dict[int, dict[int, float]] = defaultdict(dict)


async def _locks(chat_id: int) -> dict:
    return await chatcfg.get(chat_id, "locks", {})


def locks_panel(locks: dict, flood: dict) -> str:
    """Render the lock panel as a rich card with coloured toggles."""
    rows = ""
    buttons: list[str] = []
    for key, (glyph, label) in LOCK_LABELS.items():
        enabled = bool(locks.get(key))
        rows += f"<tr><td>{E(glyph)} {label}</td><td><b>{'🔒 locked' if enabled else '🔓 open'}</b></td></tr>"
        buttons.append(
            B.btn(
                f"{'🔒' if enabled else '🔓'} {label}",
                data=f"v:lock:{key}",
                style="danger" if enabled else None,
            )
        )
    flood_state = "on" if flood.get("enabled") else "off"
    body = B.heading(f"{E('shield')} content locks", 2) + B.table(None, []) + f"<table>{rows}</table>"
    body += B.kv(
        [
            (f"{E('wave')} Anti-flood", f"<b>{flood_state}</b>"),
            (f"{E('clock')} Window", f"<b>{flood.get('limit')} / {flood.get('window')}s</b>"),
        ]
    )
    return (
        body
        + B.divider()
        + B.grid(buttons, columns=2)
        + B.row(
            B.btn(f"{E('wave')} Anti-flood", data="v:lock:flood", style="primary"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
    )


async def _is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    if user_id in runtime.settings.owners:
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status.name in {"ADMINISTRATOR", "OWNER"}
    except Exception:
        return False


def _matches_lock(name: str, message: Message) -> bool:
    if name == "media":
        return bool(message.photo or message.video or message.audio or message.voice or message.document)
    if name == "links":
        text = message.text or message.caption or ""
        return bool(_URL_RE.search(text))
    if name == "forwards":
        return bool(message.forward_date or getattr(message, "forward_origin", None))
    if name == "stickers":
        return bool(message.sticker or message.animation)
    if name == "nsfw":
        text = message.text or message.caption or ""
        return bool(_NSFW_RE.search(text))
    if name == "commands":
        text = message.text or ""
        return text.startswith("/")
    if name == "bots":
        return bool(message.via_bot)
    return False


def register(client: Client) -> None:
    # ── commands ───────────────────────────────────────────────────────────
    @client.on_message(filters.command(["locks", "lockpanel", "contentlocks"]) & filters.group)
    async def _panel(_: Client, message: Message) -> None:
        if not await _is_admin(client, message.chat.id, message.from_user.id):
            await rich.send(
                client,
                message.chat.id,
                cards.notice_card(
                    "Admins only",
                    "Locks are managed by admins.",
                    tone="warn",
                    icon="shield",
                ),
                reply_to=message.id,
            )
            return
        locks = await _locks(message.chat.id)
        flood = await chatcfg.get(message.chat.id, "flood", {})
        await rich.send(client, message.chat.id, locks_panel(locks, flood), reply_to=message.id)

    @client.on_message(filters.command(["antiflood", "setflood"]) & filters.group)
    async def _antiflood(_: Client, message: Message) -> None:
        if not await _is_admin(client, message.chat.id, message.from_user.id):
            return
        flood = await chatcfg.get(message.chat.id, "flood", {})
        arg = command_args(message).lower()
        if arg in {"on", "off"}:
            flood["enabled"] = arg == "on"
        elif arg.isdigit():
            flood["limit"] = max(2, min(30, int(arg)))
            flood["enabled"] = True
        else:
            flood["enabled"] = not flood.get("enabled", True)
        await chatcfg.set(message.chat.id, "flood", flood)
        await rich.send(
            client,
            message.chat.id,
            B.row(
                B.btn(
                    f"{E('wave')} Anti-flood {'on' if flood['enabled'] else 'off'} "
                    f"({flood.get('limit')}/{flood.get('window')}s)",
                    data="v:noop",
                    style="success" if flood["enabled"] else None,
                )
            ),
        )

    @client.on_message(filters.command(["lock", "unlock"]) & filters.group)
    async def _lock_cmd(_: Client, message: Message) -> None:
        if not await _is_admin(client, message.chat.id, message.from_user.id):
            return
        name = command_args(message).strip().lower()
        if name not in LOCK_LABELS:
            await rich.send(
                client,
                message.chat.id,
                B.note("Usage: <code>/lock media</code> · options: " + ", ".join(LOCK_LABELS)),
            )
            return
        value = message.command[0].lower() == "lock"
        locks = await _locks(message.chat.id)
        locks[name] = value
        await chatcfg.set(message.chat.id, "locks", locks)
        glyph, label = LOCK_LABELS[name]
        await rich.send(
            client,
            message.chat.id,
            B.row(
                B.btn(
                    f"{E(glyph)} {label} {'locked' if value else 'unlocked'}",
                    data="v:noop",
                    style="danger" if value else "success",
                )
            ),
        )

    # ── enforcement (group 1: runs only for non-command messages) ─────────
    @client.on_message(filters.group & ~filters.service, group=1)
    async def _enforce(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        user = message.from_user
        if not user or user.is_bot:
            return
        if await _is_admin(client, chat_id, user.id):
            return
        # approved users are trusted: no locks, no flood limiter
        approved = await chatcfg.get(chat_id, "approved", []) or []
        if any(str(user.id) == str(entry) for entry in approved):
            return

        locks = await _locks(chat_id)
        for name, enabled in locks.items():
            if enabled and _matches_lock(name, message):
                try:
                    await message.delete()
                except RPCError:
                    pass
                glyph, label = LOCK_LABELS.get(name, ("cross", name))
                note = await rich.send(
                    client,
                    chat_id,
                    f"{E(glyph)} <b>{label} are locked here</b> — "
                    f"{rich.esc(display_name(user))}, that message was removed.",
                )
                if note:
                    try:
                        import asyncio

                        await asyncio.sleep(5)
                        await note.delete()
                    except Exception:
                        pass
                return

        flood = await chatcfg.get(chat_id, "flood", {})
        if not flood.get("enabled", True):
            return
        limit = int(flood.get("limit", 7))
        window = int(flood.get("window", 9))
        now = time.monotonic()
        bucket = _buckets[chat_id][user.id]
        bucket.append(now)
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) <= limit:
            return

        # over the limit — delete and briefly mute
        bucket.clear()
        last = _punished[chat_id].get(user.id, 0)
        if now - last < 30:
            return
        _punished[chat_id][user.id] = now
        try:
            await message.delete()
        except RPCError:
            pass
        try:
            await client.restrict_chat_member(
                chat_id,
                user.id,
                ChatPermissions(can_send_messages=False),
                until_date=datetime.now(timezone.utc) + timedelta(seconds=60),
            )
        except Exception:
            pass
        await rich.send(
            client,
            chat_id,
            B.row(
                B.btn(
                    f"{E('wave')} Slow down — muted for 1 min",
                    data="v:noop",
                    style="danger",
                )
            ),
        )


__all__ = ["LOCK_LABELS", "locks_panel", "register"]
