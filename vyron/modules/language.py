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


#: Languages per page.  Four plus the two arrows is exactly six buttons, which
#: is the most a card carries — with nineteen languages the picker has to page,
#: and a wall of buttons is the one thing a picker must never be.
PAGE_SIZE = 4


def _entries() -> list[tuple[str, str]]:
    return list(i18n.available().items())


def page_count() -> int:
    return max(1, -(-len(_entries()) // PAGE_SIZE))


def clamp_page(page: int) -> int:
    try:
        value = int(page)
    except (TypeError, ValueError):
        return 0
    return max(0, min(page_count() - 1, value))


def page_of(code: str) -> int:
    """The page the current language is on — opening the picker shows the ✅."""
    active = i18n.resolve(code)
    for index, (item, _) in enumerate(_entries()):
        if item == active:
            return index // PAGE_SIZE
    return 0


def page_entries(page: int) -> list[tuple[str, str]]:
    start = clamp_page(page) * PAGE_SIZE
    return _entries()[start : start + PAGE_SIZE]


def language_card(current: str, *, text_key: str = "lang.note", page: int | None = None) -> str:
    """The picker: what is on, what is on this page, how to change it."""
    catalog = i18n.catalog(current)
    active = i18n.resolve(current)
    coverage = i18n.coverage()
    shown = clamp_page(page_of(current) if page is None else page)
    rows = [
        (
            f"{'✅' if code == active else '▫️'} <b>{name}</b>",
            f"<code>{code}</code>"
            + ("" if coverage.get(code, 100) >= 100 else f" · {coverage.get(code)}% translated"),
        )
        for code, name in page_entries(shown)
    ]
    total = len(_entries())
    pager = catalog.t("lang.page", page=shown + 1, pages=page_count())
    return (
        B.banner(catalog.t('lang.title'), glyph="globe")
        + B.note(catalog.t(text_key))
        + B.table(None, rows, border=0)
        + B.note(
            f"{E('check')} <b>{catalog.t('lang.current')}</b> — {i18n.name(active)}"
            f" · {pager} · {total} languages"
        )
        + B.row(*language_buttons(active, shown))
        + B.footer(
            "admins choose in groups · your DM keeps its own · "
            "/setlang &lt;code&gt; · any missing string falls back to English"
        )
    )


def language_buttons(current: str, page: int | None = None) -> list:
    """This page's languages, bracketed by the arrows that reach the rest."""
    active = i18n.resolve(current)
    shown = clamp_page(page_of(current) if page is None else page)
    buttons = [
        B.btn(
            f"{'✅' if code == active else '▫️'} {name}",
            data=f"v:lang:{code}",
            style="success" if code == active else None,
        )
        for code, name in page_entries(shown)
    ]
    if shown > 0:
        buttons.insert(0, B.btn("◀", data=f"v:lang:page:{shown - 1}"))
    if shown < page_count() - 1:
        buttons.append(B.btn("▶", data=f"v:lang:page:{shown + 1}"))
    return buttons


def keyboard(current: str, page: int | None = None):
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    active = i18n.resolve(current)
    shown = clamp_page(page_of(current) if page is None else page)
    buttons = [
        InlineKeyboardButton(
            f"{'✅' if code == active else ''} {name}".strip(),
            callback_data=f"v:lang:{code}",
        )
        for code, name in page_entries(shown)
    ]
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    nav = []
    if shown > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"v:lang:page:{shown - 1}"))
    nav.append(
        InlineKeyboardButton(
            f"{shown + 1}/{page_count()}",
            callback_data="v:lang:menu",
        )
    )
    if shown < page_count() - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"v:lang:page:{shown + 1}"))
    rows.append(nav)
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
        page: int | None = None
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
            language_card(
                current, text_key="lang.saved" if saved else "lang.note", page=page
            ),
            markup_keyboard=keyboard(current, page),
            reply_to=message.id,
        )


__all__ = ["can_change", "keyboard", "language_card", "register"]
