# ---------------------------------------------------------------------------
#  VYRON — callback router (every inline button lands here)
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery

from vyron.core import pending
from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import cards, keyboards, rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.utils.helpers import is_chat_admin, is_owner, is_private_chat

logger = logging.getLogger(__name__)

_CONTROL_ACTIONS = {
    "pause", "resume", "skip", "stop", "loop", "shuffle", "queue",
    "clearqueue", "vol", "set", "pick", "get", "dl", "lock", "fx",
}


async def _authorized(client: Client, cq: CallbackQuery, action: str) -> bool:
    if action not in _CONTROL_ACTIONS:
        return True
    message = cq.message
    if message is None or cq.from_user is None:
        return False
    if message.chat.type == ChatType.PRIVATE:
        return True
    if is_owner(cq.from_user.id):
        return True
    return await is_chat_admin(client, message.chat.id, cq.from_user.id)


async def _show(client: Client, cq: CallbackQuery, markup: str, keyboard=None) -> None:
    if cq.message is None:
        return
    await rich.edit(
        client,
        cq.message.chat.id,
        cq.message.id,
        markup,
        markup_keyboard=keyboard,
    )


def register(client: Client) -> None:
    @client.on_callback_query(filters.regex(r"^v:"))
    async def _router(_: Client, cq: CallbackQuery) -> None:
        try:
            await _dispatch(client, cq)
        except Exception as exc:  # never let a button break the bot
            logger.exception("callback failed: %s", exc)
            try:
                await cq.answer("Something went wrong — try again.", show_alert=True)
            except Exception:
                pass

    async def _dispatch(client: Client, cq: CallbackQuery) -> None:
        parts = (cq.data or "").split(":")
        action = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""
        chat = cq.message.chat if cq.message else None
        if chat is None:
            return

        if not await _authorized(client, cq, action):
            await cq.answer("Only group admins can control playback.", show_alert=True)
            return

        player = runtime.player
        if player is None:
            await cq.answer("Player is still starting up…")
            return
        state = player.queues.get(chat.id)

        # ── navigation ─────────────────────────────────────────────────────
        if action == "noop":
            await cq.answer()
            return

        if action == "close":
            try:
                await cq.message.delete()
            except Exception:
                await cq.answer()
            return

        if action == "help":
            section = arg or "main"
            await _show(client, cq, cards.help_card(section), keyboards.help_nav(section))
            await cq.answer()
            return

        if action == "about":
            await _show(client, cq, cards.about_card(), keyboards.back_close("v:help:main"))
            await cq.answer()
            return

        # ── entry buttons (welcome card, quick actions) ────────────────────
        if action == "play":
            query = ":".join(parts[2:]).strip()
            if not query or runtime.youtube is None:
                await cq.answer("Nothing to play.", show_alert=True)
                return
            try:
                from vyron.modules.play import begin

                track = await runtime.youtube.resolve(
                    query,
                    requester=(
                        cq.from_user.id if cq.from_user else 0,
                        (cq.from_user.first_name if cq.from_user else "") or "",
                    ),
                )
                outcome = await begin(client, chat.id, track, status_id=cq.message.id)
                await cq.answer(
                    {
                        "streamed": f"Playing · {truncate(track.title, 26)}",
                        "queued": f"Queued · {truncate(track.title, 26)}",
                        "file": "Sending the file…",
                    }[outcome]
                )
            except Exception as exc:
                await cq.answer(f"Could not play that: {truncate(str(exc), 60)}", show_alert=True)
            return

        if action == "app":
            if not settings.webapp_url:
                await cq.answer("Set WEBAPP_URL first.", show_alert=True)
                return
            owner_token = ""
            if (
                cq.from_user
                and cq.from_user.id in settings.owners
                and settings.bot_token
                and is_private_chat(chat)
            ):
                from vyron.web.auth import make_owner_token

                owner_token = make_owner_token(settings.bot_token, cq.from_user.id)
            await _show(
                client,
                cq,
                cards.webapp_card(settings.webapp_url, chat.title or "", owner_token=owner_token),
                keyboards.back_close("v:help:main"),
            )
            await cq.answer()
            return

        if action == "settings":
            cfg = await runtime.storage.chat_settings(chat.id) if runtime.storage else {}
            await _show(client, cq, cards.settings_card(cfg, chat.title or ""),
                        keyboards.back_close("v:np"))
            await cq.answer()
            return

        if action == "vote":
            from vyron.modules.power import cast_vote

            if cq.from_user is None:
                await cq.answer()
                return
            outcome, tally, needed, _state = await cast_vote(chat.id, cq.from_user.id)
            if outcome == "disabled":
                await cq.answer("Vote-skip is off — an admin can enable it.", show_alert=True)
                return
            if outcome == "duplicate":
                await cq.answer(f"You already voted · {tally.remaining} more needed")
                return
            if outcome == "passed":
                skipped = await player.skip(chat.id, count=1)
                await cq.answer("Skipped by vote!" if skipped else "Queue is empty")
                return
            await cq.answer(f"Vote counted · {tally.count}/{needed}")
            return

        if action == "np":
            if not state or not state.current:
                await cq.answer("Nothing is playing.", show_alert=True)
                return
            await _show(client, cq, cards.now_playing_card(state), keyboards.now_playing(state))
            await cq.answer()
            return

        # ── queue ──────────────────────────────────────────────────────────
        if action == "queue":
            page = int(arg) if arg.isdigit() else 0
            markup, pages = cards.queue_card(state, page)
            await _show(client, cq, markup, keyboards.queue(state, min(page, pages - 1), pages))
            await cq.answer()
            return

        if action == "clearqueue":
            removed = player.queues.clear(chat.id, keep_current=True)
            await player.refresh_now_playing(chat.id)
            await cq.answer(f"Cleared {removed} tracks")
            return

        # ── transport ──────────────────────────────────────────────────────
        if action == "pause":
            await cq.answer("Paused" if await player.pause(chat.id) else "Nothing to pause")
            return

        if action == "resume":
            await cq.answer("Resumed" if await player.resume(chat.id) else "Nothing is paused")
            return

        if action == "skip":
            track = await player.skip(chat.id)
            await cq.answer(
                f"⏭ {truncate(track.title, 40)}" if track else "Queue is empty"
            )
            return

        if action == "stop":
            await player.stop(chat.id, leave=True)
            await cq.answer("Stopped and left the voice chat")
            try:
                await cq.message.delete()
            except Exception:
                pass
            return

        if action == "loop":
            state.loop = state.loop.next()
            await player.persist(chat.id)
            await player.refresh_now_playing(chat.id)
            await cq.answer(f"Loop: {state.loop.label}")
            return

        if action == "shuffle":
            count = player.queues.shuffle(chat.id)
            await player.refresh_now_playing(chat.id)
            await cq.answer(f"Shuffled {count} tracks")
            return

        if action == "vol":
            if arg == "show":
                await cq.answer(f"Volume: {state.volume}%")
                return
            delta = int(arg) if arg.lstrip("+-").isdigit() else 0
            volume = await player.set_volume(chat.id, state.volume + delta)
            await cq.answer(f"Volume: {volume}%")
            return

        # ── settings ───────────────────────────────────────────────────────
        if action == "set":
            if arg == "loop":
                state.loop = state.loop.next()
            elif arg == "autoplay":
                state.autoplay = not state.autoplay
            elif arg == "always":
                state.always_on = not state.always_on
            await player.persist(chat.id)
            cfg = {
                "volume": state.volume,
                "loop": state.loop.value,
                "autoplay": state.autoplay,
                "always_on": state.always_on,
            }
            await _show(
                client,
                cq,
                cards.settings_card(cfg, chat.title or ""),
                keyboards.settings_panel(cfg),
            )
            await cq.answer("Saved")
            return

        # ── favourites / lyrics ────────────────────────────────────────────
        if action == "fav":
            if not state or not state.current:
                await cq.answer("Nothing is playing.", show_alert=True)
                return
            added = await runtime.storage.add_favorite(cq.from_user.id, state.current.to_dict())
            await cq.answer("Saved to favourites" if added else "Already saved")
            return

        if action == "lyrics":
            await _lyrics(client, cq, state)
            return

        # ── search results ─────────────────────────────────────────────────
        if action in {"pick", "dl"}:
            entry = pending.get(chat.id, cq.message.id)
            if not entry or not arg.isdigit() or int(arg) >= len(entry.tracks):
                await cq.answer("That search expired — run the command again.", show_alert=True)
                return
            index = int(arg)
            if action == "dl":
                await _show(client, cq, cards.download_choice_card(entry.tracks[index]))
                await cq.answer()
                return

            from vyron.modules.play import begin

            track = entry.tracks[index]
            outcome = await begin(
                client,
                chat.id,
                track,
                video=entry.video,
                status_id=cq.message.id,
            )
            if outcome != "file":
                await _show(
                    client,
                    cq,
                    cards.started_card(track) if outcome == "streamed" else cards.queued_card(track, 0),
                    keyboards.now_playing(state),
                )
            await cq.answer(
                {"streamed": "Starting", "queued": "Queued", "file": "Sending the file…"}[outcome]
            )
            return

        if action == "get":
            entry = pending.get(chat.id, cq.message.id)
            kind = parts[2] if len(parts) > 2 else "audio"
            index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            if not entry or index >= len(entry.tracks):
                await cq.answer("That result expired.", show_alert=True)
                return
            from vyron.modules.play import deliver

            await cq.answer("Downloading…")
            await deliver(
                client,
                chat.id,
                entry.tracks[index],
                kind == "video",
                status_id=cq.message.id,
            )
            return

        # ── locks panel ────────────────────────────────────────────────────
        if action == "lock":
            from vyron.core import chatcfg
            from vyron.modules.locks import locks_panel

            locks_cfg = await chatcfg.get(chat.id, "locks", {})
            flood_cfg = await chatcfg.get(chat.id, "flood", {})
            if arg == "flood":
                flood_cfg["enabled"] = not flood_cfg.get("enabled", True)
                await chatcfg.set(chat.id, "flood", flood_cfg)
            elif arg in locks_cfg:
                locks_cfg[arg] = not locks_cfg.get(arg)
                await chatcfg.set(chat.id, "locks", locks_cfg)
            await _show(client, cq, locks_panel(locks_cfg, flood_cfg))
            await cq.answer("Saved")
            return

        # ── audio effects ──────────────────────────────────────────────────
        if action == "fx":
            from vyron.core import chatcfg, effects as audio_fx
            from vyron.modules.effects_cmd import panel as fx_panel

            active = audio_fx.resolve(await chatcfg.get(chat.id, "effects", []) or [])
            if arg == "off":
                active = []
            elif arg in audio_fx.EFFECTS:
                if arg in active:
                    active = [name for name in active if name != arg]
                else:
                    active = audio_fx.resolve(active + [arg])
            await chatcfg.set(chat.id, "effects", active)
            if player:
                player.queues.get(chat.id).effects = active
            await _show(client, cq, fx_panel(active))
            await cq.answer(f"Active: {audio_fx.labels(active)}")
            return

        # ── owner panel ────────────────────────────────────────────────────
        if action == "admin":
            if not is_owner(cq.from_user.id):
                await cq.answer("Owner only.", show_alert=True)
                return
            if arg == "stats":
                counters = await runtime.storage.counters()
                chunks = len(await runtime.storage.all_chat_ids())
                await _show(
                    client,
                    cq,
                    cards.stats_card(
                        uptime=runtime.uptime,
                        chats=chunks,
                        active=len(player.active_chats()),
                        tracks=counters.get("tracks", player.tracks_played),
                        downloads=counters.get("downloads", 0),
                        cache_bytes=runtime.downloader.cache_size(),
                        backend=runtime.storage.backend,
                        version=runtime.version,
                    ),
                    keyboards.admin_panel(),
                )
                await cq.answer()
                return
            if arg == "active":
                lines = [
                    f"• <code>{chat_id}</code> — {rich.esc(truncate(st.title, 36))}"
                    for chat_id in player.active_chats()
                    if (st := player.queues.get(chat_id)).current
                ]
                body = "\n".join(lines) or "<i>none</i>"
                await _show(
                    client,
                    cq,
                    f"{E('live')} <b>Active sessions</b>\n<blockquote>{body}</blockquote>",
                    keyboards.admin_panel(),
                )
                await cq.answer()
                return

        await cq.answer()

    async def _lyrics(client: Client, cq: CallbackQuery, state) -> None:
        if not state or not state.current:
            await cq.answer("Nothing is playing.", show_alert=True)
            return
        from vyron.core.lyrics import split_title

        await cq.answer("Fetching lyrics…")
        track = state.current
        title, artist = split_title(track.title)
        result = await runtime.lyrics.timed(title, artist or track.uploader, track.duration)
        await _show(
            client,
            cq,
            cards.lyrics_card(track, result),
            keyboards.back_close("v:np"),
        )


__all__ = ["register"]
