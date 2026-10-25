# ---------------------------------------------------------------------------
#  VYRON — /language
#
#  One card, one tap. The choice is per chat (a group can be Malayalam while
#  the owner's DM stays English) and lives in the chat config, so it survives
#  restarts. Adding a language is a JSON file — see vyron/core/i18n.py.
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client
from pyrogram.types import Message

from vyron.core import chatcfg, i18n
from vyron.ui import blocks as B
from vyron.ui import cards, rich
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, is_chat_admin, is_owner, is_private_chat
from vyron.utils.commands import cmd


def language_card(current: str, *, text_key: str = "lang.note") -> str:
    """The picker: what is on, what is available, how to change it."""
    catalog = i18n.catalog(current)
    active = i18n.resolve(current)
    coverage = i18n.coverage()
    rows = [
        (
            f"{'✅' if code == active else '▫️'} <b>{name}</b>",
            f"<code>{code}</code>"
            + ("" if coverage.get(code, 100) >= 100 else f" · {coverage.get(code)}% translated"),
        )
        for code, name in i18n.available().items()
    ]
    return (
        B.banner(catalog.t('lang.title'), glyph="globe")
        + B.note(catalog.t(text_key))
        + B.table(None, rows, border=0)
        + B.note(
            f"{E('check')} <b>{catalog.t('lang.current')}</b> — {i18n.name(active)}"
        )
        + B.row(*language_buttons(active))
        + B.footer(
            "admins choose in groups · your DM keeps its own · "
            "any missing string falls back to English"
        )
    )


def language_buttons(current: str) -> list:
    active = i18n.resolve(current)
    return [
        B.btn(
            f"{'✅' if code == active else '▫️'} {name}",
            data=f"v:lang:{code}",
            style="success" if code == active else None,
        )
        for code, name in i18n.available().items()
    ]


def keyboard(current: str):
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    active = i18n.resolve(current)
    buttons = [
        InlineKeyboardButton(
            f"{'✅' if code == active else ''} {name}".strip(),
            callback_data=f"v:lang:{code}",
        )
        for code, name in i18n.available().items()
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("◀️ Close", callback_data="v:close")])
    return InlineKeyboardMarkup(rows)


async def can_change(client: Client, message: Message) -> bool:
    user = message.from_user
    if user is None:
        return False
    if is_owner(user.id) or is_private_chat(message.chat):
        return True
    return await is_chat_admin(client, message.chat.id, user.id)


def register(client: Client) -> None:
    @client.on_message(cmd(["language", "lang", "setlang"]))
    async def _language(_: Client, message: Message) -> None:
        current = str(await chatcfg.get(message.chat.id, "lang", "") or "")
        # `/setlang ml` is the form people arriving from other bots type. It is
        # the same command as `/language`, with the tap already made — so the
        # picker is skipped instead of asking them to confirm what they said.
        code = command_args(message).strip().lower()
        saved = False
        if code and code in i18n.available():
            if not await can_change(client, message):
                await rich.send(
                    client,
                    message.chat.id,
                    cards.locked_card(
                        "Only an admin (or the owner) can change the language here."
                    ),
                    reply_to=message.id,
                )
                return
            await chatcfg.set(message.chat.id, "lang", code)
            current = code
            saved = True
        elif code:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    f"<b>{rich.esc(code)}</b> is not one of the languages I have. "
                    f"Available: <code>{', '.join(i18n.available())}</code>."
                ),
                reply_to=message.id,
            )
        await rich.send(
            client,
            message.chat.id,
            language_card(current, text_key="lang.saved" if saved else "lang.note"),
            markup_keyboard=keyboard(current),
            reply_to=message.id,
        )


__all__ = ["can_change", "keyboard", "language_card", "register"]
