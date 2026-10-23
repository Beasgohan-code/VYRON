# ---------------------------------------------------------------------------
#  VYRON — handler helpers (auth, parsing, replies)
# ---------------------------------------------------------------------------
from __future__ import annotations

import re
import time
from typing import Iterable

from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.errors import RPCError
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message, User

from vyron.config import settings
from vyron.core import acl
from vyron.core.queue import Track

_ADMIN_STATES = {
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.OWNER,
}
_BOT_COMMAND_RE = re.compile(r"^/\w+(?:@\w+)?\s*", re.I)


# ── query parsing ───────────────────────────────────────────────────────────
def command_args(message: Message) -> str:
    """Everything after ``/command[@bot]``."""
    text = message.text or message.caption or ""
    return _BOT_COMMAND_RE.sub("", text).strip()


def first_word(text: str) -> str:
    return (text or "").split()[0] if (text or "").split() else ""


def parse_seek(value: str, current: float = 0, total: int = 0) -> int:
    """Parse ``90``, ``1:30``, ``+15``, ``-10`` into an absolute offset."""
    raw = (value or "").strip()
    if not raw:
        return int(current)
    relative = raw[0] in "+-"
    sign = -1 if raw.startswith("-") else 1
    body = raw.lstrip("+-")
    if ":" in body:
        parts = [int(p) for p in body.split(":") if p.strip().isdigit()]
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
    else:
        try:
            seconds = int(float(body))
        except ValueError:
            return int(current)
    target = current + sign * seconds if relative else seconds
    target = max(0, int(target))
    if total:
        target = min(target, max(0, total - 1))
    return target


def chunk(items: list, size: int) -> Iterable[list]:
    for index in range(0, len(items), max(1, size)):
        yield items[index : index + size]


# ── identity ────────────────────────────────────────────────────────────────
def display_name(user: User | None) -> str:
    if not user:
        return "Someone"
    name = " ".join(filter(None, [user.first_name, user.last_name])).strip()
    return name or (user.username or "Someone")


def mention(user: User | None) -> str:
    if not user:
        return "Someone"
    return user.mention


def is_private_chat(chat) -> bool:
    """True for a one-to-one chat — the only place secrets may be posted.

    ``pyrogram``/``kurigram`` chat types are enums, not strings, so
    ``chat.type == "private"`` is always False. Compare the enum name instead,
    and fall back to the (positive) DM chat id when a stub chat is passed.
    """
    if chat is None:
        return False
    name = str(getattr(getattr(chat, "type", None), "name", "") or "").upper()
    if name:
        return name == "PRIVATE"
    try:
        return int(getattr(chat, "id", 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def is_owner(user_id: int) -> bool:
    """Owner, SUDO_USERS, or someone granted trust with /addsudo."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    return uid in settings.owners or acl.is_sudo(uid)


_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str | None) -> int | None:
    """``10m`` → 600 · ``2h`` → 7200 · ``45`` → 45 s · ``off`` → 0.

    Returns ``None`` when the string is not a duration, so callers can tell
    "no argument" apart from "invalid argument".
    """
    text = (text or "").strip().lower()
    if not text:
        return None
    if text in {"off", "0", "none", "disable"}:
        return 0
    suffix = text[-1]
    if suffix in _DURATION_UNITS and text[:-1].isdigit():
        return int(text[:-1]) * _DURATION_UNITS[suffix]
    if text.isdigit():
        return int(text)
    return None


async def is_chat_admin(client, chat_id: int, user_id: int) -> bool:
    if is_owner(user_id):
        return True
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in _ADMIN_STATES
    except RPCError:
        return False
    except Exception:
        return False


async def is_dj(chat_id: int, user_id: int) -> bool:
    """Is this user on the chat's DJ list (and does the chat use one)?"""
    from vyron.core import chatcfg

    try:
        lineup = await chatcfg.get(int(chat_id), "dj", []) or []
    except Exception:
        return False
    return any(str(user_id) == str(entry) for entry in lineup)


async def can_control(client, message: Message) -> bool:
    """Playback rights: owners always, DJs by invitation, admins, and DMs.

    A chat that sets a DJ lineup hands the controls to those people *and*
    keeps admins able to fix things — the lineup never locks an admin out.
    """
    user = message.from_user
    if not user:
        return False
    if is_owner(user.id):
        return True
    if message.chat.type == ChatType.PRIVATE:
        return True
    if await is_dj(message.chat.id, user.id):
        return True
    return await is_chat_admin(client, message.chat.id, user.id)


def chat_id_of(source: Message | CallbackQuery) -> int:
    if isinstance(source, CallbackQuery):
        return int(source.message.chat.id) if source.message else 0
    return int(source.chat.id)


def user_of(source: Message | CallbackQuery) -> User | None:
    return source.from_user


async def answer(callback: CallbackQuery, text: str = "", *, show_alert: bool = False) -> None:
    try:
        await callback.answer(text[:190], show_alert=show_alert)
    except Exception:
        pass


async def reply_card(message: Message, markup: str, *, keyboard: InlineKeyboardMarkup | None = None,
                     reply_to: Message | None = None):
    from vyron.ui import rich

    kwargs = {}
    if keyboard is not None:
        kwargs["markup_keyboard"] = keyboard
    if reply_to is not None:
        kwargs["reply_to"] = reply_to.id
    sent = await rich.send(message._client, message.chat.id, markup, **kwargs)
    if sent:
        try:
            message.continue_propagation = False
        except Exception:
            pass
    return sent


# ── media → track ───────────────────────────────────────────────────────────
def track_from_message(message: Message) -> Track | None:
    """Build a Track from a replied-to audio / voice / video file."""
    target = message.reply_to_message or message
    media = target.audio or target.voice or target.video or target.document
    if not media:
        return None
    title = getattr(media, "title", None) or getattr(media, "file_name", None) or "Telegram audio"
    performer = getattr(media, "performer", None) or ""
    file_id = getattr(media, "file_id", "") or ""
    duration = int(getattr(media, "duration", 0) or 0)
    return Track(
        id=f"tg{abs(hash(file_id)) % 10**12}",
        title=str(title),
        duration=duration,
        url=file_id,
        uploader=str(performer),
        source="telegram",
        requested_by=target.from_user.id if target.from_user else 0,
        requested_name=display_name(target.from_user) if target.from_user else "",
    )


class Cooldown:
    """Tiny per-user rate limiter for commands."""

    def __init__(self, seconds: float = 2.0) -> None:
        self.seconds = seconds
        self._seen: dict[int, float] = {}

    def check(self, user_id: int) -> bool:
        last = self._seen.get(int(user_id), 0.0)
        stamp = time.monotonic()
        if stamp - last < self.seconds:
            return False
        self._seen[int(user_id)] = stamp
        return True


__all__ = [
    "Cooldown",
    "answer",
    "can_control",
    "chat_id_of",
    "chunk",
    "command_args",
    "display_name",
    "first_word",
    "is_chat_admin",
    "is_dj",
    "is_owner",
    "mention",
    "parse_seek",
    "reply_card",
    "track_from_message",
    "user_of",
]
