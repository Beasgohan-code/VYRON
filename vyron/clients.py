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


def session_problem(value: str) -> str:
    """A human-readable reason a STRING_SESSION is unusable, or "" when fine.

    Decodes the string exactly the way pyrogram's storage does (using the
    installed version's own format constants), so a truncated paste or an
    all-zero auth key is caught at boot instead of at the first /play.
    """
    raw = (value or "").strip().strip('"').strip("'")
    if not raw:
        return "STRING_SESSION is empty"
    if raw.upper().startswith("STRING_SESSION") or " " in raw:
        return (
            "STRING_SESSION should contain only the value — paste the string itself, "
            "not `STRING_SESSION=…`"
        )

    import base64
    import struct

    try:
        from pyrogram.storage.sqlite_storage import SQLiteStorage

        data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        formats = {
            struct.calcsize(SQLiteStorage.OLD_SESSION_STRING_FORMAT): (
                SQLiteStorage.OLD_SESSION_STRING_FORMAT
            ),
            struct.calcsize(SQLiteStorage.OLD_SESSION_STRING_FORMAT_64): (
                SQLiteStorage.OLD_SESSION_STRING_FORMAT_64
            ),
            struct.calcsize(SQLiteStorage.SESSION_STRING_FORMAT): (
                SQLiteStorage.SESSION_STRING_FORMAT
            ),
        }
        fmt = formats.get(len(data))
        if fmt is None:
            return (
                f"STRING_SESSION is {len(data)} bytes after decoding, which is not a "
                "session this build understands — it was probably cut short when copying"
            )
        unpacked = struct.unpack(fmt, data)
    except Exception as exc:
        return f"STRING_SESSION could not be decoded ({type(exc).__name__}: {exc})"

    if fmt.startswith(">BI?256s"):  # new format: dc_id, api_id, test, key, user, bot
        dc_id, api_id, _test, auth_key, _user_id, _bot = unpacked
    else:  # old format: dc_id, test, key, user, bot
        dc_id, _test, auth_key, _user_id, _bot = unpacked
        api_id = 1
    if not 1 <= int(dc_id) <= 5:
        return f"STRING_SESSION points at data centre {dc_id}, which does not exist"
    if int(api_id) <= 0:
        return "STRING_SESSION has no api_id — generate a fresh one"
    if not auth_key or not auth_key.strip(b"\x00"):
        return (
            "STRING_SESSION has no login key — this is a placeholder or a damaged "
            "string; generate a fresh one with `python -m vyron.tools.session`"
        )
    return ""


def build_assistant(settings: Settings) -> Client | None:
    if not settings.session_string:
        logger.warning(
            "STRING_SESSION is missing — the voice engine is off. /play cannot stream; "
            "generate a session with `python -m vyron.tools.session`."
        )
        return None
    problem = session_problem(settings.session_string)
    if problem:
        logger.error("%s — the voice engine will not start", problem)
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


__all__ = ["build_assistant", "build_bot", "session_problem", "start_group_call"]
