# ---------------------------------------------------------------------------
#  VYRON — diagnostics & access
#
#  /sudoers — who can operate the bot (owner + SUDO_USERS)
#
#  Operational diagnostics for a self-hosted deployment.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.config import settings
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import display_name

logger = logging.getLogger(__name__)


def register(client: Client) -> None:
    # ── /sudoers ───────────────────────────────────────────────────────────
    @client.on_message(filters.command(["sudoers"]) & owner)
    async def _sudoers(_: Client, message: Message) -> None:
        ids = sorted(settings.owners)
        names: dict[int, str] = {}
        if ids:
            try:
                async for user in client.get_users(ids):
                    names[user.id] = display_name(user)
            except Exception:  # pragma: no cover - network
                pass
        lines = []
        for user_id in ids:
            role = "owner" if user_id == settings.owner_id else "sudo"
            who = rich.esc(names.get(user_id) or "unknown")
            lines.append(f"• <code>{user_id}</code> — {who} <i>({role})</i>")
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('shield')} sudoers", 3)
            + (B.bullets(lines) if lines else B.note(f"{E('warn')} No owners configured."))
            + B.footer(
                f"{E('note')} add ids via <code>SUDO_USERS=1,2,3</code> in .env, then restart"
            ),
            reply_to=message.id,
        )



__all__ = ["register"]
