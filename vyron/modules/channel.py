# ---------------------------------------------------------------------------
#  VYRON — channel playback (/cplay)
#  Streams into the discussion group's voice chat from a linked channel, the
#  Mirrors what plays in a channel to a linked group.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import Message

from vyron.core import chatcfg
from vyron.core.search import MediaError, looks_like_url
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, display_name, is_chat_admin

logger = logging.getLogger(__name__)


async def _target_chat(client: Client, message: Message) -> int | None:
    """Explicit `/cplayset` binding wins, otherwise the linked chat."""
    chat = message.chat
    bound = await chatcfg.get(chat.id, "channel", 0)
    if bound:
        return int(bound)
    linked = getattr(chat, "linked_chat_id", None)
    if linked:
        return int(linked)
    if chat.type == ChatType.CHANNEL:
        return int(chat.id)
    try:
        full = await client.get_chat(chat.id)
        if getattr(full, "linked_chat_id", None):
            return int(full.linked_chat_id)
    except Exception:
        pass
    return None


def register(client: Client) -> None:
    @client.on_message(filters.command(["cplay", "channelplay"]))
    async def _cplay(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        query = command_args(message)
        if not query:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('globe')} Usage: <code>/cplay song name or link</code>\n"
                    "The linked channel's voice chat is used."
                ),
            )
            return

        target = await _target_chat(client, message)
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                B.row(
                    B.btn(
                        f"{E('cross')} No linked chat — bind a channel first",
                        data="v:noop",
                        style="danger",
                    )
                ),
            )
            return

        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} <b>Resolving for the channel…</b>",
            reply_to=message.id,
        )
        requester = (
            message.from_user.id if message.from_user else 0,
            display_name(message.from_user),
        )
        try:
            if looks_like_url(query):
                track = await runtime.youtube.resolve(query, requester=requester)
            else:
                results = await runtime.youtube.search(query, limit=1, requester=requester)
                track = results[0]
            await runtime.player.play_track(target, track, video=track.is_video)
            markup = (
                f"{E('live')} <b>Channel stream started</b>\n"
                f"<blockquote>{E('note')} {rich.esc(truncate(track.title, 54))}\n"
                f"{E('chat')} <code>{target}</code></blockquote>"
            )
        except MediaError as exc:
            markup = f"{E('cross')} <b>Could not start</b>\n<blockquote>{rich.esc(truncate(str(exc), 150))}</blockquote>"
        except Exception as exc:
            logger.warning("cplay failed: %s", exc)
            markup = f"{E('warn')} <b>Channel playback failed</b>\n<blockquote>{rich.esc(truncate(str(exc), 150))}</blockquote>"

        if status:
            await rich.edit(client, message.chat.id, status.id, markup)

    # ── /cplayset — pin the channel a group should stream into ────────────
    @client.on_message(filters.command(["cplayset", "setchannel"]))
    async def _cplayset(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        user = message.from_user
        if user and not await is_chat_admin(client, chat_id, user.id):
            await rich.send(
                client,
                chat_id,
                B.row(B.btn(f"{E('shield')} Admins only", data="v:noop", style="danger")),
                reply_to=message.id,
            )
            return
        arg = command_args(message).strip()
        if not arg:
            bound = await chatcfg.get(chat_id, "channel", 0)
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('globe')} Channel playback is bound to <code>{bound}</code>.\n"
                    "<code>/cplayset -1001234567890</code> to change it, "
                    "<code>/cplayset off</code> to use the linked chat."
                    if bound
                    else f"{E('info')} No channel bound — <code>/cplayset &lt;id|@name&gt;</code>"
                ),
                reply_to=message.id,
            )
            return
        if arg.lower() in {"off", "none", "clear", "0"}:
            await chatcfg.set(chat_id, "channel", 0)
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('check')} Cleared — channel playback follows the linked chat again."),
                reply_to=message.id,
            )
            return
        try:
            peer = await client.get_chat(arg if arg.startswith("@") else int(arg))
        except Exception as exc:
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('warn')} Could not resolve that channel: {rich.esc(truncate(str(exc), 90))}"),
                reply_to=message.id,
            )
            return
        await chatcfg.set(chat_id, "channel", int(peer.id))
        await rich.send(
            client,
            chat_id,
            B.heading(f"{E('check')} channel bound", 3)
            + B.kv(
                [
                    (f"{E('globe')} title", f"<b>{rich.esc(truncate(peer.title or '—', 40))}</b>"),
                    (f"{E('id')} id", f"<code>{peer.id}</code>"),
                ]
            )
            + B.note(f"{E('bolt')} <code>/cplay &lt;song&gt;</code> now streams there."),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["cstop", "cend"]))
    async def _cstop(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        target = await _target_chat(client, message)
        if target is None:
            await rich.send(client, message.chat.id, f"{E('info')} No linked chat found.")
            return
        await runtime.player.stop(target, leave=True)
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Channel stream stopped", data="v:noop", style="success")),
        )


__all__ = ["register"]
