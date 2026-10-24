# ---------------------------------------------------------------------------
#  VYRON — start / help / about / ping
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.config import settings
from vyron.core.commandlist import command_names
from vyron.core.commandlist import suggest as command_suggest
from vyron.runtime import runtime
from vyron.ui import cards, keyboards, rich
from vyron.ui.theme import E
from vyron.utils.helpers import is_private_chat
from vyron.utils.commands import cmd, prefixes

logger = logging.getLogger(__name__)

# The picture `/start` sends. Once Telegram has it, the returned ``file_id`` is
# cached in the shared meta store so later starts upload nothing at all —
# ``_ART_VERSION`` invalidates that cache whenever the artwork changes.
START_PHOTO = Path(__file__).resolve().parents[2] / "assets" / "start.jpg"
_PHOTO_META = "start_photo_file_id"
_PHOTO_VERSION = "start_photo_version"
_ART_VERSION = "5"  # classic banner, ribbons fade out (2026-10-23)


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


def register(client: Client) -> None:
    async def _send_app(message: Message) -> None:
        """Open the Mini App *inside Telegram* — never as a browser link."""
        if not keyboards.app_url():
            await rich.send(
                message._client,
                message.chat.id,
                cards.warn_card(
                    "<b>Web app is not configured</b>\n"
                    "<blockquote>Set <code>WEBAPP_URL</code> to the public URL of this "
                    "deployment, then restart.</blockquote>"
                ),
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

    @client.on_message(cmd(["start"]))
    async def _start(_: Client, message: Message) -> None:
        # t.me/<bot>?start=app deep-links straight into the player, so a shared
        # link lands people where the music actually is.
        payload = (message.text or "").split(maxsplit=1)
        if len(payload) > 1 and payload[1].strip().lower() in {"app", "player", "miniapp", "music"}:
            await _send_app(message)
            return

        stats = await runtime.storage.counters() if runtime.storage else {}
        name = (message.from_user.first_name if message.from_user else "there") or "there"

        # A returning user in an active chat wants the track, not the manual.
        live = None
        if runtime.player:
            state = runtime.player.queues.get(message.chat.id)
            if state is not None and state.current is not None:
                track = state.current
                live = {
                    "title": track.title,
                    "artist": getattr(track, "uploader", "") or "",
                    "duration": getattr(track, "duration", 0) or 0,
                    "queue": len(state.queue),
                    "paused": state.paused,
                }

        markup = cards.start_card(
            name,
            {"chats": stats.get("chats", 0), "tracks": stats.get("tracks", 0)},
            streaming=runtime.streaming_ready,
            live=live,
        )
        # No credential and no URL in the card: the Mini App identifies the
        # owner from Telegram's own initData, and its button is DM-only.
        photo, cached = await _photo_source()
        sent = await rich.send_photo(
            message._client,
            message.chat.id,
            photo,
            markup,
            markup_keyboard=keyboards.start_panel(player=is_private_chat(message.chat)),
            reply_to=message.id,
        )
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

    @client.on_message(cmd("help"))
    async def _help(_: Client, message: Message) -> None:
        await rich.send(
            message._client,
            message.chat.id,
            cards.help_card("main"),
            markup_keyboard=keyboards.help_nav("main"),
            reply_to=message.id,
        )

    @client.on_message(cmd(["about", "repo"]))
    async def _about(_: Client, message: Message) -> None:
        await rich.send(
            message._client,
            message.chat.id,
            cards.about_card(),
            markup_keyboard=keyboards.back_close("v:help:main"),
            reply_to=message.id,
        )

    @client.on_message(cmd(["app", "player"]))
    async def _webapp(_: Client, message: Message) -> None:
        await _send_app(message)

    @client.on_message(cmd("ping"))
    async def _ping(_: Client, message: Message) -> None:
        started = time.perf_counter()
        sent = await rich.send(message._client, message.chat.id, cards.ok_card("<b>Measuring…</b>"))
        latency = (time.perf_counter() - started) * 1000
        if sent:
            await rich.edit(
                message._client,
                message.chat.id,
                sent.id,
                cards.ping_card(latency, runtime.uptime),
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
        hint = f"<b>{prefix}{name}</b> isn't a command."
        if close:
            hint += f" Did you mean <code>{prefix}{close[0]}</code>?"
        hint += "\n<blockquote>/help lists everything the bot can do.</blockquote>"
        await rich.send(message._client, message.chat.id, hint, reply_to=message.id)

    @client.on_message(cmd(["id"]))
    async def _id(_: Client, message: Message) -> None:
        chat = message.chat
        lines = [
            f"{E('chat')} <b>Chat</b> <code>{chat.id}</code>",
            f"{E('user')} <b>You</b> <code>{message.from_user.id if message.from_user else 0}</code>",
        ]
        if message.reply_to_message and message.reply_to_message.from_user:
            lines.append(f"{E('users')} <b>Replied</b> <code>{message.reply_to_message.from_user.id}</code>")
        if message.reply_to_message and message.reply_to_message.audio:
            lines.append(f"{E('song')} <b>File</b> <code>{message.reply_to_message.audio.file_id[:42]}…</code>")
        await rich.send(message._client, chat.id, "\n".join(lines), reply_to=message.id)



__all__ = ["register"]
