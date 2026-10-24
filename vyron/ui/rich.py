# ---------------------------------------------------------------------------
#  VYRON — rich message delivery
#
#  Two rendering lanes, chosen automatically:
#
#    * RICH   — Telegram's Bot-API "rich message" (headings, tables, collapsible
#               sections, <tg-button>, images).  Beautiful, but messages cannot
#               be edited afterwards, so it is used only for *static* cards.
#    * HTML   — classic parse_mode=HTML, editable in place.  Used for live
#               cards (now-playing, queue) that refresh their progress bar.
#
#  Every call is defensive: if the rich lane raises (old Kurigram build, server
#  rejection, malformed markup) we down-convert the exact same markup to plain
#  HTML and resend, so a user never sees a crash or an empty message.
# ---------------------------------------------------------------------------
from __future__ import annotations

import html as _html
import logging
import re
from typing import Any

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import ReplyParameters

from vyron.config import settings

logger = logging.getLogger(__name__)

try:  # capability probe for the rich-message lane
    from pyrogram import Client as _Client

    RICH_AVAILABLE = hasattr(_Client, "send_rich_message")
except Exception:  # pragma: no cover
    RICH_AVAILABLE = False

try:
    from pyrogram.types import EphemeralMessageParameters
except Exception:  # pragma: no cover
    EphemeralMessageParameters = None  # type: ignore[assignment]

try:
    from pyrogram.types import InputRichMessage
except Exception:  # pragma: no cover
    InputRichMessage = None  # type: ignore[assignment]


# ── tag vocabulary ──────────────────────────────────────────────────────────
_RICH_ONLY = (
    "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th",
    "td", "details", "summary", "mark", "sub", "sup", "tg-button", "button",
    "footer", "header", "img", "aside", "ul", "ol", "li",
    "tg-button-row", "tg-thinking", "tg-math-block", "hr",
)
_RICH_ONLY_RE = re.compile(r"</?(?:%s)\b" % "|".join(_RICH_ONLY), re.I)
_BLOCK_BREAK_RE = re.compile(
    r"</(?:h[1-6]|tr|details|summary|blockquote|table|pre|p)>", re.I
)
_CELL_BREAK_RE = re.compile(r"</(?:th|td)>", re.I)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_VERBATIM_RE = re.compile(r"(<(?:table|pre)\b[\s\S]*?</(?:table|pre)>)", re.I)
_EMOJI_RE = re.compile(
    r'<(?:tg-)?emoji\s+(?:emoji-)?id="[^"]*"\s*>(.*?)</(?:tg-)?emoji>', re.I | re.S
)
_BR_RE = re.compile(r"<br\s*/?>\s*\n?", re.I)

# Messages that were delivered through the rich lane can only be edited through
# it as well; remember them (bounded, oldest entries dropped first).
_RICH_SENT: dict[tuple[int, int], float] = {}
_RICH_SENT_MAX = 400

# Photos cannot be edited with edit_message_text — their captions are. Remember
# which messages are pictures so `edit()` can route without every caller
# knowing (the now-playing poster is refreshed in place this way).
_PHOTO_SENT: dict[tuple[int, int], float] = {}
_PHOTO_SENT_MAX = 400

# Messages Telegram has told us can never be edited again (deleted, too old,
# or the bot lost the right to write). Retrying them on every progress tick
# burns flood quota for nothing, so they are remembered and skipped.
_DEAD: set[tuple[int, int]] = set()
_DEAD_MAX = 600


def _dead(chat_id: int | str, message_id: int | None) -> bool:
    return bool(message_id) and (int(chat_id), int(message_id)) in _DEAD


def _bury(chat_id: int | str, message_id: int | None, exc: BaseException) -> None:
    """Remember a permanently uneditable message (and forget its lane)."""
    from pyrogram.errors import (
        ChannelInvalid,
        ChannelPrivate,
        ChatWriteForbidden,
        MessageDeleteForbidden,
        MessageIdInvalid,
    )

    # "not modified" means the text is already identical — the message is fine,
    # so it must never be buried.
    permanent = (
        MessageIdInvalid,
        MessageDeleteForbidden,
        ChatWriteForbidden,
        ChannelInvalid,
        ChannelPrivate,
    )
    if not isinstance(exc, permanent):
        return
    if message_id:
        _DEAD.add((int(chat_id), int(message_id)))
        if len(_DEAD) > _DEAD_MAX:
            _DEAD.clear()
        _forget(chat_id, message_id)
        _PHOTO_SENT.pop((int(chat_id), int(message_id)), None)


