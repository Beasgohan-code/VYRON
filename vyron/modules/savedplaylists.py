# ---------------------------------------------------------------------------
#  VYRON — saved playlists (per-user, persistent)
#
#  /savepl <name>   — save the current track (or the whole queue) into a playlist
#  /playlists       — list your playlists
#  /pl <name>       — queue a saved playlist
#  /pldel <name>    — delete one
#
#  The same store powers the Library view of the web app
#  (see vyron/core/playlists.py).
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.types import Message

from vyron.core import playlists as store
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.ui.progress import fmt_duration, truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def register(client: Client) -> None:
    # ── /playlists ─────────────────────────────────────────────────────────
    @client.on_message(cmd(["playlists", "myplaylists", "listpl"]))
    async def _playlists(_: Client, message: Message) -> None:
        items = await store.list_playlists(_uid(message))
        await rich.send(
            client,
            message.chat.id,
            cards.playlists_card(items),
            reply_to=message.id,
        )

    # ── /savepl ────────────────────────────────────────────────────────────
    @client.on_message(cmd(["savepl", "saveplaylist"]))
    async def _save(_: Client, message: Message) -> None:
        if not runtime.storage:
            return
        name_arg = command_args(message)
        user_id = _uid(message)
        existing = await store.list_playlists(user_id)
        name = store.clean_name(name_arg or f"playlist {len(existing) + 1}")
        playlist = await store.find(user_id, name)
        if playlist is None:
            playlist = await store.create(user_id, name)

        tracks = []
        state = runtime.player.queues.get(message.chat.id) if runtime.player else None
        replied = message.reply_to_message
        if replied is not None and getattr(replied, "audio", None):
            from vyron.utils.helpers import track_from_message

            track = track_from_message(replied)
            if track:
                tracks.append(track)
        if not tracks and state:
            if state.current:
                tracks.append(state.current)
            tracks.extend(state.queue)
        if not tracks:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    "Nothing to save — play something first, or reply to an audio file "
                    "with <code>/savepl</code>."
                ),
                reply_to=message.id,
            )
            return

        added = await store.add_tracks(user_id, playlist["id"], tracks[: store.MAX_TRACKS])
        total = len(playlist.get("tracks", [])) + added
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "saved to playlist",
                glyph="check",
                label="playlist",
                value=f"<b>{rich.esc(playlist['name'])}</b>",
                note=(
                    f"{added} new track{'s' if added != 1 else ''} · {total} in the list."
                    if added
                    else "Those tracks were already in it — nothing was duplicated."
                ),
                extra=[("queue", "now holds", f"<b>{total}</b> tracks")],
                actions=B.row(
                    B.btn(f"{E('play')} Queue it", data=f"v:pl:{playlist['id']}", style="primary"),
                    B.btn(f"{E('playlist')} All playlists", data="v:help:tools"),
                    B.btn(f"{E('close')} Done", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    # ── /pl <name>──────────────────────────────────────────────────────────
    @client.on_message(cmd(["pplay", "loadpl", "loadplaylist", "cpplay"]))
    async def _play_saved(_: Client, message: Message) -> None:
        # `/cpplay` is the same playlist, played where the linked channel's
        # voice chat is — the one thing `/pplay` cannot express.
        channel_mode = message.command[0].lower() == "cpplay"
        target_chat = message.chat.id
        if channel_mode:
            from vyron.modules.channel import resolve_target

            resolved = await resolve_target(client, message)
            if resolved is None:
                await rich.send(
                    client,
                    message.chat.id,
                    cards.warn_card(
                        "<b>No linked channel to play in.</b>\n"
                        "Bind one with <code>/cplayset @channel</code>, or link a "
                        "channel to this group, then try again."
                    ),
                    reply_to=message.id,
                )
                return
            target_chat = resolved

        name = command_args(message)
        if not name:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Usage: <code>/pplay chill nights</code>"),
                reply_to=message.id,
            )
            return
        title, tracks = await store.as_tracks(_uid(message), name)
        if not tracks:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    f"No playlist called <b>{rich.esc(truncate(name, 30))}</b>. "
                    "Send <code>/playlists</code> to see what you have."
                ),
                reply_to=message.id,
            )
            return
        if not runtime.player:
            return
        queued = 0
        for index, track in enumerate(tracks):
            if channel_mode and index == 0:
                # The first track starts the stream; the rest join the queue.
                try:
                    await runtime.player.play_track(
                        target_chat, track, video=track.is_video
                    )
                    queued += 1
                except Exception as exc:  # a dead track must not drop the list
                    logger.warning("cpplay could not start the channel stream: %s", exc)
                continue
            position = await runtime.player.enqueue(target_chat, track)
            if position > 0:
                queued += 1
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "playlist queued",
                glyph="playlist",
                label="playlist",
                value=f"<b>{rich.esc(truncate(title, 30))}</b>",
                note=(
                    "It plays in the linked channel's voice chat."
                    if channel_mode
                    else (
                        "It plays after whatever is already queued — nothing was interrupted."
                        if queued < len(tracks)
                        else "Everything in it went into the queue."
                    )
                ),
                extra=[
                    ("plus", "queued", f"<b>{queued}</b> of {len(tracks)} tracks"),
                    ("clock", "length", f"<b>{fmt_duration(sum(t.duration for t in tracks))}</b>"),
                ],
                actions=B.row(
                    B.btn(f"{E('queue')} See the queue", data="v:queue", style="primary"),
                    B.btn(f"{E('now')} Now playing", data="v:np"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    # ── /pldel ─────────────────────────────────────────────────────────────
    @client.on_message(cmd(["pdelete", "delpl", "rmplaylist", "deleteplaylist"]))
    async def _delete(_: Client, message: Message) -> None:
        name = command_args(message)
        playlist = await store.find(_uid(message), name) if name else None
        if playlist is None:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Usage: <code>/pldel chill nights</code>"),
                reply_to=message.id,
            )
            return
        await store.delete(_uid(message), playlist["id"])
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "playlist deleted",
                glyph="cross",
                label="name",
                value=f"<b>{rich.esc(playlist['name'])}</b>",
                note="It is gone for good. The tracks themselves still play.",
                extra=[("queue", "removed", f"<b>{len(playlist.get('tracks', []))}</b> tracks")],
                actions=B.row(
                    B.btn(f"{E('playlist')} My playlists", data="v:help:tools", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )
    # ── /pcreate · /padd · /pview · /premove ────────────────────────────────
    @client.on_message(cmd(["pcreate"]))
    async def _pcreate(_: Client, message: Message) -> None:
        name = store.clean_name(command_args(message) or "")
        if not name:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Usage: <code>/pcreate chill nights</code>"),
                reply_to=message.id,
            )
            return
        if await store.find(_uid(message), name):
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(f"You already have a playlist called <b>{rich.esc(name)}</b> — "
                            "send <code>/playlists</code> to see it."),
                reply_to=message.id,
            )
            return
        playlist = await store.create(_uid(message), name)
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "playlist created",
                glyph="playlist",
                label="name",
                value=f"<b>{rich.esc(playlist['name'])}</b>",
                note=(
                    f"<code>/padd {rich.esc(playlist['name'])}</code> drops what is playing "
                    "into it. It is empty for now."
                ),
                extra=[("plus", "tracks", "<b>0</b>")],
                actions=B.row(
                    B.btn(f"{E('now')} What is playing", data="v:np", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["padd"]))
    async def _padd(_: Client, message: Message) -> None:
        """Add the current track (or a replied audio) to a named playlist."""
        name = store.clean_name(command_args(message) or "")
        if not name:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Usage: <code>/padd chill nights</code>"),
                reply_to=message.id,
            )
            return
        playlist = await store.find(_uid(message), name)
        if playlist is None:
            playlist = await store.create(_uid(message), name)

        track = None
        replied = message.reply_to_message
        if replied is not None and getattr(replied, "audio", None):
            from vyron.utils.helpers import track_from_message

            track = track_from_message(replied)
        if track is None and runtime.player:
            chat_state = runtime.player.queues.get(message.chat.id)
            track = chat_state.current
        if track is None:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Nothing is playing — start a track, or reply to an audio file with "
                            "<code>/padd</code>."),
                reply_to=message.id,
            )
            return

        added = await store.add_tracks(_uid(message), playlist["id"], [track])
        total = len(playlist.get("tracks", [])) + added
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "added" if added else "already there",
                glyph="check" if added else "info",
                label="track",
                value=f"<b>{rich.esc(truncate(str(track.title), 44))}</b>",
                note=(
                    f"now in <b>{rich.esc(playlist['name'])}</b>"
                    if added
                    else f"<b>{rich.esc(playlist['name'])}</b> already had this one — "
                    "nothing was duplicated."
                ),
                extra=[("playlist", "in the list", f"<b>{total}</b> tracks")],
                actions=B.row(
                    B.btn(f"{E('playlist')} View it", data=f"v:pl:{playlist['id']}", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["pview"]))
    async def _pview(_: Client, message: Message) -> None:
        name = store.clean_name(command_args(message) or "")
        playlist = await store.find(_uid(message), name) if name else None
        if playlist is None:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    f"Which one? You have "
                    f"<b>{len(await store.list_playlists(_uid(message)))}</b> saved — "
                    "send <code>/playlists</code>, then <code>/pview &lt;name&gt;</code>."
                ),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            cards.playlist_card(playlist),
            markup_keyboard=keyboards.back_close("v:help:tools"),
            reply_to=message.id,
        )

    @client.on_message(cmd(["premove"]))
    async def _premove(_: Client, message: Message) -> None:
        """``/premove <name> <index>`` — the index shown by /pview."""
        args = command_args(message).split()
        if len(args) < 2 or not args[-1].isdigit():
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("Usage: <code>/premove chill nights 3</code>"),
                reply_to=message.id,
            )
            return
        index = int(args[-1])
        name = store.clean_name(" ".join(args[:-1]))
        playlist = await store.find(_uid(message), name)
        tracks = (playlist or {}).get("tracks", [])
        if playlist is None or not (1 <= index <= len(tracks)):
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(f"There is no track #{index} in that playlist."),
                reply_to=message.id,
            )
            return
        item = tracks[index - 1]
        removed = await store.remove_track(_uid(message), playlist["id"], str(item.get("id") or ""))
        remaining = len(tracks) - (1 if removed else 0)
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "track removed" if removed else "already gone",
                glyph="check" if removed else "info",
                label="track",
                value=f"<b>{rich.esc(truncate(str(item.get('title') or '—'), 40))}</b>",
                note=(
                    f"Taken out of <b>{rich.esc(playlist['name'])}</b>."
                    if removed
                    else "Someone else got there first — the list is unchanged."
                ),
                extra=[("playlist", "left", f"<b>{max(remaining, 0)}</b> tracks")],
                actions=B.row(
                    B.btn(f"{E('playlist')} View it", data=f"v:pl:{playlist['id']}", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
            reply_to=message.id,
        )



__all__ = ["register"]
