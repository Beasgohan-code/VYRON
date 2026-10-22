# ---------------------------------------------------------------------------
#  VYRON — play / download commands
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.core.pending import put as remember_search
from vyron.core.queue import Track
from vyron.core.search import MediaError, looks_like_url
from vyron.runtime import runtime
from vyron.ui import cards, keyboards, rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.filters import control
from vyron.utils.helpers import command_args, display_name, track_from_message
from vyron.utils.net import fetch_bytes

logger = logging.getLogger(__name__)

USAGE = (
    f"{E('info')} <b>How to use</b>\n"
    f"<blockquote><code>/play believer</code>\n"
    f"<code>/play https://youtu.be/…</code>\n"
    f"<code>/song …</code> — send an MP3\n"
    f"<code>/video …</code> — send an MP4</blockquote>"
)


def _player():
    return runtime.require_player()


def _too_long(track: Track) -> bool:
    limit = runtime.settings.max_track_minutes
    return bool(limit and track.duration and track.duration > limit * 60)


def _too_long_text(track: Track) -> str:
    return cards.warn_card(
        f"<b>Skipping too-long track</b>\n<blockquote>{rich.esc(truncate(track.title, 52))} "
        f"is longer than the {runtime.settings.max_track_minutes} min limit.</blockquote>"
    )


async def _thinking(client: Client, message: Message, text: str):
    return await rich.send(
        client,
        message.chat.id,
        f"{E('clock')} <b>{text}</b>",
        reply_to=message.id,
        editable=True,
    )


async def _edit(client: Client, chat_id: int, message_id: int | None, markup: str, keyboard=None) -> None:
    if message_id:
        await rich.edit(client, chat_id, message_id, markup, markup_keyboard=keyboard)


def register(client: Client) -> None:
    # ── /play /vplay ───────────────────────────────────────────────────────
    @client.on_message(filters.command(["play", "p", "vplay", "vp"]))
    async def _play_cmd(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        command = message.command[0].lower()
        video = command in {"vplay", "vp"}
        chat_id = message.chat.id
        query = command_args(message)
        reply = message.reply_to_message
        requester = (
            message.from_user.id if message.from_user else 0,
            display_name(message.from_user),
        )

        # 1) reply to a Telegram media file → stream the file itself
        if reply and not query:
            media_track = track_from_message(message)
            if media_track:
                if not runtime.streaming_ready:
                    await rich.send(client, chat_id, cards.error_card("Voice streaming is not configured."))
                    return
                status = await _thinking(client, message, "Downloading from Telegram…")
                try:
                    media = reply.audio or reply.voice or reply.video or reply.document
                    target = Path(runtime.settings.downloads_dir) / f"tg-{media_track.id}{_suffix(media)}"
                    path = await client.download_media(reply, file_name=str(target))
                    if not path:
                        raise MediaError("The file could not be downloaded.")
                    media_track.url = str(path)
                    media_track.source = "telegram"
                    media_track.requested_by, media_track.requested_name = requester
                    await runtime.player.play_track(chat_id, media_track, video=video)
                    await _edit(client, chat_id, status.id if status else None,
                                cards.started_card(media_track))
                except Exception as exc:
                    await _edit(
                        client,
                        chat_id,
                        status.id if status else None,
                        cards.error_card(f"<b>Could not play that file</b>\n<blockquote>{truncate(str(exc), 160)}</blockquote>"),
                    )
                return

        if not query:
            await rich.send(client, chat_id, USAGE, reply_to=message.id)
            return

        # 2) direct link → resolve and start immediately
        if looks_like_url(query):
            status = await _thinking(client, message, "Resolving link…")
            try:
                track = await runtime.youtube.resolve(query, requester=requester)
                if _too_long(track):
                    await _edit(client, chat_id, status.id if status else None, _too_long_text(track))
                    return
                position = await _player().enqueue(
                    chat_id, track, video=video, play_now=True
                )
                await _edit(
                    client,
                    chat_id,
                    status.id if status else None,
                    cards.started_card(track) if position == 1 else cards.queued_card(track, position),
                )
            except MediaError as exc:
                await _edit(
                    client,
                    chat_id,
                    status.id if status else None,
                    cards.error_card(f"<b>Nothing playable there</b>\n<blockquote>{truncate(str(exc), 160)}</blockquote>"),
                )
            except Exception as exc:
                logger.warning("play link failed: %s", exc)
            return

        # 3) text query → search picker
        status = await _thinking(client, message, "Searching YouTube…")
        try:
            tracks = await runtime.youtube.search(query, requester=requester)
        except MediaError as exc:
            await _edit(client, chat_id, status.id if status else None,
                        cards.error_card(f"<b>No results</b>\n<blockquote>{truncate(str(exc), 160)}</blockquote>"))
            return
        if status:
            remember_search(
                chat_id,
                status.id,
                message.from_user.id if message.from_user else 0,
                query,
                tracks,
                mode="play",
                video=video,
            )
        await _edit(
            client,
            chat_id,
            status.id if status else None,
            cards.search_card(query, tracks),
            keyboards.search_results(tracks),
        )

    # ── /song /video ───────────────────────────────────────────────────────
    @client.on_message(filters.command(["song", "audio", "mp3", "video", "mp4", "dl", "download"]))
    async def _download_cmd(_: Client, message: Message) -> None:
        command = message.command[0].lower()
        want_video = command in {"video", "mp4"}
        query = command_args(message)
        chat_id = message.chat.id
        if not query:
            await rich.send(client, chat_id, USAGE, reply_to=message.id)
            return

        status = await _thinking(client, message, "Searching…")
        requester = (
            message.from_user.id if message.from_user else 0,
            display_name(message.from_user),
        )
        try:
            if looks_like_url(query):
                tracks = [await runtime.youtube.resolve(query, requester=requester)]
            else:
                tracks = await runtime.youtube.search(query, requester=requester)
        except MediaError as exc:
            await _edit(client, chat_id, status.id if status else None,
                        cards.error_card(f"<b>No results</b>\n<blockquote>{truncate(str(exc), 160)}</blockquote>"))
            return

        if status:
            remember_search(
                chat_id,
                status.id,
                message.from_user.id if message.from_user else 0,
                query,
                tracks,
                mode="download",
                video=want_video,
            )

        if len(tracks) == 1:
            await deliver(
                client,
                chat_id,
                tracks[0],
                want_video,
                status_id=status.id if status else None,
                reply_to=message.id,
            )
        else:
            await _edit(
                client,
                chat_id,
                status.id if status else None,
                cards.search_card(query, tracks)
                + "\n<footer>Choose a result, then pick a format.</footer>",
                keyboards.results_page(tracks),
            )

    # ── /search ────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["search", "find"]))
    async def _search_cmd(_: Client, message: Message) -> None:
        query = command_args(message)
        if not query:
            await rich.send(client, message.chat.id, USAGE, reply_to=message.id)
            return
        status = await _thinking(client, message, "Searching…")
        requester = (
            message.from_user.id if message.from_user else 0,
            display_name(message.from_user),
        )
        try:
            tracks = await runtime.youtube.search(query, requester=requester, limit=5)
        except MediaError as exc:
            await _edit(client, message.chat.id, status.id if status else None,
                        cards.error_card(f"<b>No results</b>\n<blockquote>{truncate(str(exc), 160)}</blockquote>"))
            return
        if status:
            remember_search(
                message.chat.id,
                status.id,
                message.from_user.id if message.from_user else 0,
                query,
                tracks,
            )
        await _edit(
            client,
            message.chat.id,
            status.id if status else None,
            cards.search_card(query, tracks),
            keyboards.search_results(tracks),
        )

    # ── /playlist ──────────────────────────────────────────────────────────
    @client.on_message(filters.command(["playlist", "ytpl"]))
    async def _playlist_cmd(_: Client, message: Message) -> None:
        query = command_args(message)
        if not query or not looks_like_url(query):
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    "Send a YouTube playlist or mix link: <code>/playlist https://…</code>\n"
                    "<blockquote>Looking for your own saved lists? <code>/playlists</code></blockquote>"
                ),
                reply_to=message.id,
            )
            return
        status = await _thinking(client, message, "Loading playlist…")
        try:
            title, tracks = await runtime.youtube.playlist(query, limit=50)
        except MediaError as exc:
            await _edit(client, message.chat.id, status.id if status else None,
                        cards.error_card(f"<b>Playlist failed</b>\n<blockquote>{truncate(str(exc), 160)}</blockquote>"))
            return

        requester = (
            message.from_user.id if message.from_user else 0,
            display_name(message.from_user),
        )
        player = _player()
        state = player.queues.get(message.chat.id)
        started = not state.playing and state.current is None
        queued = 0
        for track in tracks:
            track.requested_by, track.requested_name = requester
            position = await player.enqueue(
                message.chat.id, track, play_now=started and queued == 0
            )
            if position > 0:
                queued += 1
        markup = (
            f"{E('queue')} <b>{truncate(title, 50)}</b>\n"
            f"<blockquote>{E('note')} {queued} tracks queued "
            f"{'— playback started' if started else ''}</blockquote>"
        )
        await _edit(client, message.chat.id, status.id if status else None, markup)


