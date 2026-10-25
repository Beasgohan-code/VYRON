# ---------------------------------------------------------------------------
#  VYRON — start / help / about / ping
#
#  Everything a first-time visitor sees. Every reply here is a *rich* card built
#  from `vyron.ui.blocks` (the richgram wrapper): headings, quoted intros, key/
#  value tables, collapsible setup steps, hairline dividers and coloured
#  in-message buttons — with the classic-HTML lane as an automatic fallback, so
#  an old server build still gets a complete, readable answer.
#
#  Copy rules for this file (they are the whole point of it):
#    · the first line always says what the person is looking at;
#    · no URL ever appears in text — the Mini App is a button, not a link;
#    · every claim is true right now (`streaming`, live queue, real counters);
#    · a returning listener with music playing sees the track, not the manual.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from vyron.config import settings
from vyron.core.commandlist import command_names
from vyron.core.commandlist import suggest as command_suggest
from vyron.core.journal import journal
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.utils.helpers import is_private_chat
from vyron.utils.commands import cmd, prefixes

logger = logging.getLogger(__name__)

# The picture `/start` sends. Once Telegram has it, the returned ``file_id`` is
# cached in the shared meta store so later starts upload nothing at all —
# ``_ART_VERSION`` invalidates that cache whenever the artwork changes.
START_PHOTO = Path(__file__).resolve().parents[2] / "assets" / "start.jpg"
_PHOTO_META = "start_photo_file_id"
_PHOTO_VERSION = "start_photo_version"
# 6 — the 2026 artwork: glass sculpture, gradient wordmark, no ribbons.
_ART_VERSION = "6"

# Aliases that mean "open the player", from a t.me deep link or a typed command.
_APP_WORDS = {"app", "player", "miniapp", "mini", "music", "open"}


async def _photo_source() -> tuple[object, bool]:
    """(source, cached) — a cached Telegram ``file_id`` or the brand artwork.

    Order: cached id (same artwork version) → shipped JPEG → freshly rendered
    brand art. Nothing here is required for `/start` to work: if all three are
    missing the caller falls back to the text card.
    """
    if runtime.storage is not None:
        try:
            version = str(await runtime.storage.get_meta(_PHOTO_VERSION, "") or "")
            stored = str(await runtime.storage.get_meta(_PHOTO_META, "") or "")
        except Exception:  # pragma: no cover - storage hiccups must not break /start
            version, stored = "", ""
        if stored and version == _ART_VERSION:
            return stored, True

    if START_PHOTO.is_file():
        return str(START_PHOTO), False

    try:
        from vyron.utils import brandart

        image = await asyncio.to_thread(brandart.start_image)
        if image:
            return image, False
    except Exception:  # pragma: no cover - art is optional
        logger.debug("could not render the /start artwork")
    return None, False


def _live_state(chat_id: int) -> dict | None:
    """What this chat is playing right now, if anything."""
    if runtime.player is None:
        return None
    state = runtime.player.queues.get(chat_id)
    if state is None or state.current is None:
        return None
    track = state.current
    return {
        "title": track.title,
        "artist": getattr(track, "uploader", "") or "",
        "duration": getattr(track, "duration", 0) or 0,
        "queue": len(state.queue),
        "paused": state.paused,
        "position": getattr(state, "position", 0) or 0,
    }


def _greeting() -> str:
    """One word that fits the hour on the server — never a fake local time."""
    hour = time.gmtime().tm_hour
    if hour < 5:
        return "Still up"
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    if hour < 22:
        return "Good evening"
    return "Still up"


def _engine_line() -> str:
    """The honest voice-chat state, phrased for a human."""
    if runtime.streaming_ready:
        return f"{B.pill('voice chat ready', 'ok')} · the assistant can join calls"
    if runtime.player is None:
        return (
            f"{B.pill('voice engine off', 'warn')} · no <code>STRING_SESSION</code> — "
            "<code>/song</code> and the API still send files"
        )
    return f"{B.pill('starting up', 'warn')} · the voice engine is still coming online"


async def _counters() -> dict:
    if runtime.storage is None:
        return {}
    try:
        return await runtime.storage.counters()
    except Exception:  # pragma: no cover - a counter is never worth a failure
        return {}


