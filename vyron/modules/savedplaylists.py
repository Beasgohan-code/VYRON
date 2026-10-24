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
from vyron.ui import keyboards, rich
from vyron.ui.progress import fmt_duration, truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def register(client: Client) -> None:
    # ── /playlists ─────────────────────────────────────────────────────────
    @client.on_message(cmd(["playlists"]))
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
    @client.on_message(cmd(["savepl"]))
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
            + B.row(B.btn(f"{E('play')} Queue it", data=f"v:pl:{playlist['id']}", style="primary"),
                    B.btn(f"{E('close')} Done", data="v:close"))
            if added
            else B.note(f"{E('info')} Those tracks are already in <b>{rich.esc(playlist['name'])}</b>."),
            reply_to=message.id,
        )

    # ── /pl <name>──────────────────────────────────────────────────────────
    @client.on_message(cmd(["pplay"]))
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
    @client.on_message(cmd(["pdelete"]))
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
    # ── /pcreate · /padd · /pview · /premove (Shizu command names) ─────────
    @client.on_message(cmd(["pcreate"]))
    async def _pcreate(_: Client, message: Message) -> None:
        name = store.clean_name(command_args(message) or "")
        if not name:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Usage: <code>/pcreate chill nights</code>"),
                reply_to=message.id,
            )
            return
        if await store.find(_uid(message), name):
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} You already have a playlist called <b>{rich.esc(name)}</b>."),
                reply_to=message.id,
            )
            return
        playlist = await store.create(_uid(message), name)
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('playlist')} playlist created", 3)
            + B.kv(
                [
                    (f"{E('name')} name", f"<b>{rich.esc(playlist['name'])}</b>"),
                    (f"{E('plus')} tracks", "<b>0</b>"),
                ]
            )
            + B.note(
                f"{E('info')} <code>/padd {rich.esc(playlist['name'])}</code> adds what is playing now."
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
                B.note(f"{E('info')} Usage: <code>/padd chill nights</code>"),
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
                B.note(f"{E('warn')} Nothing is playing — start a track or reply to an audio file."),
                reply_to=message.id,
            )
            return

        added = await store.add_tracks(_uid(message), playlist["id"], [track])
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('check')} <b>{'Added' if added else 'Already there'}</b> · "
                f"{rich.esc(truncate(track.title, 44))} → <b>{rich.esc(playlist['name'])}</b>"
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
                B.note(
                    f"{E('info')} <code>/pview &lt;name&gt;</code> — "
                    f"{len(await store.list_playlists(_uid(message)))} playlists saved."
                ),
                reply_to=message.id,
            )
            return
        tracks = playlist.get("tracks", [])
        rows = [
            (
                f"<b>{index}</b>",
                rich.esc(truncate(str(item.get("title") or "—"), 40)),
                fmt_duration(int(item.get("duration") or 0)),
            )
            for index, item in enumerate(tracks[:20], start=1)
        ]
        total = sum(int(item.get("duration") or 0) for item in tracks)
        body = B.heading(f"{E('playlist')} {rich.esc(truncate(playlist['name'], 34))}", 3)
        body += (
            B.table(["#", "title", "time"], rows)
            if rows
            else B.note(f"{E('moon')} Empty — <code>/padd {rich.esc(playlist['name'])}</code>.")
        )
        body += B.note(
            f"{E('clock')} <b>{len(tracks)}</b> tracks · <b>{fmt_duration(total)}</b> · "
            f"<code>/pplay {rich.esc(truncate(playlist['name'], 24))}</code>"
        )
        await rich.send(
            client,
            message.chat.id,
            body,
            markup_keyboard=keyboards.back_close("v:help:main"),
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
                B.note(f"{E('info')} Usage: <code>/premove chill nights 3</code>"),
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
                B.note(f"{E('warn')} No track #{index} in that playlist."),
                reply_to=message.id,
            )
            return
        item = tracks[index - 1]
        removed = await store.remove_track(_uid(message), playlist["id"], str(item.get("id") or ""))
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('check')} Removed <b>{rich.esc(truncate(str(item.get('title') or '—'), 40))}</b>"
                f" from <b>{rich.esc(playlist['name'])}</b>"
                if removed
                else f"{E('warn')} That track is already gone."
            ),
            reply_to=message.id,
        )



__all__ = ["register"]
