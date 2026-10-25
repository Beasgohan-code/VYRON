# ---------------------------------------------------------------------------
#  VYRON — presence
#
#  What happens the moment the bot joins or leaves a chat, without anybody
#  typing a command:
#
#    · added to a group  → the *group* card, so the first message anybody sees
#      is "is it set up here, and what is missing" — not a bare "hi"
#    · removed / banned  → the queue, the poster, the volume, the loop mode and
#      the stored per-chat settings for that chat are dropped, and the
#      assistant leaves the voice call
#
#  The second half matters more than it looks. A group that removes the bot
#  with music playing otherwise leaves a queue in memory, a snapshot on disk
#  and an assistant sitting in a voice chat nobody can hear — forever.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.types import ChatMemberUpdated

from vyron.modules import start as start_module
from vyron.runtime import runtime
from vyron.ui import keyboards, rich

logger = logging.getLogger(__name__)

#: Statuses that mean "the bot is in the chat".
_PRESENT = {"MEMBER", "ADMINISTRATOR", "OWNER"}


def _status(member) -> str:
    """The member status as an upper-case name, RESTRICTED resolved to in/out.

    ``pyrogram``/``kurigram`` hand over an enum; a stub in a test may hand over
    a plain string. Both end up as one of ``MEMBER``, ``ADMINISTRATOR``,
    ``OWNER``, ``LEFT``, ``BANNED``.
    """
    raw = getattr(member, "status", None)
    name = str(getattr(raw, "name", raw) or "").upper()
    if name == "RESTRICTED":
        # A restricted member is *in* the chat unless is_member says otherwise.
        return "MEMBER" if bool(getattr(member, "is_member", False)) else "LEFT"
    return name


def _presence(member) -> bool:
    return _status(member) in _PRESENT


def transition(update: ChatMemberUpdated) -> str:
    """Classify a membership update: ``"joined"``, ``"removed"`` or ``""``."""
    was = _presence(getattr(update, "old_chat_member", None))
    now = _presence(getattr(update, "new_chat_member", None))
    if was and not now:
        return "removed"
    if now and not was:
        return "joined"
    return ""


def is_for_me(client: Client, update: ChatMemberUpdated) -> bool:
    """Is this update about *this* bot's own membership?"""
    me = getattr(client, "me", None)
    user = getattr(getattr(update, "new_chat_member", None), "user", None) or getattr(
        getattr(update, "old_chat_member", None), "user", None
    )
    if me is None or user is None:
        return False
    return getattr(user, "id", None) == getattr(me, "id", None)


async def handle(client: Client, update: ChatMemberUpdated) -> str:
    """React to the bot's own membership change. Returns what was done.

    Both halves are best effort: a group that bans us has already decided, so
    neither a failed greeting nor a failed cleanup may raise into the client's
    dispatcher.
    """
    if not is_for_me(client, update):
        return ""
    action = transition(update)
    chat = getattr(update, "chat", None)
    chat_id = int(getattr(chat, "id", 0) or 0)
    if not action or not chat_id:
        return ""

    if action == "removed":
        player = getattr(runtime, "player", None)
        abandoned = False
        if player is not None:
            try:
                await player.abandon(chat_id)
                abandoned = True
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("could not clean up chat %s after removal: %s", chat_id, exc)
        logger.info("removed from chat %s — queue and settings %s",
                    chat_id, "dropped" if abandoned else "left alone")
        return action

    # Joined: the setup card, the same one /start shows in a group.
    try:
        markup = await start_module.group_card(
            client, chat, getattr(update, "from_user", None)
        )
        await rich.send(
            client,
            chat_id,
            markup,
            markup_keyboard=keyboards.start_panel(player=False),
        )
    except Exception as exc:
        logger.debug("could not greet chat %s: %s", chat_id, exc)
    return action


def register(client: Client) -> None:
    @client.on_chat_member_updated()
    async def _presence(_: Client, update: ChatMemberUpdated) -> None:
        await handle(client, update)


__all__ = ["handle", "is_for_me", "register", "transition"]
