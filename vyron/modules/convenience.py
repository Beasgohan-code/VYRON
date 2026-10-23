# ---------------------------------------------------------------------------
#  VYRON — quality-of-life commands
#
#      /timer 30 · /timer off · /timer      sleep timer for the voice chat
#      /random [mood]                       play something unexpected
#      /exportpl <name>                    send a playlist as JSON
#      /importpl                           reply to that JSON to restore it
#      /daemons                            housekeeping / watchdog / keep-alive
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import io
import json
import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core import charts as charts_mod
from vyron.core import keepalive, maintenance, watchdog
from vyron.core import playlists as store
from vyron.core.queue import Track
from vyron.core.timers import MAX_MINUTES, TimerBoard, humanise, parse_duration
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import human_time, truncate
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args, display_name, is_chat_admin, is_owner

logger = logging.getLogger(__name__)

TIMERS = TimerBoard()
EXPORT_FORMAT = "vyron.playlist.v1"


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def _player():
    return runtime.player


async def _can_drive(client: Client, message: Message) -> bool:
    user = message.from_user
    if user is None:
        return False
    return is_owner(user.id) or await is_chat_admin(client, message.chat.id, user.id)


def register(client: Client) -> None:
    # ── /timer ─────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["timer", "sleep", "sleepafter"]))
    async def _timer(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        arg = command_args(message).strip()

        if not arg:
            entry = TIMERS.get(chat_id)
            if entry is None:
                await rich.send(
                    client,
                    chat_id,
                    B.note(
                        f"{E('clock')} No sleep timer here.\n"
                        "<code>/timer 30</code> · <code>/timer 1h30m</code> · "
                        "<code>/timer off</code>"
                    ),
                    reply_to=message.id,
                )
                return
            left = TIMERS.remaining(chat_id, time.time())
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('clock')} Stopping in <b>{human_time(left)}</b> "
                    f"(set for {humanise(entry.minutes)})."
                ),
                reply_to=message.id,
            )
            return

        if not await _can_drive(client, message):
            await rich.send(
                client,
                chat_id,
                B.row(B.btn(f"{E('shield')} Admins only", data="v:noop", style="danger")),
                reply_to=message.id,
            )
            return

        minutes = parse_duration(arg)
        if minutes is None:
            removed = TIMERS.cancel(chat_id)
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('cross')} Sleep timer cancelled."
                    if removed
                    else f"{E('info')} There was no timer to cancel."
                ),
                reply_to=message.id,
            )
            return
        if minutes <= 0:
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('warn')} I couldn't read that. Try <code>/timer 30</code>, "
                    f"<code>/timer 1h30m</code> or <code>/timer off</code> "
                    f"(max {MAX_MINUTES} minutes)."
                ),
                reply_to=message.id,
            )
            return

        due = time.time() + minutes * 60

        async def _fire() -> None:
            try:
                await asyncio.sleep(minutes * 60)
            except asyncio.CancelledError:
                return
            TIMERS.cancel(chat_id, kill=False)
            player = _player()
            state = player.queues.get(chat_id) if player else None
            title = state.current.title if state and state.current else ""
            if player is not None:
                try:
                    await player.stop(chat_id, leave=True, announce=False)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.debug("timer stop failed: %s", exc)
            await rich.send(
                client,
                chat_id,
                B.heading(f"{E('moon')} sleep timer", 3)
                + B.note(
                    f"{E('check')} Stopped after {humanise(minutes)}"
                    + (f" — was playing <b>{rich.esc(truncate(title, 40))}</b>" if title else "")
                    + ".\n<i>Send /play whenever you're back.</i>"
                ),
            )

        task = asyncio.create_task(_fire())
        TIMERS.set(chat_id, minutes, due=due, task=task)
        await rich.send(
            client,
            chat_id,
            B.heading(f"{E('clock')} sleep timer set", 3)
            + B.kv(
                [
                    (f"{E('clock')} stops in", f"<b>{humanise(minutes)}</b>"),
                    (f"{E('moon')} what happens", "playback stops, I leave the voice chat"),
                ]
            )
            + B.row(B.btn(f"{E('cross')} Cancel timer", data="v:timer:off", style="danger")),
            reply_to=message.id,
        )

    # ── /random ────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["random", "shuffleme", "surprise"]))
    async def _random(_: Client, message: Message) -> None:
        if runtime.youtube is None or runtime.player is None:
            return
        arg = command_args(message).strip().lower()
        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} {B.think()} <b>Rolling the dice…</b>",
            reply_to=message.id,
        )
        requester = (_uid(message), display_name(message.from_user))
        try:
            if arg and arg in charts_mod.MOODS:
                pool = await runtime.charts.mood(arg, limit=8)
            elif arg:
                pool = await runtime.youtube.search(arg, requester=requester)
            else:
                pool = await runtime.charts.trending(limit=12)
        except Exception as exc:
            logger.debug("random lookup failed: %s", exc)
            pool = []

        if not pool:
            await rich.edit(
                client,
                message.chat.id,
                status.id if status else None,
                B.note(f"{E('warn')} No ideas right now — try <code>/random lofi</code>."),
            )
            return

        import random as _rng

        track = _rng.choice(pool)
        from vyron.modules.play import begin

        outcome = await begin(
            client,
            message.chat.id,
            track,
            status_id=status.id if status else None,
            reply_to=message.id,
        )
        if outcome != "file" and status:
            from vyron.ui import cards

            await rich.edit(
                client,
                message.chat.id,
                status.id,
                cards.started_card(track) if outcome == "streamed" else cards.queued_card(track, 0),
            )

    # ── /exportpl ──────────────────────────────────────────────────────────
    @client.on_message(filters.command(["exportpl", "plexport", "exportplaylist"]))
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
    @client.on_message(filters.command(["importpl", "plimport", "importplaylist"]))
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
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
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
                import os

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

    # ── /daemons — background loop status ──────────────────────────────────
    @client.on_message(filters.command(["daemons", "loops", "keepalive", "watchdog"]) & owner)
    async def _daemons(_: Client, message: Message) -> None:
        now = time.time()
        sweep = maintenance.status()
        dog = watchdog.status()
        ping = keepalive.status()

        def ago(stamp) -> str:
            if not stamp:
                return "<i>not yet</i>"
            return f"{human_time(max(0.0, now - float(stamp)))} ago"

        rows = [
            (
                f"{E('spark')} housekeeping",
                f"every <b>{sweep['every_hours']}h</b> · {ago(sweep['last'])} · "
                f"{sweep['files']} files / {sweep['rows']} rows",
            ),
            (
                f"{E('check')} watchdog",
                (
                    f"every <b>{dog.get('enabled') and '60s' or 'off'}</b> · "
                    f"{dog['checks']} checks · {dog['reconnects']} reconnects"
                ),
            ),
            (
                f"{E('link')} keep-alive",
                (
                    f"{'on' if ping['enabled'] else 'off'} · {ping['runs']} pings · "
                    f"last ok {ago(ping['last_ok'])}"
                    + (f" · http {ping['last_status']}" if ping["last_status"] else "")
                ),
            ),
            (
                f"{E('clock')} sleep timers",
                f"<b>{len(TIMERS)}</b> active",
            ),
        ]
        errors = [str(dog.get("last_error") or "").strip()]
        text = B.heading(f"{E('bolt')} background loops", 3) + B.kv(rows)
        note = "\n".join([item for item in errors if item])
        if note:
            text += B.note(f"{E('warn')} last watchdog error: {rich.esc(truncate(note, 120))}")
        await rich.send(client, message.chat.id, text, reply_to=message.id)


__all__ = ["TIMERS", "register"]