def _remember(chat_id: int, message_id: int | None, stamp: float | None = None) -> None:
    if not message_id:
        return
    import time as _time

    _RICH_SENT[(int(chat_id), int(message_id))] = stamp or _time.time()
    if len(_RICH_SENT) > _RICH_SENT_MAX:
        for key in sorted(_RICH_SENT, key=_RICH_SENT.get)[: len(_RICH_SENT) - _RICH_SENT_MAX]:
            _RICH_SENT.pop(key, None)


def _was_rich(chat_id: int, message_id: int) -> bool:
    return (int(chat_id), int(message_id)) in _RICH_SENT


def _remember_photo(chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    import time as _time

    _PHOTO_SENT[(int(chat_id), int(message_id))] = _time.time()
    if len(_PHOTO_SENT) > _PHOTO_SENT_MAX:
        for key in sorted(_PHOTO_SENT, key=_PHOTO_SENT.get)[:50]:
            _PHOTO_SENT.pop(key, None)


def is_photo(chat_id: int | str, message_id: int) -> bool:
    """Was this message sent with `send_photo` (so it needs a caption edit)?"""
    if not message_id:
        return False
    return (int(chat_id), int(message_id)) in _PHOTO_SENT


def _forget(chat_id: int, message_id: int) -> None:
    _RICH_SENT.pop((int(chat_id), int(message_id)), None)


def esc(value: Any) -> str:
    """Escape untrusted text (titles, names, error strings) for card markup."""
    if value is None:
        return ""
    return _html.escape(str(value), quote=False)


def has_rich_tags(markup: str) -> bool:
    return bool(markup) and bool(_RICH_ONLY_RE.search(markup))


def normalize(markup: str) -> str:
    """Prepare rich HTML for Telegram.

    * newlines outside <table>/<pre> collapse in rich messages → <br/>
    * unquoted ``href=`` (as produced by ``User.mention()``) is rejected → quote
    """
    if not markup:
        return ""
    text = str(markup).replace("\r\n", "\n")
    text = re.sub(r"href='([^']*)'", r'href="\1"', text)
    text = re.sub(r'href=(?!["\'])([^\s">]+)', r'href="\1"', text)

    parts = _VERBATIM_RE.split(text)
    for index in range(0, len(parts), 2):
        if not parts[index]:
            continue
        block = parts[index]
        # Preserve intentional blank lines, convert single breaks.
        block = re.sub(r"\n{2,}", "\x00", block)
        block = block.replace("\n", "<br/>\n")
        block = block.replace("\x00", "<br/><br/>\n")
        parts[index] = block
    return "".join(parts)


def to_html(markup: str) -> str:
    """Down-convert rich markup into classic parse_mode=HTML.

    Keeps only the inline tags Telegram's standard parser accepts, so the same
    card source can be used for both delivery lanes.
    """
    if not markup:
        return ""
    text = normalize(markup)

    text = re.sub(r"<img\b[^>]*/?>", "", text, flags=re.I)
    text = re.sub(r"<p\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<h[1-6]>(.*?)</h[1-6]>", r"\n<b>\1</b>\n", text, flags=re.I | re.S)
    text = re.sub(r"<footer[^>]*>(.*?)</footer>", r"\n<i>\1</i>", text, flags=re.I | re.S)
    text = re.sub(r"<summary>(.*?)</summary>", r"<b>\1</b>\n", text, flags=re.I | re.S)
    text = re.sub(r"<mark>(.*?)</mark>", r"<b>\1</b>", text, flags=re.I | re.S)
    # Rich cards draw their own coloured buttons; the classic lane gets a real
    # ``reply_markup`` keyboard instead, so callback buttons are dropped rather
    # than printed twice as bold text. Link buttons survive as inline links.
    text = re.sub(r"<tg-button-row[^>]*>", "", text, flags=re.I)
    text = re.sub(
        r'<tg-button[^>]*\burl="([^"]*)"[^>]*>(.*?)</tg-button>',
        r'<a href="\1">\2</a>',
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"<tg-button(?:\s[^>]*)?>.*?</tg-button>", "", text, flags=re.I | re.S)
    text = re.sub(r"<tg-button[^>]*/?>", "", text, flags=re.I)
    text = re.sub(r"<button[^>]*>.*?</button>", "", text, flags=re.I | re.S)

    # block-level decorations → readable text equivalents
    text = re.sub(r"<hr\s*/?>", "\n──────────\n", text, flags=re.I)
    text = re.sub(r"<tg-thinking\s*>\s*</tg-thinking>", "…", text, flags=re.I)
    text = re.sub(r"</tg-button-row>", "\n", text, flags=re.I)
    text = re.sub(r"<tg-button-row[^>]*>", "", text, flags=re.I)
    text = re.sub(r"<tg-math-block>(.*?)</tg-math-block>", r"<code>\1</code>", text, flags=re.I | re.S)
    text = re.sub(r"<li\b[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<aside>(.*?)</aside>", r"<i>\1</i>", text, flags=re.I | re.S)
    text = _CELL_BREAK_RE.sub("  ·  ", text)
    text = re.sub(r"</tr>", "\n", text, flags=re.I)
    text = re.sub(r"</table>", "\n", text, flags=re.I)
    text = re.sub(
        r"</?(?:table|thead|tbody|tr|th|td|details|summary|mark|sub|sup|button|footer|header|img|ul|ol|tg-button-row|tg-thinking|tg-math-block)\b[^>]*>",
        "",
        text,
        flags=re.I,
    )
    text = _BR_RE.sub("\n", text)
    text = re.sub(r"[ \t]{3,}", "  ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


_BUTTON_ROW_RE = re.compile(
    r"<tg-button-row\b[^>]*>[\s\S]*?</tg-button-row>|<button\b[^>]*>[\s\S]*?</button>",
    re.I,
)


def to_caption(markup: str) -> str:
    """HTML fit for a photo caption: buttons are dropped, not turned into links.

    A card that renders its own ``<tg-button>`` rows would otherwise show those
    labels twice — once as dead links in the caption and once as the real
    keyboard underneath the picture.
    """
    return to_html(_BUTTON_ROW_RE.sub("", markup))


def to_plain_text(markup: str) -> str:
    """Rich markup → completely tag-free text (used for toasts/notifications)."""
    if not markup:
        return ""
    text = _EMOJI_RE.sub(r"\1", str(markup))
    # Structure first: the same down-conversion the HTML lane does, so lists,
    # tables and separators stay legible when a toast or a log eats a card.
    text = re.sub(r"</tg-button>", "  ·  ", text, flags=re.I)
    text = re.sub(r"<tg-button-row[^>]*>", "", text, flags=re.I)
    text = re.sub(r"</tg-button-row>", "\n", text, flags=re.I)
    text = _CELL_BREAK_RE.sub("  ·  ", text)
    text = re.sub(r"</tr>", "\n", text, flags=re.I)
    text = re.sub(r"<li\b[^>]*>", "• ", text, flags=re.I)
    text = re.sub(r"</li>", "\n", text, flags=re.I)
    text = re.sub(r"<hr\s*/?>", "\n──────────\n", text, flags=re.I)
    text = _BLOCK_BREAK_RE.sub("\n", text)
    text = _BR_RE.sub("\n", text)
    text = _ANY_TAG_RE.sub("", text)
    text = _html.unescape(text)
    # Small caps are a display trick: undo it wherever the card is leaving the
    # chat (toasts, logs, plain lane) so the words read normally again.
    from vyron.ui.theme import un_small_caps

    text = un_small_caps(text)
    text = re.sub(r"[ \t]*·[ \t]*(?=\n|$)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── delivery ────────────────────────────────────────────────────────────────
# `/uistyle` changes lanes at runtime. `Settings` is frozen (by design — it is
# the deployment's contract), so the live choice lives here as an override:
# ``None`` follows RICH_MESSAGES, ``True``/``False`` is what the owner picked.
_style_override: bool | None = None


def blockquote(markup: str) -> str:
    """A quoted asid — `<blockquote>` is a Telegram HTML tag, so this is just
    the wrapper with the escaping done for you (used by /logs and /doctor)."""
    return f"<blockquote>{esc(markup)}</blockquote>"


def rich_enabled() -> bool:
    """Is the rich lane on *right now* for this process?"""
    if _style_override is not None:
        return _style_override
    return bool(settings.rich_messages)


def set_rich_enabled(value: bool | None) -> None:
    global _style_override
    _style_override = value


def _ephemeral(receiver_user_id: int | None, callback_query_id: str | None):
    if not receiver_user_id or EphemeralMessageParameters is None:
        return None
    try:
        return EphemeralMessageParameters(
            receiver_user_id=int(receiver_user_id),
            callback_query_id=callback_query_id,
        )
    except Exception:  # pragma: no cover - older builds
        return None


async def send(
    client,
    chat_id: int | str,
    markup: str,
    *,
    markup_keyboard=None,
    reply_markup=None,
    reply_to: int | None = None,
    editable: bool = False,
    ephemeral_to: int | None = None,
    callback_query_id: str | None = None,
    silent: bool = False,
    protect: bool = False,
    thread_id: int | None = None,
    effect_id: int | None = None,
):
    """Send *markup* as a card. Returns the Message (or None on total failure).

    ``editable=True`` forces the classic HTML lane so the message can later be
    updated in place (progress bars).  ``ephemeral_to=<user id>`` asks Telegram
    to show the message only to that user (groups/supergroups only).
    """
    if not markup:
        return None
    keyboard = markup_keyboard or reply_markup
    # Cards that carry their own <tg-button> rows must not also receive a
    # reply_markup in the rich lane — that would render two button sets.
    inline_buttons = "<tg-button" in markup
    eph = _ephemeral(ephemeral_to, callback_query_id)

    rich_ok = (
        RICH_AVAILABLE
        and InputRichMessage is not None
        and rich_enabled()
        and (eph is not None or (has_rich_tags(markup) and not editable))
    )

    if rich_ok:
        try:
            message = await client.send_rich_message(
                chat_id=chat_id,
                rich_message=InputRichMessage(html=normalize(markup)),
                reply_markup=None if inline_buttons else keyboard,
                reply_parameters=ReplyParameters(message_id=reply_to) if reply_to else None,
                message_thread_id=thread_id,
                disable_notification=silent,
                protect_content=protect,
                effect_id=effect_id,
                ephemeral_message_parameters=eph,
            )
            if message is not None and eph is None:
                _remember(chat_id, message.id)
            return message
        except Exception as exc:  # fall through to the HTML lane
            logger.debug("rich send failed (%s) — falling back to HTML", exc)

    kwargs: dict[str, Any] = dict(
        chat_id=chat_id,
        text=to_html(markup),
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
        disable_notification=silent,
        protect_content=protect,
        link_preview_options=None,
        reply_parameters=ReplyParameters(message_id=reply_to) if reply_to else None,
        message_thread_id=thread_id,
        effect_id=effect_id,
    )
    if eph is not None:
        kwargs["ephemeral_message_parameters"] = eph
    try:
        return await client.send_message(**kwargs)
    except Exception:
        # Last resort: drop the ephemeral wrapper (older servers).
        kwargs.pop("ephemeral_message_parameters", None)
        try:
            return await client.send_message(**kwargs)
        except Exception as exc:
            logger.warning("card send failed: %s", exc)
            return None


async def send_photo(
    client,
    chat_id: int | str,
    photo: Any,
    markup: str,
    *,
    markup_keyboard=None,
    reply_markup=None,
    reply_to: int | None = None,
    silent: bool = False,
    protect: bool = False,
    thread_id: int | None = None,
):
    """Send a picture with a rich *caption*, degrading gracefully.

    Telegram captions are plain HTML — no headings, tables or buttons — so the
    markup is flattened with `to_html` and the keyword rows are handed over as a
    real inline keyboard.  If the photo cannot be uploaded at all (bad file, no
    network) we fall back to the ordinary card so the user still gets `/start`.
    """
    if not markup:
        return None
    keyboard = markup_keyboard or reply_markup
    caption = to_caption(markup)
    if len(caption) > 1024:  # Telegram's caption ceiling
        caption = caption[:1010].rsplit("\n", 1)[0] + "…"
    if photo:
        # Pyrogram only accepts a path, a file id or a *binary file object* —
        # raw bytes would raise "Invalid file" and cost us the poster.
        if isinstance(photo, (bytes, bytearray)):
            import io as _io

            buffer = _io.BytesIO(photo)
            buffer.name = "vyron-poster.jpg"  # type: ignore[attr-defined]
            photo = buffer
        try:
            sent = await client.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                reply_parameters=ReplyParameters(message_id=reply_to) if reply_to else None,
                message_thread_id=thread_id,
                disable_notification=silent,
                protect_content=protect,
            )
            if sent is not None and getattr(sent, "id", None):
                _remember_photo(chat_id, sent.id)
            return sent
        except Exception as exc:
            logger.debug("photo send failed (%s) — falling back to a text card", exc)
    return await send(
        client,
        chat_id,
        markup,
        reply_markup=keyboard,
        reply_to=reply_to,
        silent=silent,
        protect=protect,
        thread_id=thread_id,
    )


async def edit(
    client,
    chat_id: int | str,
    message_id: int,
    markup: str,
    *,
    markup_keyboard=None,
    reply_markup=None,
):
    """Edit a card in place, preserving its original (rich or HTML) lane."""
    if not markup or not message_id or _dead(chat_id, message_id):
        return None
    keyboard = markup_keyboard or reply_markup
    # rich payloads can embed their own <tg-button> rows; don't double up
    inline_buttons = "<tg-button" in markup

    if is_photo(chat_id, message_id):
        return await edit_caption(
            client,
            chat_id,
            message_id,
            markup,
            markup_keyboard=None if inline_buttons else keyboard,
        )

    if (
        rich_enabled()
        and RICH_AVAILABLE
        and InputRichMessage is not None
        and _was_rich(chat_id, message_id)
    ):
        try:
            return await client.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                rich_message=InputRichMessage(html=normalize(markup)),
                reply_markup=None if inline_buttons else keyboard,
            )
        except MessageNotModified:
            return None
        except Exception as exc:
            logger.debug("rich edit failed (%s) — falling back", exc)
            _forget(chat_id, message_id)

    try:
        return await client.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=to_html(markup),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            link_preview_options=None,
        )
    except MessageNotModified:
        return None
    except Exception as exc:
        _bury(chat_id, message_id, exc)
        logger.debug("card edit failed: %s", exc)
        return None