def _rights_from_member(member) -> dict:
    """The four permissions a music bot needs, from a ``ChatMember``.

    Pure on purpose: the interesting part of a permission check is the mapping
    (owner means everything, an admin has a privileges object, a member has
    none), and that should be testable without a Telegram client.
    """
    raw = getattr(member, "status", "")
    status = str(getattr(raw, "name", raw) or "").upper()
    owner = "OWNER" in status
    admin = owner or "ADMIN" in status
    privileges = getattr(member, "privileges", None)
    fields = {
        "voice": "can_manage_video_chats",
        "delete": "can_delete_messages",
        "invite": "can_invite_users",
        "pin": "can_pin_messages",
    }
    rights: dict[str, bool] = {}
    for key, field in fields.items():
        if not admin:
            rights[key] = False
        elif owner or privileges is None:
            rights[key] = True
        else:
            rights[key] = bool(getattr(privileges, field, False))
    return rights


async def _bot_rights(client, chat_id: int) -> dict | None:
    """What the bot may do in *chat_id*, or ``None`` when it cannot tell."""
    try:
        member = await client.get_chat_member(chat_id, "me")
    except Exception as exc:  # private chats, a probe failure, an old client
        logger.debug("could not read my rights in %s: %s", chat_id, exc)
        return None
    return _rights_from_member(member)


# Chats and people that have already said hello since this process started:
# the owner journal is a record of what changed, not a page per `/start`.
_GREETED: set[int] = set()
_GREETED_USERS: set[int] = set()


async def home_card(chat, user=None) -> str:
    """The home card, for `/start` and every "Home" button.

    One builder means a tapped button and a typed command never drift apart.
    """
    counters = await _counters()
    who = (getattr(user, "first_name", "") or "").strip() or "there"
    return cards.start_card(
        who,
        {"chats": counters.get("chats", 0), "tracks": counters.get("tracks", 0)},
        streaming=runtime.streaming_ready,
        live=_live_state(chat.id),
        greeting=_greeting(),
    )


async def group_card(client, chat, user=None) -> str:
    """The card a *group* gets: is it set up here, and what is still missing."""
    counters = await _counters()
    who = (
        (getattr(user, "first_name", "") or "").strip(),
        int(getattr(user, "id", 0) or 0),
    )
    return cards.group_start_card(
        getattr(chat, "title", "") or "this group",
        who if who[1] else "there",
        await _bot_rights(client, chat.id),
        {"chats": counters.get("chats", 0), "tracks": counters.get("tracks", 0)},
        streaming=runtime.streaming_ready,
        live=_live_state(chat.id),
    )


