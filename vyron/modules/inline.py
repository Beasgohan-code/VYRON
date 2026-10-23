# ---------------------------------------------------------------------------
#  VYRON — inline mode
#
#  @VyronMusicBot <song>  → a ranked, album-art list of results that can be
#  shared into any chat, with a working "play here" button.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from vyron.config import settings
from vyron.core.search import MediaError
from vyron.runtime import runtime
from vyron.ui.progress import compact_number, fmt_duration, truncate
from vyron.ui.rich import esc
from vyron.ui.theme import BRAND_DISPLAY

logger = logging.getLogger(__name__)

CACHE_TIME = 30
MAX_RESULTS = 8
CALLBACK_LIMIT = 64  # Telegram rejects anything longer


# ── pieces ──────────────────────────────────────────────────────────────────
def _share_text(track) -> str:
    """The message a shared result produces — readable outside the bot too."""
    meta = f"👤 {esc(truncate(track.uploader, 50) or track.source)}"
    meta += f" · ⏱ {fmt_duration(track.duration)}"
    if track.views:
        meta += f" · ▶️ {compact_number(track.views)}"
    lines = [f"🎧 <b>{esc(truncate(track.title, 90))}</b>", meta]
    if track.watch_url:
        lines.append(f'<a href="{esc(track.watch_url)}">source</a>')
    lines.append(f"<i>shared from @{esc(settings.bot_username)}</i>")
    return "\n".join(lines)


def _play_data(track) -> str | None:
    """Callback payload for "play here", kept inside Telegram's 64-byte cap."""
    candidates = []
    if track.watch_url:
        candidates.append(f"v:play:{track.watch_url}")
    candidates.append(f"v:play:{track.title} {track.uploader}".strip())
    candidates.append(f"v:play:{track.title}")
    for data in candidates:
        if len(data.encode("utf-8")) <= CALLBACK_LIMIT:
            return data
    return None


def _keyboard(track) -> InlineKeyboardMarkup:
    rows = []
    data = _play_data(track)
    if data:
        rows.append([InlineKeyboardButton("▶️ Play in this chat", callback_data=data)])
    if track.watch_url:
        rows.append([InlineKeyboardButton("🔗 Open source", url=track.watch_url)])
    rows.append(
        [
            InlineKeyboardButton(
                f"🎧 {settings.bot_name}",
                url=f"https://t.me/{settings.bot_username}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def _description(track, rank: int) -> str:
    bits = [truncate(track.uploader, 26) or track.source, fmt_duration(track.duration)]
    if track.views:
        bits.append(f"{compact_number(track.views)} plays")
    bits.append("top match" if rank == 0 else f"#{rank + 1}")
    return " · ".join(bit for bit in bits if bit)


def _empty_result() -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id="vyron-hint",
        title=f"{BRAND_DISPLAY} · search music",
        description="Type a song, an artist, or paste a link",
        input_message_content=InputTextMessageContent(
            f"🎧 <b>{esc(BRAND_DISPLAY)}</b> — inline music search\n"
            f"Try <code>@{esc(settings.bot_username)} believer</code> in any chat.",
            parse_mode=ParseMode.HTML,
        ),
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🚀 Open the bot", url=f"https://t.me/{settings.bot_username}"
                    )
                ]
            ]
        ),
    )


# ── handler body ────────────────────────────────────────────────────────────
async def answer_inline(query: InlineQuery) -> None:
    """Build the result list for one inline query (separated for testing)."""
    text = (query.query or "").strip()
    if not text:
        await query.answer([_empty_result()], cache_time=CACHE_TIME, is_personal=True)
        return

    if runtime.youtube is None:
        await query.answer(
            [],
            cache_time=5,
            switch_pm_text="Bot is starting…",
            switch_pm_parameter="start",
        )
        return

    try:
        tracks = await runtime.youtube.search(
            text,
            limit=MAX_RESULTS,
            requester=(
                query.from_user.id if query.from_user else 0,
                (query.from_user.first_name if query.from_user else "") or "",
            ),
        )
    except MediaError:
        await query.answer(
            [],
            cache_time=5,
            switch_pm_text="No results — open the bot",
            switch_pm_parameter="start",
        )
        return
    except Exception as exc:  # never leave the user with a spinner
        logger.debug("inline search failed: %s", exc)
        await query.answer([], cache_time=5)
        return

    results = [
        InlineQueryResultArticle(
            id=f"{track.source}-{track.id}",
            title=truncate(track.title, 60),
            description=_description(track, rank),
            thumb_url=track.thumbnail or None,
            input_message_content=InputTextMessageContent(
                _share_text(track), parse_mode=ParseMode.HTML
            ),
            reply_markup=_keyboard(track),
        )
        for rank, track in enumerate(tracks)
    ]
    await query.answer(results, cache_time=CACHE_TIME, is_personal=True)


def register(client: Client) -> None:
    @client.on_inline_query()
    async def _inline(_: Client, query: InlineQuery) -> None:
        await answer_inline(query)


__all__ = ["answer_inline", "register"]
