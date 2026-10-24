# ---------------------------------------------------------------------------
#  VYRON — owner journal commands
#
#      /logs                  newest events
#      /logs errors           warnings + errors only
#      /logs warn             warnings and errors
#      /logs info             everything except debug
#      /logs <scope>           e.g. /logs player, /logs database
#      /logs export           sends the raw .jsonl so you can grep offline
#      /logs clear            empties the ring buffer (confirm button)
#
#  Owner-only in private chats: the journal can contain chat ids and track
#  metadata, so it never appears in a group.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, Message

from vyron.core import logsink
from vyron.runtime import runtime
from vyron.core.journal import journal
from vyron.ui import blocks as B
from vyron.ui import cards, rich
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import is_owner
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

_ALIASES = {
    "all": "all",
    "everything": "all",
    "info": "info",
    "ok": "info",
    "warn": "warn",
    "warning": "warn",
    "warnings": "warn",
    "error": "error",
    "errors": "error",
    "err": "error",
}

SCOPES = (
    "boot", "player", "voice", "queue", "search", "download", "database",
    "watchdog", "webapp", "stream", "config", "command", "journal",
)


def render(level: str = "all", scope: str = "") -> tuple[str, object]:
    """Build the journal card + keyboard for a filter."""
    from vyron.ui import blocks as B

    events = journal.events(
        limit=40,
        levels={"error": ["error"], "warn": ["warn", "error"], "info": ["info", "ok", "warn", "error"]}.get(level),
        scope=scope or None,
    )
    markup = cards.logs_card(events, journal.stats(), level=level, scope=scope)
    keyboard = B.row(
        B.btn("All", data="v:logs:all", style="primary" if level == "all" else None),
        B.btn("Errors", data="v:logs:error", style="primary" if level == "error" else None),
        B.btn("Refresh", data=f"v:logs:{level}", style="success"),
    )
    return markup, keyboard


async def _send_journal(client: Client, message: Message, level: str = "all", scope: str = "") -> None:
    markup, keyboard = render(level, scope)
    await rich.send(client, message.chat.id, markup, markup_keyboard=keyboard, reply_to=message.id)


async def _is_owner_message(message: Message) -> bool:
    return bool(message.from_user and is_owner(message.from_user.id))


def _logger_kb():
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ On", callback_data="v:log:on"),
                InlineKeyboardButton("✖️ Off", callback_data="v:log:off"),
            ]
        ]
    )


def logger_card() -> str:
    """Status of the live log channel (one card, one toggle)."""
    from vyron.config import settings

    on = logsink.is_enabled()
    channel = settings.logger_id
    body = (
        B.heading(f"{E('live')} log channel", 2)
        + B.kv(
            [
                ("state", f"<b>{'on' if on else 'off'}</b>"),
                ("channel", f"<code>{channel}</code>" if channel else "<i>LOGGER_ID is not set</i>"),
                ("mirrors", "warnings and errors"),
            ]
        )
        + B.note(
            "With this on, every warning and error in the journal is also posted "
            "to the channel, so you see trouble without opening /logs."
            if channel
            else "Set <code>LOGGER_ID</code> to a channel the bot can post in, then "
            "<code>/logger on</code>."
        )
        + B.row(
            B.btn(f"{E('check')} Turn on", data="v:log:on", style="success"),
            B.btn(f"{E('close')} Turn off", data="v:log:off", style="danger"),
        )
        + B.footer("/logger · owner only · rate limited to 20 events a minute")
    )
    return body


def register(client: Client) -> None:
    @client.on_message(cmd("logger") & owner)
    async def _logger(_: Client, message: Message) -> None:
        arg = (message.command[1].lower() if len(message.command) > 1 else "").strip()
        if arg in {"on", "enable", "start"}:
            state = await logsink.set_enabled(runtime.storage, True)
            await rich.send(
                client,
                message.chat.id,
                cards.ok_card(
                    f"<b>Log channel on</b>\n<blockquote>Warnings and errors are mirrored "
                    f"to <code>{runtime.settings.logger_id}</code>.</blockquote>"
                    if state
                    else "<b>Nothing to post to</b>\n<blockquote>Set <code>LOGGER_ID</code> first.</blockquote>"
                ),
                reply_to=message.id,
            )
            return
        if arg in {"off", "disable", "stop"}:
            await logsink.set_enabled(runtime.storage, False)
            await rich.send(
                client,
                message.chat.id,
                cards.ok_card("<b>Log channel off</b> — the journal keeps recording."),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            logger_card(),
            markup_keyboard=_logger_kb(),
            reply_to=message.id,
        )

    @client.on_message(cmd("logs") & owner)
    async def _logs(_: Client, message: Message) -> None:
        if message.chat.type != ChatType.PRIVATE:
            await rich.send(
                client,
                message.chat.id,
                rich.blockquote("The journal is owner-only and reads best in DM — open a private chat with me."),
                reply_to=message.id,
            )
            return

        args = [part.lower() for part in (message.text or "").split()[1:]]
        if args and args[0] in {"export", "dump"}:
            path = journal.export()
            if path is None:
                await rich.send(client, message.chat.id, cards.ok_card("Nothing to export yet."), reply_to=message.id)
                return
            try:
                await client.send_document(
                    message.chat.id,
                    str(path),
                    caption=f"VYRON journal · {journal.stats().get('buffered', 0)} events",
                )
            except Exception as exc:  # pragma: no cover - transport
                logger.warning("journal export failed: %s", exc)
                journal.error("journal", "export failed", exc)
                await rich.send(client, message.chat.id, cards.ok_card("Could not send the file."), reply_to=message.id)
            return

        if args and args[0] in {"clear", "reset"}:
            removed = journal.clear(reason="by the owner")
            await rich.send(
                client,
                message.chat.id,
                cards.ok_card(f"Cleared **{removed}** events. New activity is already being recorded."),
                reply_to=message.id,
            )
            return

        level, scope = "all", ""
        for part in args:
            if part in _ALIASES:
                level = _ALIASES[part]
            elif part in SCOPES:
                scope = part
        await _send_journal(client, message, level, scope)

    @client.on_callback_query(filters.regex(r"^v:logs:"))
    async def _logs_button(_: Client, cq: CallbackQuery) -> None:
        if cq.from_user is None or not is_owner(cq.from_user.id):
            await cq.answer("Owner only", show_alert=True)
            return
        action = (cq.data or "").split(":")[2] if len((cq.data or "").split(":")) > 2 else "all"
        message = cq.message
        if message is None:
            return
        if action == "export":
            path = journal.export()
            await cq.answer("Exported" if path else "Nothing to export", show_alert=False)
            if path is not None:
                try:
                    await client.send_document(message.chat.id, str(path), caption="VYRON journal")
                except Exception:
                    pass
            return
        if action == "clear":
            journal.clear()
            await cq.answer("Journal cleared", show_alert=False)
            action = "all"
        markup, keyboard = render(action if action in _ALIASES else "all")
        await rich.edit(client, message.chat.id, message.id, markup, markup_keyboard=keyboard)
        await cq.answer()


__all__ = ["SCOPES", "register", "render"]
