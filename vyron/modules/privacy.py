# ---------------------------------------------------------------------------
#  VYRON — what the bot keeps, and how to get it back or get rid of it
#
#      /mydata      everything stored about you, as a JSON file
#      /forgetme    delete it — two taps, no argument
#
#  A bot that remembers your history, favourites and playlists owes you both
#  answers. The owner has had `/dbcleanup` and `/dbstats` for a while; this is
#  the same courtesy for everybody else, and it works in a DM or a group.
#
#  What is *not* deleted: counters (they are not per-person), a chat's own
#  settings (they belong to the group, not to you) and anything Telegram keeps
#  in the message history. The card says so rather than implying a clean slate.
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import json
import logging
import time

from pyrogram import Client
from pyrogram.types import Message, ReplyParameters

from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, rich
from vyron.ui.theme import E
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

FORMAT = "vyron.userdata.v1"


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def register(client: Client) -> None:
    # ── /mydata ────────────────────────────────────────────────────────────
    @client.on_message(cmd(["mydata", "myinfo"]))
    async def _mydata(_: Client, message: Message) -> None:
        user_id = _uid(message)
        if not user_id:
            return
        if runtime.storage is None:
            await rich.send(
                client,
                message.chat.id,
                B.head("Your data", glyph="warn")
                + B.context("Storage is not ready yet — try again in a moment."),
                reply_to=message.id,
            )
            return

        data = await runtime.storage.export_user(user_id)
        counts = {
            "history": len(data.get("history") or []),
            "favorites": len(data.get("favorites") or []),
            "playlists": len(data.get("playlists") or []),
        }
        document = {
            "format": FORMAT,
            "exported_at": int(time.time()),
            "user_id": user_id,
            "name": message.from_user.first_name if message.from_user else "",
            **data,
        }
        payload = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
        name = f"vyron-{user_id}-{int(time.time())}.json"

        await client.send_document(
            message.chat.id,
            document=io.BytesIO(payload),
            file_name=name,
            caption=(
                "Your VYRON data. Nothing here is shared with anyone, and "
                "/forgetme deletes it."
            ),
            reply_parameters=ReplyParameters(message_id=message.id, allow_sending_without_reply=True),
        )

        await rich.send(
            client,
            message.chat.id,
            B.head("Your data", glyph="id")
            + B.context(
                "That file is everything this deployment stores about you — "
                "no passwords, no tokens, nothing you did not ask the bot for."
            )
            + B.stat_pairs(
                [
                    ("clock", "History", f"<b>{counts['history']}</b> tracks"),
                    ("star", "Favourites", f"<b>{counts['favorites']}</b> saved"),
                    ("queue", "Playlists", f"<b>{counts['playlists']}</b>"),
                ]
            )
            + B.note(
                "Not included: anonymous counters, group settings, and whatever "
                "Telegram itself keeps in this chat."
            )
            + B.actions(
                B.row(B.btn(f"{E('warn')} Delete all of it", data="v:forget:ask", style="danger"))
            ),
            reply_to=message.id,
        )

    # ── /forgetme ──────────────────────────────────────────────────────────
    @client.on_message(cmd(["forgetme", "deleteme", "deletemydata"]))
    async def _forget(_: Client, message: Message) -> None:
        if not _uid(message) or runtime.storage is None:
            return
        # Destructive commands never fire on one tap: the button below confirms.
        await rich.send(
            client,
            message.chat.id,
            cards.confirm_card(
                "Delete your data?",
                "Your history, favourites and playlists are removed from this "
                "deployment. Group settings and the bot's counters stay.",
                confirm="v:forget:yes",
                danger=True,
                confirm_label="Yes, delete it",
            ),
            reply_to=message.id,
        )


__all__ = ["FORMAT", "register"]
