# ---------------------------------------------------------------------------
#  VYRON — playlist portability
#
#      /exportpl <name>   send a playlist as a JSON file
#      /importpl          reply to that file to restore it
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import time
from pathlib import Path

from pyrogram import Client
from pyrogram.types import Message

from vyron.core import playlists as store
from vyron.core.queue import Track
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args, display_name
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

EXPORT_FORMAT = "vyron.playlist.v1"


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def register(client: Client) -> None:
    # ── /exportpl ──────────────────────────────────────────────────────────
    @client.on_message(cmd(["exportpl"]))
    async def _export(_: Client, message: Message) -> None:
        if runtime.storage is None:
            return
        name = command_args(message).strip()
        user_id = _uid(message)
        if not name:
            listing = await store.list_playlists(user_id)
            if not listing:
                await rich.send(
                    client,
                    message.chat.id,
                    B.note(f"{E('info')} You have no playlists yet — <code>/savepl</code> first."),
                    reply_to=message.id,
                )
                return
            names = ", ".join(f"<code>{rich.esc(item['name'])}</code>" for item in listing[:10])
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('download')} Which one? {names}\n<code>/exportpl &lt;name&gt;</code>"),
                reply_to=message.id,
            )
            return

        playlist = await store.find(user_id, name)
        if playlist is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} No playlist called <b>{rich.esc(truncate(name, 40))}</b>."),
                reply_to=message.id,
            )
            return

        payload = {
            "format": EXPORT_FORMAT,
            "name": playlist["name"],
            "exported_at": int(time.time()),
            "tracks": [
                {
                    "title": entry.get("title", ""),
                    "uploader": entry.get("uploader", ""),
                    "duration": int(entry.get("duration") or 0),
                    "id": entry.get("id"),
                    "url": entry.get("url"),
                    "source": entry.get("source", "youtube"),
                    "thumbnail": entry.get("thumbnail"),
                }
                for entry in playlist.get("tracks", [])
            ],
        }
        buffer = io.BytesIO(json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
        safe = "".join(ch for ch in playlist["name"] if ch.isalnum() or ch in " -_") or "playlist"
        buffer.name = f"{safe.strip().replace(' ', '-')}.json"
        try:
            await client.send_document(
                message.chat.id,
                buffer,
                caption=(
                    f"{E('playlist')} <b>{rich.esc(truncate(playlist['name'], 40))}</b> · "
                    f"{len(payload['tracks'])} tracks\n"
                    "<i>Keep this file — reply to it with /importpl to restore.</i>"
                ),
                reply_to_message_id=message.id,
            )
        except Exception as exc:
            logger.warning("export failed: %s", exc)
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} Could not send the export: {rich.esc(truncate(str(exc), 120))}"),
                reply_to=message.id,
            )

    # ── /importpl ──────────────────────────────────────────────────────────
    @client.on_message(cmd(["importpl"]))
    async def _import(_: Client, message: Message) -> None:
        if runtime.storage is None:
            return
        replied = message.reply_to_message
        document = getattr(replied, "document", None) if replied else None
        if document is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('info')} Reply to an exported <code>.json</code> with "
                    "<code>/importpl</code> (add a name to rename it)."
                ),
                reply_to=message.id,
            )
            return

        path = await client.download_media(replied)
        try:
            payload = json.loads(await asyncio.to_thread(Path(path).read_text, "utf-8"))
        except Exception:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} That file isn't valid JSON."),
                reply_to=message.id,
            )
            return
        finally:
            try:
                os.unlink(path)
            except Exception:
                pass

        if not isinstance(payload, dict) or payload.get("format") != EXPORT_FORMAT:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('warn')} That isn't a VYRON playlist export "
                    f"(expected <code>{EXPORT_FORMAT}</code>)."
                ),
                reply_to=message.id,
            )
            return

        wanted = command_args(message).strip() or payload.get("name") or "imported"
        user_id = _uid(message)
        playlist = await store.find(user_id, store.clean_name(wanted))
        if playlist is None:
            playlist = await store.create(user_id, store.clean_name(wanted))

        tracks: list[Track] = []
        for entry in payload.get("tracks", [])[: store.MAX_TRACKS]:
            if not isinstance(entry, dict) or not entry.get("title"):
                continue
            tracks.append(
                Track(
                    id=str(entry.get("id") or entry.get("url") or entry["title"])[:64],
                    title=str(entry["title"])[:200],
                    uploader=str(entry.get("uploader") or ""),
                    duration=int(entry.get("duration") or 0),
                    url=str(entry.get("url") or ""),
                    thumbnail=entry.get("thumbnail"),
                    source=str(entry.get("source") or "youtube"),
                    requested_by=user_id,
                    requested_name=display_name(message.from_user),
                )
            )
        added = await store.add_tracks(user_id, playlist["id"], tracks)
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('check')} imported", 3)
            + B.kv(
                [
                    (f"{E('playlist')} playlist", f"<b>{rich.esc(playlist['name'])}</b>"),
                    (f"{E('plus')} added", f"<b>{added}</b>"),
                    (f"{E('queue')} skipped", f"<b>{len(tracks) - added}</b> duplicates"),
                ]
            )
            + B.note(f"{E('play')} queue it with <code>/pl {rich.esc(playlist['name'])}</code>"),
            reply_to=message.id,
        )

__all__ = ["EXPORT_FORMAT", "register"]
