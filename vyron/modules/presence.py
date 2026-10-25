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
#
#  The *assistant* is a separate member, and it is the one that actually joins
#  the call. A group that kicks only the assistant used to keep a queue that
#  could never play again: every track timed out, ten seconds at a time, and
#  nothing ever said why. Now that removal is recognised for what it is.
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


def _subject(update: ChatMemberUpdated):
    """The user id the update is about — the new member, or the old one if gone."""
    member = getattr(update, "new_chat_member", None) or getattr(
        update, "old_chat_member", None
    )
    return int(getattr(getattr(member, "user", None), "id", 0) or 0)


def is_for_me(client: Client, update: ChatMemberUpdated) -> bool:
    """Is this update about *this* bot's own membership?"""
    me = getattr(client, "me", None)
    if me is None:
        return False
    subject = _subject(update)
    return bool(subject) and subject == int(getattr(me, "id", 0) or 0)


def is_for_assistant(update: ChatMemberUpdated) -> bool:
    """Is this update about the account that joins the voice chat?

    Only meaningful when a separate assistant exists; a deployment without one
    has nothing to watch, and an update about the bot itself is not this.
    """
    me = getattr(getattr(runtime, "assistant", None), "me", None)
    if me is None:
        return False
    subject = _subject(update)
    return bool(subject) and subject == int(getattr(me, "id", 0) or 0)


def subject_of(client: Client, update: ChatMemberUpdated) -> str:
    """``"bot"``, ``"assistant"`` or ``""`` — who this membership update is about."""
    if is_for_me(client, update):
        return "bot"
    if is_for_assistant(update):
        return "assistant"
    return ""


async def _abandon(chat_id: int, who: str) -> str:
    """Drop everything kept for a chat. Returns the log line's tail."""
    player = getattr(runtime, "player", None)
    if player is None:
        return "left alone"
    try:
        await player.abandon(chat_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("could not clean up chat %s after removal: %s", chat_id, exc)
        return "left alone"
    logger.info(
        "%s removed from chat %s — queue and settings dropped", who, chat_id
    )
    return "dropped"


async def _report_missing_assistant(client: Client, chat_id: int) -> None:
    """Say why nothing will play, instead of failing one song at a time."""
    text = (
        "<b>My voice account was removed from this group.</b>\n"
        "It is the account that actually joins the voice chat, so nothing can "
        "play until an admin adds it back.\n"
        "<blockquote>Playback stopped and the queue was cleared — nothing is "
        "left half-finished. Add the assistant back and resend the song.</blockquote>"
    )
    try:
        from vyron.ui import cards

        await rich.send(client, chat_id, cards.warn_card(text))
    except Exception as exc:  # pragma: no cover - the group may not let us speak
        logger.debug("could not report the missing assistant in %s: %s", chat_id, exc)


async def handle(client: Client, update: ChatMemberUpdated) -> str:
    """React to a membership change. Returns what was done.

    Both halves are best effort: a group that bans us has already decided, so
    neither a failed greeting nor a failed cleanup may raise into the client's
    dispatcher.
    """
    subject = subject_of(client, update)
    if not subject:
        return ""
    action = transition(update)
    chat = getattr(update, "chat", None)
    chat_id = int(getattr(chat, "id", 0) or 0)
    if not action or not chat_id:
        return ""

    if action == "removed":
        await _abandon(chat_id, "the assistant" if subject == "assistant" else "the bot")
        if subject == "assistant":
            await _report_missing_assistant(client, chat_id)
        return action

    if subject == "assistant":
        # The assistant is invited to a group by hand, usually while the bot
        # already sits there; there is no card to send, only a note for the log.
        logger.info("assistant joined chat %s — calls can play here now", chat_id)
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


__all__ = [
    "handle",
    "is_for_assistant",
    "is_for_me",
    "register",
    "subject_of",
    "transition",
]