def register(client: Client) -> None:
    async def _send_app(message: Message) -> None:
        """Open the Mini App *inside Telegram* — never as a browser link."""
        if not keyboards.app_url():
            await rich.send(
                message._client,
                message.chat.id,
                B.head("Player", glyph="warn")
                + B.context(
                    "<b>The Mini App is not configured on this deployment.</b>\n"
                    "Set <code>WEBAPP_URL</code> to this server's public address and "
                    "restart — the button appears on the next <code>/start</code>."
                )
                + B.actions(B.row(B.btn("Reload the home card", data="v:start"))),
                reply_to=message.id,
            )
            return

        if is_private_chat(message.chat):
            await rich.send(
                message._client,
                message.chat.id,
                cards.webapp_card(settings.webapp_url or ""),
                markup_keyboard=keyboards.app_markup(with_close=True),
                reply_to=message.id,
            )
        else:
            await rich.send(
                message._client,
                message.chat.id,
                cards.webapp_group_card(settings.bot_username),
                markup_keyboard=keyboards.dm_markup(),
                reply_to=message.id,
            )

    # ── /start ─────────────────────────────────────────────────────────────
    @client.on_message(cmd(["start"]))
    async def _start(_: Client, message: Message) -> None:
        # t.me/<bot>?start=app deep-links straight into the player, so a shared
        # link lands people where the music actually is.
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip().lower() in _APP_WORDS:
            await _send_app(message)
            return

        private = is_private_chat(message.chat)
        # A group asks a different question than a person does: not "what is
        # this" but "is it set up here". Same photo, same buttons, other card.
        markup = (
            await home_card(message.chat, message.from_user)
            if private
            else await group_card(message._client, message.chat, message.from_user)
        )
        # No credential and no URL in the card: the Mini App identifies the
        # owner from Telegram's own initData, and its button is DM-only.
        photo, cached = await _photo_source()
        kwargs = {
            "chat_id": message.chat.id,
            "photo": photo,
            "markup": markup,
            "markup_keyboard": keyboards.start_panel(player=private),
        }
        if private:
            # In a private chat the card answers the command, so it stays a
            # reply to it. In a group the command itself goes: the card is the
            # message, and a "/start" sitting above it reads like a person
            # talking to themselves.
            kwargs["reply_to"] = message.id
        else:
            try:
                await message.delete()
            except Exception:  # no rights, too old, already gone
                pass
        try:
            sent = await rich.send_photo(message._client, **kwargs)
        except FloodWait as flood:
            try:
                await rich.send(client, message.chat.id, cards.rate_limit_card(getattr(flood, 'value', 5)))
            except Exception:
                pass
            # A busy group can hit the flood limit on the *photo*; waiting and
            # retrying is what turns that into a card instead of silence.
            await asyncio.sleep(float(getattr(flood, "value", 3)) + 1)
            sent = await rich.send_photo(message._client, **kwargs)
        if not private and message.chat.id not in _GREETED:
            _GREETED.add(message.chat.id)
            journal.info(
                "start",
                f"new group: {getattr(message.chat, 'title', '') or message.chat.id}",
                chat=message.chat.id,
                user=getattr(message.from_user, "id", 0),
            )
            # Mirror to LOGGER_ID (Shizu-style visibility)
            if getattr(settings, "logger_id", None):
                try:
                    title = getattr(message.chat, "title", "") or str(message.chat.id)
                    by = getattr(message.from_user, "first_name", "") or "someone"
                    await rich.send(
                        message._client,
                        settings.logger_id,
                        B.soft_header("users", "Group /start", title)
                        + B.pretty_table([
                            ("Chat", f"<code>{message.chat.id}</code>"),
                            ("Title", rich.esc(str(title)[:40])),
                            ("By", rich.esc(str(by)[:32])),
                        ])
                        + B.soft_footer("VYRON", "logger"),
                    )
                except Exception:
                    pass
        elif private:
            uid = int(getattr(message.from_user, "id", 0) or 0)
            if uid and uid not in _GREETED_USERS:
                _GREETED_USERS.add(uid)
                journal.info(
                    "start",
                    f"new listener: {getattr(message.from_user, 'first_name', '') or uid}",
                    user=uid,
                )
                if getattr(settings, "logger_id", None):
                    try:
                        name = getattr(message.from_user, "first_name", "") or str(uid)
                        un = getattr(message.from_user, "username", None)
                        await rich.send(
                            message._client,
                            settings.logger_id,
                            B.soft_header("users", "New user", name)
                            + B.pretty_table([
                                ("User", f"<code>{uid}</code>"),
                                ("Name", rich.esc(str(name)[:32])),
                                ("Username", f"@{un}" if un else "—"),
                            ])
                            + B.soft_footer("VYRON", "logger"),
                        )
                    except Exception:
                        pass
        # Remember the upload so the next /start is instant. A stale id would
        # fail later; `_photo_source` re-reads it and `/start` is idempotent.
        if not cached and sent is not None and getattr(sent, "photo", None):
            if runtime.storage is not None:
                try:
                    await runtime.storage.set_meta(_PHOTO_META, sent.photo.file_id)
                    await runtime.storage.set_meta(_PHOTO_VERSION, _ART_VERSION)
                except Exception:  # pragma: no cover
                    logger.debug("could not cache the /start photo id")
        if runtime.storage:
            await runtime.storage.bump("starts")
            if message.chat.type.name in {"GROUP", "SUPERGROUP"}:
                await runtime.storage.bump("chats")

    # ── /help ──────────────────────────────────────────────────────────────
    @client.on_message(cmd("help"))
    async def _help(_: Client, message: Message) -> None:
        await rich.send(
            message._client,
            message.chat.id,
            cards.help_card("main"),
            markup_keyboard=keyboards.help_nav("main"),
            reply_to=message.id,
        )

    # ── /about ─────────────────────────────────────────────────────────────
    @client.on_message(cmd(["about", "repo"]))
    async def _about(_: Client, message: Message) -> None:
        await rich.send(
            message._client,
            message.chat.id,
            cards.about_card(),
            markup_keyboard=keyboards.back_close("v:help:main"),
            reply_to=message.id,
        )

    # ── /app · /player ─────────────────────────────────────────────────────
    @client.on_message(cmd(["app", "player"]))
    async def _webapp(_: Client, message: Message) -> None:
        await _send_app(message)

    # ── /ping ──────────────────────────────────────────────────────────────
    @client.on_message(cmd("ping"))
    async def _ping(_: Client, message: Message) -> None:
        from vyron.utils import sysinfo

        started = time.perf_counter()
        sent = await rich.send(
            message._client,
            message.chat.id,
            B.soft_header("bolt", "Ping", "Measuring round trip…"),
        )
        latency = (time.perf_counter() - started) * 1000
        snap = sysinfo.snapshot()
        if sent:
            await rich.edit(
                message._client,
                message.chat.id,
                sent.id,
                cards.ping_card(latency, runtime.uptime, system=snap),
            )

    # ── unknown commands get a hint, not silence ───────────────────────────
    known = frozenset(command_names())
    # Every configured prefix, regex-escaped (`?`, `$` and `&` are not literal
    # in a character class without it).
    typed_prefix = re.compile(
        r"^(?P<prefix>[" + re.escape("".join(p for p in prefixes() if p)) + r"])"
        r"(?P<name>[A-Za-z0-9_]+)"
    )

    @client.on_message(filters.private & filters.regex(r"^\S"), group=1)
    async def _unknown(_: Client, message: Message) -> None:
        """Runs in a later group, so it only sees commands nobody claimed.

        The alias prune left a lot of muscle memory pointing at names that no
        longer exist (`/pl`, `/favs`, `/vskip`); instead of dropping those on
        the floor we answer with the closest live command — in the prefix the
        person actually typed.

        Non-slash prefixes stay quiet unless they are a near-miss for a real
        command: `.` and `?` are ordinary punctuation, and nobody wants the bot
        correcting their prose.
        """
        match = typed_prefix.match((message.text or "").strip())
        if not match:
            return
        prefix, name = match.group("prefix"), match.group("name").lower()
        if name in known:
            return  # a real command: its handler already ran in group 0
        close = command_suggest(name)
        if not close and prefix != "/":
            return  # punctuation, not an attempt at a command
        body = B.context(
            f"<b>{prefix}{name}</b> is not a command — nothing was sent."
            + (f"\nThe closest one is <code>{prefix}{close[0]}</code>." if close else "")
        )
        await rich.send(
            message._client,
            message.chat.id,
            B.head("Not a command", glyph="info") + body
            + B.actions(
                B.row(
                    B.btn("All commands", data="v:help:main", style="primary"),
                    B.btn("Home", data="v:start"),
                )
            ),
            reply_to=message.id,
        )

    # ── /id ────────────────────────────────────────────────────────────────
    @client.on_message(cmd(["id"]))
    async def _id(_: Client, message: Message) -> None:
        chat = message.chat
        rows = [
            ("chat", "This chat", f"<code>{chat.id}</code>"),
            (
                "user",
                "You",
                f"<code>{message.from_user.id if message.from_user else 0}</code>",
            ),
        ]
        replied = message.reply_to_message
        if replied and replied.from_user:
            rows.append(("users", "Replied to", f"<code>{replied.from_user.id}</code>"))
        if replied and replied.audio:
            rows.append(("song", "Audio file", f"<code>{replied.audio.file_id[:42]}…</code>"))
        if getattr(chat, "username", None):
            rows.append(("link", "Username", f"@{chat.username}"))
        await rich.send(
            message._client,
            chat.id,
            B.head("Identifiers", glyph="id")
            + B.context("Copyable ids — useful in a bug report or a whitelist.")
            + B.stat_pairs(rows)
            + B.actions(
                B.row(B.btn("Home", data="v:start", style="primary")),
            ),
            reply_to=message.id,
        )


__all__ = ["home_card", "register"]
