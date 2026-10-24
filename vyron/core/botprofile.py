# ---------------------------------------------------------------------------
#  VYRON — bot profile
#
#  A polished bot is not only its messages: it is also what Telegram shows
#  before anything is sent. At boot we install
#
#    · a name, short description and long description (masked, no secrets)
#    · scoped command menus — ordinary users never see owner tooling, group
#      admins get the moderation set, the owner gets the console
#    · default admin rights requested when the bot is added to a group, so it
#      can manage voice chats, delete messages and invite people without a
#      manual "promote me" round-trip
#
#  Every call is best-effort: a rate limit or a missing right must never stop
#  the bot from booting.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from vyron.config import settings

logger = logging.getLogger(__name__)

NAME = "𓆩 𝐕𝐘𝐑𝐎𝐍 𓆪"

SHORT_DESCRIPTION = (
    "Stream music into any Telegram voice chat, or download it — "
    "with a full Mini App player. /play to start."
)

DESCRIPTION = (
    "VYRON — music beyond limits.\n\n"
    "• /play <song or link>   stream into the voice chat\n"
    "• /song <song or link>   send the MP3 here\n"
    "• /search <text>         browse results and pick one\n"
    "• /app                   open the player inside Telegram\n"
    "• /help                  every command\n\n"
    "Add me to a group, give me voice-chat rights, and I will keep the music "
    "running around the clock."
)

# ── command menus ───────────────────────────────────────────────────────────
USER_COMMANDS = [
    ("play", "stream audio in the voice chat"),
    ("song", "download an MP3"),
    ("search", "search and pick a result"),
    ("queue", "what is coming up"),
    ("np", "now playing"),
    ("lyrics", "lyrics for the current track"),
    ("pause", "pause playback"),
    ("resume", "resume playback"),
    ("skip", "next track"),
    ("stop", "end the session"),
    ("app", "open the player app"),
    ("help", "all commands"),
]

ADMIN_COMMANDS = [
    ("gadmin", "group manager panel"),
    ("settings", "per-chat playback settings"),
    ("locks", "content locks and anti-flood"),
    ("rules", "this chat's rules"),
    ("warn", "warn a member"),
    ("mute", "mute a member"),
    ("ban", "ban a member"),
    ("purge", "bulk delete messages"),
    ("setwelcome", "set the welcome message"),
    ("captcha", "verify new members"),
    ("zombies", "find deleted accounts"),
    ("report", "flag a message to admins"),
    ("cplay", "stream from the linked channel"),
    ("cstop", "stop the channel stream"),
    ("cseek", "seek the channel stream"),
    ("cvolume", "channel volume"),
]

OWNER_COMMANDS = ADMIN_COMMANDS + [
    ("stats", "bot statistics"),
    ("logs", "the owner journal"),
    ("api", "the music API"),
    ("apitoken", "owner token for API access"),
    ("sudoers", "who can operate the bot"),
    ("vars", "configuration snapshot (masked)"),
    ("broadcast", "message every chat"),
]


def _commands(pairs: list[tuple[str, str]]):
    from pyrogram.types import BotCommand

    return [BotCommand(command=name, description=desc[:256]) for name, desc in pairs]


async def install(bot) -> dict[str, bool]:
    """Apply the whole profile; returns which steps succeeded."""
    report = {"name": False, "about": False, "commands": False, "rights": False}

    if not getattr(settings, "bot_profile", True):
        return report

    try:
        await bot.set_bot_name(NAME)
        report["name"] = True
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("could not set the bot name: %s", exc)

    try:
        await bot.set_bot_info_short_description(SHORT_DESCRIPTION)
        await bot.set_bot_info_description(DESCRIPTION)
        report["about"] = True
    except Exception as exc:  # pragma: no cover - network dependent
        logger.debug("could not set the bot description: %s", exc)

    try:
        from pyrogram.types import BotCommandScopeAllChatAdministrators, BotCommandScopeChat
        from pyrogram.types import BotCommandScopeDefault

        await bot.set_bot_commands(_commands(USER_COMMANDS), scope=BotCommandScopeDefault())
        await bot.set_bot_commands(
            _commands(ADMIN_COMMANDS), scope=BotCommandScopeAllChatAdministrators()
        )
        owner_id = getattr(settings, "owner_id", 0)
        if owner_id:
            try:
                await bot.set_bot_commands(
                    _commands(OWNER_COMMANDS), scope=BotCommandScopeChat(chat_id=owner_id)
                )
            except Exception as exc:  # pragma: no cover - owner may not have opened a DM
                logger.debug("owner command scope skipped: %s", exc)
        report["commands"] = True
    except Exception as exc:  # pragma: no cover
        logger.debug("could not set scoped commands: %s", exc)

    try:
        from pyrogram.types import ChatAdministratorRights

        await bot.set_bot_default_privileges(
            ChatAdministratorRights(
                can_manage_chat=True,
                can_delete_messages=True,
                can_manage_video_chats=True,
                can_restrict_members=True,
                can_invite_users=True,
                can_pin_messages=True,
                can_change_info=True,
            )
        )
        report["rights"] = True
    except Exception as exc:  # pragma: no cover
        logger.debug("could not set default admin rights: %s", exc)

    logger.info(
        "bot profile: %s",
        ", ".join(name for name, ok in report.items() if ok) or "nothing applied",
    )
    return report


__all__ = [
    "ADMIN_COMMANDS",
    "DESCRIPTION",
    "NAME",
    "OWNER_COMMANDS",
    "SHORT_DESCRIPTION",
    "USER_COMMANDS",
    "install",
]
