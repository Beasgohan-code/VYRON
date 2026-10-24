# ---------------------------------------------------------------------------
#  VYRON — play / download commands
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from pathlib import Path

from pyrogram import Client
from pyrogram.enums import ChatType
from pyrogram.types import Message

from vyron.core import chatcfg, metasources
from vyron.core.pending import put as remember_search
from vyron.core.player import StreamError
from vyron.core.queue import Track
from vyron.core.search import MediaError, looks_like_url
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import cards, keyboards, rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.helpers import (
    command_args,
    display_name,
    is_chat_admin,
    is_owner,
    media_suffix,
    track_from_message,
)
from vyron.utils.net import fetch_bytes
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)

USAGE = (
    f"{E('info')} <b>How to use</b>\n"
    f"<blockquote><code>/play believer</code>\n"
    f"<code>/play https://youtu.be/…</code>\n"
    f"reply to any audio / video / file with <code>/play</code>\n"
    f"<code>/song …</code> — get the file instead</blockquote>\n"
    f"<footer>{E('spark')} audio or video is detected automatically</footer>"
)


def _player():
    return runtime.require_player()


async def may_request(client: Client, message: Message) -> bool:
    """Honour the chat's play mode.

    BadMusic calls this *playmode*: by default anyone may request a song, but a
    group can switch to "admins only" — useful once a 200-person group finds
    the bot. Private chats are never restricted, and the owner always is not.
    """
    chat = message.chat
    if chat is None or chat.type == ChatType.PRIVATE:
        return True
    if not await chatcfg.get(chat.id, "admins_only", False):
        return True
    user = message.from_user
    uid = user.id if user else 0
    if is_owner(uid) or await is_chat_admin(client, chat.id, uid):
        return True
    await rich.send(
        client,
        chat.id,
        cards.warn_card(
            "<b>Admins only here</b>\n"
            "<blockquote>An admin can open this up in <code>/settings</code> → "
            "<i>who can play</i>.</blockquote>"
        ),
        reply_to=message.id,
    )
    return False


def _too_long(track: Track) -> bool:
    limit = runtime.settings.max_track_minutes
    return bool(limit and track.duration and track.duration > limit * 60)


def _too_long_text(track: Track) -> str:
    return cards.warn_card(
        f"<b>Skipping too-long track</b>\n<blockquote>{rich.esc(truncate(track.title, 52))} "
        f"is longer than the {runtime.settings.max_track_minutes} min limit.</blockquote>"
    )


async def _thinking(client: Client, message: Message, text: str):
    # Editable (classic HTML) lane, so no rich-only tags here — an expandable
    # blockquote keeps the card compact and collapses to one tidy line.
    return await rich.send(
        client,
        message.chat.id,
        f"{E('clock')} <b>{text}</b>\n"
        f"<blockquote>{E('spark')} <i>give it a moment — VYRON is on it</i></blockquote>",
        reply_to=message.id,
        editable=True,
    )


async def _edit(client: Client, chat_id: int, message_id: int | None, markup: str, keyboard=None) -> None:
    if message_id:
        await rich.edit(client, chat_id, message_id, markup, markup_keyboard=keyboard)


def _honest_kind(requested_video: bool, chat_id: int) -> str:
    """Say it out loud when a video request ends up playing as audio.

    A walled YouTube has no video to give, and the player falls back to the
    same song from a catalogue. Silence there looks like a bug, so the card
    says what happened instead.
    """
    if not requested_video or runtime.player is None:
        return ""
    state = runtime.player.queues.get(chat_id)
    if state is not None and not state.is_video:
        return (
            "No video from this server right now — playing the same song as audio."
        )
    return ""


