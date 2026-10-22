# ---------------------------------------------------------------------------
#  VYRON — Telegram client factory
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.raw.functions.phone import CreateGroupCall

from vyron.config import Settings

logger = logging.getLogger(__name__)


def build_bot(settings: Settings) -> Client:
    return Client(
        name=settings.session_name,
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        bot_token=settings.bot_token,
        parse_mode=ParseMode.HTML,
        in_memory=True,
        workers=12,
        sleep_threshold=20,
        app_version="VYRON 1.0",
        device_model="VYRON Music",
    )


def build_assistant(settings: Settings) -> Client | None:
    if not settings.session_string:
        logger.warning("STRING_SESSION is missing — voice streaming disabled, file mode only")
        return None
    return Client(
        name=f"{settings.session_name}_assistant",
        api_id=settings.api_id,
        api_hash=settings.api_hash,
        session_string=settings.session_string,
        in_memory=True,
        sleep_threshold=20,
        app_version="VYRON 1.0",
        device_model="VYRON Assistant",
    )


async def start_group_call(assistant: Client, chat_id: int) -> bool:
    """Explicitly start a voice chat (fallback when auto-start is not wanted)."""
    try:

        peer = await assistant.resolve_peer(chat_id)
        await assistant.invoke(
            CreateGroupCall(
                peer=peer,
                random_id=abs(hash((chat_id, "vyron"))) % (2**31),
                title="VYRON",
            )
        )
        return True
    except Exception as exc:  # already running / no permission
        logger.debug("create group call failed: %s", exc)
        return False


__all__ = ["build_assistant", "build_bot", "start_group_call"]
