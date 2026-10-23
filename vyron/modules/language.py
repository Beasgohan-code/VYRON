# ---------------------------------------------------------------------------
#  VYRON — /language
#
#  One card, one tap. The choice is per chat (a group can be Malayalam while
#  the owner's DM stays English) and lives in the chat config, so it survives
#  restarts. Adding a language is a JSON file — see vyron/core/i18n.py.
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core import chatcfg, i18n
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.theme import E, small_caps
from vyron.utils.helpers import is_chat_admin, is_owner, is_private_chat


def language_card(current: str, *, text_key: str = "lang.note") -> str:
    """The picker: what is on, what is available, how to change it."""
    catalog = i18n.catalog(current)
    active = i18n.resolve(current)
    rows = [
        (f"{'✅' if code == active else '▫️'} <b>{name}</b>", f"<code>{code}</code>")
        for code, name in i18n.available().items()
    ]
    return (
        B.heading(f"{E('globe')} {small_caps(catalog.t('lang.title'))}", 2)
        + B.note(catalog.t(text_key))
        + B.table(None, rows, border=0)
        + B.note(
            f"{E('check')} <b>{catalog.t('lang.current')}</b> — {i18n.name(active)}"
        )
        + B.row(*language_buttons(active))
        + B.footer("admins choose in groups · your DM keeps its own")
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
    @client.on_message(filters.command(["language", "lang"]))
    async def _language(_: Client, message: Message) -> None:
        current = str(await chatcfg.get(message.chat.id, "lang", "") or "")
        await rich.send(
            client,
            message.chat.id,
            language_card(current),
            markup_keyboard=keyboard(current),
            reply_to=message.id,
        )


__all__ = ["can_change", "keyboard", "language_card", "register"]
