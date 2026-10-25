# ---------------------------------------------------------------------------
#  VYRON — /doctor  (deployment health)
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.utils.commands import cmd
from vyron.utils import sysinfo

logger = logging.getLogger(__name__)


def _checks() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    # bot token presence (don't print token)
    out.append(("Bot token", "ok" if settings.bot_token else "fail", "set" if settings.bot_token else "missing"))
    # assistant
    has_session = bool(getattr(settings, "string_session", None) or getattr(settings, "assistant_session", None))
    out.append(("STRING_SESSION", "ok" if has_session else "warn", "assistant ready" if has_session else "voice limited"))
    # player
    out.append(("Player", "ok" if runtime.player else "warn", "running" if runtime.player else "not started"))
    # storage / mongo
    out.append(("Storage", "ok" if runtime.storage else "warn", "ready" if runtime.storage else "memory only"))
    # logger channel
    lid = getattr(settings, "logger_id", None)
    out.append(("LOGGER_ID", "ok" if lid else "warn", str(lid) if lid else "not set"))
    # disk
    snap = sysinfo.snapshot()
    disk = snap.get("disk_percent")
    if disk is not None:
        st = "ok" if float(disk) < 90 else "warn"
        out.append(("Disk", st, f"{disk}% used"))
    # downloads dir
    ddir = getattr(settings, "downloads_dir", None)
    if ddir:
        p = Path(str(ddir))
        out.append(("Downloads dir", "ok" if p.exists() else "warn", str(p)))
    # python
    out.append(("Python", "ok", str(snap.get("python") or "?")))
    return out


def register(client: Client) -> None:
    @client.on_message(cmd(["doctor", "health"]))
    async def _doctor(_: Client, message: Message) -> None:
        await rich.send(
            client,
            message.chat.id,
            cards.doctor_card(_checks()),
            reply_to=message.id,
        )


__all__ = ["register"]
