# ---------------------------------------------------------------------------
#  VYRON — smart queue
#
#  /suggest  — tracks similar to whatever is playing (or to a query)
#  /next <q> — insert the next track to play, ahead of the queue
#  /qinfo    — a one-glance health view of the current queue
#
#  Built on VYRON's queue / search / rich-card layers.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core import pending
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import fmt_duration, human_time, truncate
from vyron.ui.theme import E
from vyron.utils.helpers import command_args

logger = logging.getLogger(__name__)


def _picker(query: str, tracks, prefix: str = "v:p") -> str:
    buttons = [
        B.btn(
            f"{index + 1}. {rich.esc(truncate(track.title, 18))}",
            data=f"{prefix}:{index}",
            style="primary" if index == 0 else None,
        )
        for index, track in enumerate(tracks)
    ]
    return B.grid(buttons, columns=2)


def register(client: Client) -> None:
    # ── /suggest ───────────────────────────────────────────────────────────
    @client.on_message(filters.command(["suggest", "similar", "upnext"]))
    async def _suggest(_: Client, message: Message) -> None:
        if not runtime.youtube:
            return
        seed_query = command_args(message)
        state = runtime.player.queues.get(message.chat.id) if runtime.player else None
        seed_track = None if seed_query else (state.current if state else None)

        if not seed_query and seed_track is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('moon')} Nothing is playing. "
                    f"Try <code>/suggest lofi hip hop</code>."
                ),
                reply_to=message.id,
            )
            return

        query = seed_query or f"{seed_track.title} {seed_track.uploader}".strip()
        status = await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('search')} finding similar", 3)
            + B.note(f"{B.think()} Looking for tracks like <b>{rich.esc(truncate(query, 46))}</b>"),
            reply_to=message.id,
            editable=True,
        )
        if status is None:
            return

        try:
            found = (
                await runtime.youtube.search(query, limit=6)
                if seed_track is None
                else await runtime.youtube.related(seed_track, limit=6)
            )
        except Exception as exc:
            await rich.edit(
                client,
                message.chat.id,
                status.id,
                B.note(f"{E('warn')} {rich.esc(truncate(str(exc), 160))}"),
            )
            return

        if not found:
            await rich.edit(
                client,
                message.chat.id,
                status.id,
                B.note(f"{E('info')} No similar tracks found for that."),
            )
            return

        pending.put(
            message.chat.id,
            status.id,
            message.from_user.id if message.from_user else 0,
            query,
            found,
            mode="play",
        )

        markup = (
            B.heading(f"{E('spark')} up next", 3)
            + B.note(
                f"{E('note')} Suggestions for <b>{rich.esc(truncate(query, 44))}</b>"
                " • pick one to queue it"
            )
            + B.table(
                ["#", "track", "time"],
                [
                    (
                        f"<b>{index + 1}</b>",
                        rich.esc(truncate(track.title, 38)),
                        fmt_duration(track.duration),
                    )
                    for index, track in enumerate(found)
                ],
            )
            + _picker(query, found)
            + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
        )
        await rich.edit(client, message.chat.id, status.id, markup)

    # ── /next <query> ──────────────────────────────────────────────────────
    @client.on_message(filters.command(["playnext", "next"]) & filters.regex(r"^/\w+\s+\S"))
    async def _play_next(_: Client, message: Message) -> None:
        if not runtime.player or not runtime.youtube:
            return
        query = command_args(message)
        if not query:
            return
        requester = (
            message.from_user.id if message.from_user else 0,
            (message.from_user.first_name if message.from_user else "") or "",
        )
        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} {B.think()} <b>Queuing next…</b>",
            reply_to=message.id,
            editable=True,
        )
        try:
            track = await runtime.youtube.resolve(query, requester=requester)
            position = await runtime.player.enqueue(message.chat.id, track, index=0)
        except Exception as exc:
            if status:
                await rich.edit(
                    client,
                    message.chat.id,
                    status.id,
                    B.note(f"{E('warn')} {rich.esc(truncate(str(exc), 160))}"),
                )
            return
        if status:
            await rich.edit(
                client,
                message.chat.id,
                status.id,
                B.note(f"{E('check')} <b>Playing next</b>")
                + B.kv(
                    [
                        ("track", rich.esc(truncate(track.title, 42))),
                        ("artist", rich.esc(truncate(track.uploader, 30))),
                        ("position", "<b>#1</b>" if position > 0 else "<b>duplicate</b>"),
                    ]
                ),
            )

    # ── /qinfo ─────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["queueinfo", "qinfo"]))
    async def _queueinfo(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        state = runtime.player.queues.get(message.chat.id)
        remaining = state.remaining() if state.current else 0
        remaining += sum(track.duration for track in state.queue)
        markup = B.heading(f"{E('queue')} queue health", 3) + B.kv(
            [
                (f"{E('queue')} queued", f"<b>{len(state.queue)}</b> tracks"),
                (f"{E('clock')} remaining", f"<b>{human_time(remaining)}</b>"),
                (f"{E('loop')} loop", f"<b>{state.loop.label}</b>"),
                (f"{E('spark')} autoplay", f"<b>{'on' if state.autoplay else 'off'}</b>"),
                (f"{E('bolt')} effects", f"<b>{', '.join(state.effects) or 'off'}</b>"),
                (f"{E('volume')} volume", f"<b>{state.volume}%</b>"),
            ]
        )
        if state.current:
            markup += B.note(
                f"{E('note')} <b>{rich.esc(truncate(state.current.title, 44))}</b>\n"
                f"{E('clock')} {fmt_duration(state.elapsed())} / {fmt_duration(state.current.duration)}"
            )
        await rich.send(client, message.chat.id, markup, reply_to=message.id)


__all__ = ["register"]
