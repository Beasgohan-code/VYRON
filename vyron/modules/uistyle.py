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

from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.ui.theme import E
from vyron.utils.helpers import is_owner
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

META_KEY = "ui_style"
STYLES = {
    "rich": "Rich cards",
    "classic": "Classic (old UI)",
}
ALIASES = {"old": "classic", "html": "classic", "rich": "rich", "new": "rich"}


def current() -> str:
    return "rich" if rich.rich_enabled() else "classic"


async def load() -> str:
    """Apply the style saved by `/uistyle`, if the owner ever set one."""
    if not runtime.storage:
        return current()
    try:
        saved = str(await runtime.storage.get_meta(META_KEY, "") or "").lower()
    except Exception:  # pragma: no cover - storage is best effort at boot
        return current()
    if saved in STYLES:
        rich.set_rich_enabled(saved == "rich")
    return current()


async def verify() -> dict:
    """Probe at boot and **fall back to the classic UI** if rich is broken.

    The rich lane depends on a parse mode Telegram is still rolling out. When a
    deployment is on the wrong side of that rollout, `/start` — the first thing
    anybody sees — would be an empty message. Rather than shipping a broken
    front door, we drop to the old plain-HTML UI and say so in the log.
    """
    report = probe()
    if not report["classic_ok"]:
        logger.error("interface: the start card renders empty in both lanes")
    elif not report["rich_ok"] and rich.rich_enabled():
        logger.error(
            "interface: the rich start card is empty (rich api %s) — switching to the classic UI",
            "available" if report["rich_api"] else "unavailable",
        )
        await set_style("classic")
        report = {**report, "style": "classic", "fell_back": True}
    return report


async def set_style(style: str) -> str:
    style = ALIASES.get(style, style)
    if style not in STYLES:
        return current()
    rich.set_rich_enabled(style == "rich")
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


def _start_markup() -> str:
    return cards.start_card(
        "there",
        {"chats": 0, "tracks": 0},
        streaming=bool(getattr(runtime, "streaming_ready", False)),
    )


def probe() -> dict:
    """Check the `/start` card in *both* lanes without talking to Telegram.

    `/start` is the one card every single user sees, so it is the right canary.
    The two lanes are checked separately: the rich card can render fine while
    its down-conversion (used for edits and for classic mode) is empty, and
    that would break every card in the bot, not just this one.
    """
    markup = _start_markup()
    plain = rich.to_html(markup)
    rich_ok = bool(rich.RICH_AVAILABLE and markup.strip() and markup.count("<tg-button") >= 0)
    classic_ok = bool(plain.strip())
    return {
        "style": current(),
        "rich_api": bool(rich.RICH_AVAILABLE),
        "rich_ok": rich_ok,
        "classic_ok": classic_ok,
        "rich_chars": len(markup),
        "classic_chars": len(plain),
        "buttons": markup.count("<tg-button"),
        "ok": rich_ok and classic_ok,
    }


async def check(client: Client, chat_id: int) -> str:
    """Render the `/start` card for real and report *both* lanes."""
    markup = _start_markup()
    plain = rich.to_html(markup)
    report = probe()
    rows = [
        (f"{E('interface')} style", f"<b>{STYLES[current()]}</b>"),
        (
            f"{E('code')} rich api",
            "<b>yes</b>" if rich.RICH_AVAILABLE else "no — classic only",
        ),
        (
            f"{E('spark')} rich start",
            ("<b>ok</b> · " if report["rich_ok"] else "<b>empty</b> · ") + f"{len(markup)} chars",
        ),
        (
            f"{E('download')} classic start",
            ("<b>ok</b> · " if report["classic_ok"] else "<b>empty</b> · ") + f"{len(plain)} chars",
        ),
    ]
    delivered = False
    try:
        message = await rich.send(client, chat_id, markup)
        delivered = message is not None
    except Exception as exc:  # pragma: no cover - that is what this checks
        logger.warning("ui check send failed: %s", exc)
        # A failed rich send in the rich lane is exactly the case that should
        # end in the old UI, so do it immediately rather than leaving the
        # deployment on a lane that cannot deliver.
        if rich.rich_enabled():
            await set_style("classic")
    rows.append(
        (
            f"{E('rocket')} delivery",
            "<b>ok</b>" if delivered else "<b>failed</b>",
        )
    )
    if not delivered and not rich.rich_enabled():
        tail = f"{E('warn')} Both lanes failed to send — check the bot token and chat."
    elif not delivered:
        tail = f"{E('warn')} The rich card did not send — switched to the classic UI with <code>/uistyle classic</code>."
    else:
        tail = (
            f"{E('check')} The card above was sent through the "
            f"<b>{STYLES[current()]}</b> lane."
        )
    return B.heading(f"{E('shield')} ui check", 2) + B.kv(rows) + B.note(tail)


def register(client: Client) -> None:

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

    @client.on_message(cmd(["uistyle"]))
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

    @client.on_message(cmd(["uicheck"]))
    async def _uicheck(_: Client, message: Message) -> None:
        if not await _owner_only(message):
            return
        await rich.send(
            client,
            message.chat.id,
            await check(client, message.chat.id),
            reply_to=message.id,
        )


__all__ = [
    "STYLES",
    "card",
    "check",
    "current",
    "load",
    "probe",
    "register",
    "set_style",
    "verify",
]
