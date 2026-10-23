# ---------------------------------------------------------------------------
#  VYRON — UI style switch + rich-lane self check
#
#  Two looks are shipped, and the owner picks which one this deployment speaks:
#
#    rich     the Bot-API rich cards (headings, tables, collapsible sections,
#             <tg-button> rows) — the default;
#    classic  the older plain-HTML cards with an inline keyboard. Same content,
#             same buttons, no rich blocks.
#
#  `/uistyle` flips it live and remembers the choice in storage, so a restart
#  does not silently put the other UI back. `/uicheck` renders the *start* card
#  through whichever lane is active and reports what actually happened — that is
#  the one card every user sees, so it is the right canary.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.types import Message

from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.ui.theme import E
from vyron.utils.helpers import is_owner

logger = logging.getLogger(__name__)

META_KEY = "ui_style"
STYLES = {
    "rich": "Rich cards",
    "classic": "Classic (old UI)",
}
ALIASES = {"old": "classic", "html": "classic", "rich": "rich", "new": "rich"}


def current() -> str:
    return "rich" if settings.rich_messages else "classic"


async def load() -> str:
    """Apply the style saved by `/uistyle`, if the owner ever set one."""
    if not runtime.storage:
        return current()
    try:
        saved = str(await runtime.storage.get_meta(META_KEY, "") or "").lower()
    except Exception:  # pragma: no cover - storage is best effort at boot
        return current()
    if saved in STYLES:
        settings.rich_messages = saved == "rich"
    return current()


async def set_style(style: str) -> str:
    style = ALIASES.get(style, style)
    if style not in STYLES:
        return current()
    settings.rich_messages = style == "rich"
    if runtime.storage:
        try:
            await runtime.storage.set_meta(META_KEY, style)
        except Exception:  # pragma: no cover - a failed save must not break
            logger.debug("could not persist the ui style")
    return style


def card() -> str:
    active = current()
    rows = [
        (f"{E('interface')} style", f"<b>{STYLES[active]}</b>"),
        (f"{E('code')} rich lane", "<b>available</b>" if rich.RICH_AVAILABLE else "unavailable"),
        (f"{E('spark')} premium emoji", "<b>on</b>" if rich.RICH_AVAILABLE else "plain"),
    ]
    body = (
        B.heading(f"{E('interface')} interface", 2)
        + B.kv(rows)
        + B.note(
            "<b>Rich cards</b> add headings, tables and in-message buttons.\n"
            "<b>Classic</b> is the older plain-HTML look — every command and button "
            "still works."
        )
        + B.divider()
        + B.row(
            B.btn(
                f"{E('check') if active == 'rich' else E('code')} Rich cards",
                data="v:ui:rich",
                style="primary" if active == "rich" else None,
            ),
            B.btn(
                f"{E('check') if active == 'classic' else E('code')} Classic",
                data="v:ui:classic",
                style="primary" if active == "classic" else None,
            ),
        )
    )
    return body


def probe() -> dict:
    """Check the `/start` card in both lanes without talking to Telegram.

    `/start` is the one card every single user sees, so it is the right canary:
    if its markup cannot be down-converted, every other card is broken too.
    """
    markup = cards.start_card(
        "there",
        {"chats": 0, "tracks": 0},
        streaming=bool(getattr(runtime, "streaming_ready", False)),
    )
    plain = rich.to_html(markup)
    return {
        "style": current(),
        "rich_api": bool(rich.RICH_AVAILABLE),
        "rich_chars": len(markup),
        "classic_chars": len(plain),
        "buttons": markup.count("<tg-button"),
        "ok": bool(plain.strip()),
    }


async def check(client: Client, chat_id: int) -> str:
    """Render the `/start` card for real and report what the lane did."""
    markup = cards.start_card(
        "there",
        {"chats": 0, "tracks": 0},
        streaming=bool(getattr(runtime, "streaming_ready", False)),
    )
    plain = rich.to_html(markup)
    rows = [
        (f"{E('interface')} style", f"<b>{STYLES[current()]}</b>"),
        (
            f"{E('code')} rich api",
            "<b>yes</b>" if rich.RICH_AVAILABLE else "no — classic only",
        ),
        (f"{E('spark')} card size", f"<b>{len(markup)}</b> chars"),
        (f"{E('download')} classic copy", f"<b>{len(plain)}</b> chars"),
    ]
    delivered = False
    try:
        message = await rich.send(client, chat_id, markup)
        delivered = message is not None
    except Exception as exc:  # pragma: no cover - that is what this checks
        logger.warning("ui check send failed: %s", exc)
    rows.append(
        (
            f"{E('rocket')} delivery",
            "<b>ok</b>" if delivered else "<b>failed</b>",
        )
    )
    return (
        B.heading(f"{E('shield')} ui check", 2)
        + B.kv(rows)
        + B.note(
            f"{E('check')} The card above was sent through the "
            f"<b>{STYLES[current()]}</b> lane."
            if delivered
            else f"{E('warn')} Sending failed — fall back with <code>/uistyle classic</code>."
        )
    )


def register(client: Client) -> None:
    from pyrogram import filters

    async def _owner_only(message: Message) -> bool:
        user = message.from_user
        if user and is_owner(user.id):
            return True
        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('shield')} Owner only — the interface is a deployment-wide choice."),
            reply_to=message.id,
        )
        return False

    @client.on_message(filters.command(["uistyle", "uimode", "ui"]))
    async def _uistyle(_: Client, message: Message) -> None:
        if not await _owner_only(message):
            return
        parts = (message.text or "").split(maxsplit=1)
        argument = parts[1].strip().lower() if len(parts) > 1 else ""
        if argument:
            chosen = await set_style(argument)
            if chosen not in STYLES or ALIASES.get(argument, argument) not in STYLES:
                await rich.send(
                    client,
                    message.chat.id,
                    B.note(
                        f"{E('warn')} Unknown style — use <code>rich</code> or <code>classic</code>."
                    ),
                    reply_to=message.id,
                )
                return
            await rich.send(
                client,
                message.chat.id,
                B.heading(f"{E('check')} interface switched", 3)
                + B.note(f"Now speaking <b>{STYLES[chosen]}</b>. It survives restarts."),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            card(),
            markup_keyboard=keyboards.back_close("v:help:main"),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["uicheck"]))
    async def _uicheck(_: Client, message: Message) -> None:
        if not await _owner_only(message):
            return
        await rich.send(
            client,
            message.chat.id,
            await check(client, message.chat.id),
            reply_to=message.id,
        )


__all__ = ["STYLES", "card", "check", "current", "load", "probe", "register", "set_style"]
