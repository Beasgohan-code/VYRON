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

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core import playlists as store
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import fmt_duration, truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args

logger = logging.getLogger(__name__)


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def register(client: Client) -> None:
    # ── /playlists ─────────────────────────────────────────────────────────
    @client.on_message(filters.command(["playlists", "pls", "mylists"]))
    async def _playlists(_: Client, message: Message) -> None:
        items = await store.list_playlists(_uid(message))
        if not items:
            await rich.send(
                client,
                message.chat.id,
                B.heading(f"{E('playlist')} your playlists", 3)
                + B.note(
                    f"{E('info')} Nothing saved yet.\n"
                    f"<code>/savepl chill nights</code> while something is playing."
                ),
                reply_to=message.id,
            )
            return
        detail = [
            (f"{E('playlist')} <b>{rich.esc(truncate(item['name'], 26))}</b>",
             f"{len(item.get('tracks', []))} tracks")
            for item in items
        ]
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('playlist')} your playlists", 3)
            + B.table(["name", "tracks"], detail)
            + B.note(f"{E('play')} queue one with <code>/pl &lt;name&gt;</code>"),
            reply_to=message.id,
        )

    # ── /savepl ────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["savepl", "saveplaylist", "plsave"]))
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
                B.note(f"{E('warn')} Nothing to save — play something or reply to an audio file."),
                reply_to=message.id,
            )
            return

        added = await store.add_tracks(user_id, playlist["id"], tracks[: store.MAX_TRACKS])
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('check')} saved", 3)
            + B.kv(
                [
                    (f"{E('playlist')} playlist", f"<b>{rich.esc(playlist['name'])}</b>"),
                    (f"{E('plus')} added", f"<b>{added}</b> track{'s' if added != 1 else ''}"),
                    (f"{E('queue')} total", f"<b>{len(playlist.get('tracks', [])) + added}</b>"),
                ]
            )
            + B.row(B.btn(f"{E('play')} Queue it", data="v:pl", style="primary"),
                    B.btn(f"{E('close')} Done", data="v:close"))
            if added
            else B.note(f"{E('info')} Those tracks are already in <b>{rich.esc(playlist['name'])}</b>."),
            reply_to=message.id,
        )

    # ── /pl <name>──────────────────────────────────────────────────────────
    @client.on_message(filters.command(["pl", "playlistplay", "plplay"]))
    async def _play_saved(_: Client, message: Message) -> None:
        name = command_args(message)
        if not name:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Usage: <code>/pl chill nights</code>"),
                reply_to=message.id,
            )
            return
        title, tracks = await store.as_tracks(_uid(message), name)
        if not tracks:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} No playlist called <b>{rich.esc(truncate(name, 30))}</b>."),
                reply_to=message.id,
            )
            return
        if not runtime.player:
            return
        queued = 0
        for track in tracks:
            position = await runtime.player.enqueue(message.chat.id, track)
            if position > 0:
                queued += 1
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('play')} queued playlist", 3)
            + B.kv(
                [
                    (f"{E('playlist')} name", f"<b>{rich.esc(truncate(title, 30))}</b>"),
                    (f"{E('plus')} queued", f"<b>{queued}</b> of {len(tracks)}"),
                    (f"{E('clock')} length",
                     f"<b>{fmt_duration(sum(t.duration for t in tracks))}</b>"),
                ]
            ),
            reply_to=message.id,
        )

    # ── /pldel ─────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["pldel", "plremove", "playlistdelete"]))
    async def _delete(_: Client, message: Message) -> None:
        name = command_args(message)
        playlist = await store.find(_uid(message), name) if name else None
        if playlist is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} Usage: <code>/pldel &lt;playlist name&gt;</code>"),
                reply_to=message.id,
            )
            return
        await store.delete(_uid(message), playlist["id"])
        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('check')} Deleted <b>{rich.esc(playlist['name'])}</b>."),
            reply_to=message.id,
        )


__all__ = ["register"]