def _suffix(media) -> str:
    name = getattr(media, "file_name", "") or ""
    if "." in name:
        return "." + name.rsplit(".", 1)[-1]
    return "." + (getattr(media, "mime_type", "") or "audio/mpeg").split("/")[-1][:5]


async def deliver(
    client: Client,
    chat_id: int,
    track: Track,
    want_video: bool,
    *,
    status_id: int | None = None,
    reply_to: int | None = None,
) -> None:
    """Download a track and send it as a real Telegram file."""
    markup = cards.download_card(track, "video" if want_video else "audio")
    await _edit(client, chat_id, status_id, markup)

    try:
        path = (
            await runtime.downloader.video(track)
            if want_video
            else await runtime.downloader.audio(track)
        )
    except Exception as exc:
        await _edit(
            client,
            chat_id,
            status_id,
            cards.error_card(
                f"<b>Download failed</b>\n<blockquote>{truncate(str(exc), 170)}</blockquote>"
            ),
        )
        return

    thumb = await fetch_bytes(track.thumbnail)
    caption = (
        f"{E('song')} <b>{rich.esc(truncate(track.title, 60))}</b>\n"
        f"{E('microphone')} {rich.esc(truncate(track.uploader, 40) or 'unknown')}"
    )
    try:
        if want_video:
            await client.send_video(
                chat_id,
                str(path),
                caption=caption,
                duration=track.duration or None,
                thumb=thumb,
                supports_streaming=True,
                reply_to_message_id=reply_to,
            )
        else:
            await client.send_audio(
                chat_id,
                str(path),
                caption=caption,
                title=track.title[:64],
                performer=(track.uploader or "VYRON")[:64],
                duration=track.duration or None,
                thumb=thumb,
                reply_to_message_id=reply_to,
            )
        if runtime.storage:
            await runtime.storage.bump("downloads")
        if status_id:
            try:
                await client.delete_messages(chat_id, status_id)
            except Exception:
                pass
    except Exception as exc:
        logger.warning("send file failed: %s", exc)
        await _edit(
            client,
            chat_id,
            status_id,
            cards.error_card(
                f"<b>Upload failed</b>\n<blockquote>{truncate(str(exc), 170)}</blockquote>"
            ),
        )


__all__ = ["deliver", "register"]