def register(client: Client) -> None:
    # ── /play ──────────────────────────────────────────────────────────────
    # One command, three inputs (text, link, replied file) and no format
    # questions: the track carries `is_video` and the player streams whatever
    # it is. There is deliberately no `/playforce` — an admin who wants to cut
    # in can `/skip` first.
    @client.on_message(cmd(["play"]))
    async def _play_cmd(_: Client, message: Message) -> None:
        if not runtime.player or not await may_request(client, message):
            return
        video = False  # replaced by the detected kind below
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
                    await rich.send(
                        client,
                        chat_id,
                        cards.error_card(
                            "<b>Voice engine is off</b>\n"
                            "<blockquote>Add <code>STRING_SESSION</code> to stream into a "
                            "voice chat, or send <code>/song &lt;query&gt;</code> for an MP3.</blockquote>"
                        ),
                        reply_to=message.id,
                    )
                    return
                status = await _thinking(client, message, "Downloading from Telegram…")
                try:
                    media = reply.audio or reply.voice or reply.video or reply.document
                    target = Path(runtime.settings.downloads_dir) / f"tg-{media_track.id}{media_suffix(media)}"
                    path = await client.download_media(reply, file_name=str(target))
                    if not path:
                        raise MediaError("The file could not be downloaded.")
                    media_track.url = str(path)
                    media_track.source = "telegram"
                    media_track.requested_by, media_track.requested_name = requester
                    # A replied video plays as video, a voice note as audio —
                    # the kind came from `track_from_message`, not a command.
                    await runtime.player.play_track(
                        chat_id, media_track, video=media_track.is_video
                    )
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

        # 2a) catalogue album/playlist (Spotify, Deezer, Apple Music) → queue it
        if looks_like_url(query) and metasources.is_catalogue_link(query):
            status = await _thinking(client, message, "Reading that link…")
            collection = None
            try:
                collection = await runtime.youtube.resolve_collection(
                    query, limit=25, requester=requester
                )
            except Exception as exc:  # pragma: no cover - network paths
                logger.info("catalogue collection failed: %s", exc)
            if collection:
                title, tracks = collection
                player = _player()
                state = player.queues.get(chat_id)
                started = not state.playing and state.current is None
                queued = 0
                for track in tracks:
                    track.requested_by, track.requested_name = requester
                    position = await player.enqueue(
                        chat_id, track, play_now=started and queued == 0
                    )
                    if position > 0:
                        queued += 1
                await _edit(
                    client,
                    chat_id,
                    status.id if status else None,
                    cards.started_card(tracks[0])
                    if started and queued
                    else f"{E('queue')} <b>{rich.esc(truncate(title, 44))}</b>\n"
                    f"<blockquote>{E('note')} {queued} tracks queued</blockquote>",
                )
                return

        # 2b) direct link → resolve and start immediately
        if looks_like_url(query):
            status = await _thinking(client, message, "Resolving link…")
            try:
                track = await runtime.youtube.resolve(query, requester=requester)
                if _too_long(track):
                    await _edit(client, chat_id, status.id if status else None, _too_long_text(track))
                    return
                outcome = await begin(
                    client,
                    chat_id,
                    track,
                    video=track.is_video,
                    status_id=status.id if status else None,
                    reply_to=message.id,
                )
                if outcome != "error":
                    await _edit(
                        client,
                        chat_id,
                        status.id if status else None,
                        cards.started_card(
                            track, note=_honest_kind(bool(track.is_video), chat_id)
                        )
                        if outcome == "streamed"
                        else cards.queued_card(track, 0),
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

    # ── /song (the file, one command) ──────────────────────────────────────
    @client.on_message(cmd(["song"]))
    async def _download_cmd(_: Client, message: Message) -> None:
        if not await may_request(client, message):
            return
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
                video=tracks[0].is_video if len(tracks) == 1 else False,
            )

        if len(tracks) == 1:
            await deliver(
                client,
                chat_id,
                tracks[0],
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
    @client.on_message(cmd(["search"]))
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
    @client.on_message(cmd(["playlist"]))
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


async def begin(
    client: Client,
    chat_id: int,
    track: Track,
    *,
    video: bool | None = None,
    status_id: int | None = None,
    reply_to: int | None = None,
) -> str:
    """Play *track* into the voice chat.

    Streaming is the product: a missing voice engine or a dead link is reported
    as such instead of quietly turning /play into a file upload. ``/song`` is
    the explicit way to get a file.

    Returns ``"streamed"``, ``"queued"`` or ``"error"`` (the error card is
    already on screen when this returns).
    """
    if runtime.calls is None:
        await _edit(
            client,
            chat_id,
            status_id,
            cards.error_card(
                "<b>Voice engine is off</b>\n"
                "<blockquote>Playback needs the assistant account. Add "
                "<code>STRING_SESSION</code> (generate one with "
                "<code>python -m vyron.tools.session</code>) and restart. "
                "Use <code>/song</code> if you want a file.</blockquote>"
            ),
        )
        return "error"
    # Auto-detect: a video source streams video, everything else audio.
    if video is None:
        video = bool(track.is_video)
    try:
        position = await _player().enqueue(chat_id, track, video=video, play_now=True)
    except StreamError as exc:
        logger.info("stream unavailable: %s", exc)
        await _edit(
            client,
            chat_id,
            status_id,
            cards.error_card(
                f"<b>Could not stream that</b>\n<blockquote>{truncate(str(exc), 170)}</blockquote>"
                "\n<footer>the same track as a file: <code>/song</code></footer>"
            ),
        )
        return "error"
    return "streamed" if position == 1 else "queued"


async def deliver(
    client: Client,
    chat_id: int,
    track: Track,
    want_video: bool | None = None,
    *,
    status_id: int | None = None,
    reply_to: int | None = None,
    hint: str | None = None,
) -> None:
    """Download a track and send it as a real Telegram file.

    The container is detected, not asked for: audio first (that is what
    ``/song`` means), and when the source has no audio-only stream at all — a
    video-only link, a replied video — the video file is sent instead. An
    explicit ``want_video`` still wins, because the inline buttons offer the
    choice.
    """
    if want_video is None:
        want_video = False
    markup = cards.download_card(track, "video" if want_video else "audio")
    if hint:
        markup = B.note(hint) + markup
    await _edit(client, chat_id, status_id, markup)

    path = None
    if not want_video:
        try:
            path = await runtime.downloader.audio(track)
        except Exception as exc:
            # A video-only source: the honest answer is the video, not an error.
            if not (track.is_video or track.url):
                await _edit(
                    client,
                    chat_id,
                    status_id,
                    cards.error_card(
                        f"<b>Download failed</b>\n<blockquote>{truncate(str(exc), 170)}</blockquote>"
                    ),
                )
                return
            logger.info("audio download failed for %s, trying video: %s", track.id, exc)
    if path is None:
        try:
            path = await runtime.downloader.video(track)
            want_video = True
            await _edit(client, chat_id, status_id, cards.download_card(track, "video"))
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


__all__ = ["begin", "deliver", "may_request", "register"]
