# ---------------------------------------------------------------------------
#  VYRON — inline mode
#  @VyronMusicBot <song>  → shareable results straight from any chat.
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

logger = logging.getLogger(__name__)

CACHE_TIME = 30


def _button_row(track) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🎧 Stream in this chat", callback_data=f"v:nopeep:{track.id}")]
    ]
    if track.watch_url:
        buttons.append([InlineKeyboardButton("▶️ Watch on YouTube", url=track.watch_url)])
    return InlineKeyboardMarkup(buttons)


def register(client: Client) -> None:
    @client.on_inline_query()
    async def _inline(_: Client, query: InlineQuery) -> None:
        text = (query.query or "").strip()
        if not text:
            await query.answer(
                [
                    InlineQueryResultArticle(
                        title=f"{settings.bot_name} · search music",
                        description="Type a song name, artist or paste a link",
                        thumb_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                        input_message_content=InputTextMessageContent(
                            f"🎧 <b>{settings.bot_name}</b> — inline music search\n"
                            f"Send <code>@{settings.bot_username} song name</code> in any chat."
                        ),
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "🚀 Open the bot",
                                        url=f"https://t.me/{settings.bot_username}",
                                    )
                                ]
                            ]
                        ),
                    )
                ],
                cache_time=CACHE_TIME,
                is_personal=True,
            )
            return

        if runtime.youtube is None:
            await query.answer([], cache_time=5, switch_pm_text="Bot is starting…", switch_pm_parameter="start")
            return

        try:
            tracks = await runtime.youtube.search(
                text, limit=8, requester=(query.from_user.id, query.from_user.first_name or "")
            )
        except MediaError:
            await query.answer(
                [],
                cache_time=5,
                switch_pm_text="No results — open the bot",
                switch_pm_parameter="start",
            )
            return
        except Exception as exc:
            logger.debug("inline search failed: %s", exc)
            await query.answer([], cache_time=5)
            return

        results = []
        for index, track in enumerate(tracks):
            description = " · ".join(
                filter(
                    None,
                    [
                        truncate(track.uploader, 26) or track.source,
                        fmt_duration(track.duration),
                        f"{compact_number(track.views)} plays" if track.views else "",
                        "top match" if index == 0 else "",
                    ],
                )
            )
            results.append(
                InlineQueryResultArticle(
                    id=f"{track.source}-{track.id}",
                    title=truncate(track.title, 60),
                    description=description,
                    thumb_url=track.thumbnail or None,
                    input_message_content=InputTextMessageContent(
                        f"🎧 <b>{settings.bot_name}</b>\n"
                        f"🎶 {truncate(track.title, 70)}\n"
                        f"⏱ {fmt_duration(track.duration)} · {truncate(track.uploader, 40)}",
                        parse_mode=ParseMode.HTML,
                    ),
                    reply_markup=_button_row(track),
                )
            )

        await query.answer(results, cache_time=CACHE_TIME, is_personal=True)


__all__ = ["register"]