async def edit_caption(
    client,
    chat_id: int | str,
    message_id: int,
    markup: str,
    *,
    markup_keyboard=None,
    reply_markup=None,
):
    """Edit the caption of a photo card (Telegram's 1024-character ceiling)."""
    if not markup or not message_id or _dead(chat_id, message_id):
        return None
    caption = to_caption(markup)
    if len(caption) > 1024:
        caption = caption[:1008].rsplit("\n", 1)[0] + "…"
    keyboard = markup_keyboard if markup_keyboard is not None else reply_markup
    try:
        return await client.edit_message_caption(
            chat_id=chat_id,
            message_id=message_id,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
    except MessageNotModified:
        return None
    except Exception as exc:
        _bury(chat_id, message_id, exc)
        logger.debug("caption edit failed: %s", exc)
        return None


async def edit_inline(media_message, markup: str, *, markup_keyboard=None):
    """Edit an inline card (media message) in place."""
    try:
        return await media_message.edit_text(
            text=to_html(markup),
            parse_mode=ParseMode.HTML,
            reply_markup=markup_keyboard,
            link_preview_options=None,
        )
    except MessageNotModified:
        return None
    except Exception as exc:
        logger.debug("inline edit failed: %s", exc)
        return None


async def react(message, glyph: str) -> None:
    """Best-effort custom reaction on a user's message (Bot API 7+)."""
    try:
        from pyrogram.types import ReactionTypeEmoji

        await message.react([ReactionTypeEmoji(emoji=glyph)])
    except Exception:
        pass


__all__ = [
    "RICH_AVAILABLE",
    "blockquote",
    "edit",
    "edit_inline",
    "esc",
    "has_rich_tags",
    "normalize",
    "react",
    "send",
    "to_html",
    "to_plain_text",
]
