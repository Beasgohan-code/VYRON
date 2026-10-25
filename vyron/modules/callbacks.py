# ---------------------------------------------------------------------------
#  VYRON — callback router (every inline button lands here)
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery

from vyron.core import i18n, pending
from vyron.config import settings
from vyron.runtime import runtime
from vyron.ui import cards, keyboards, panels, rich
from vyron.ui.progress import fmt_duration, truncate
from vyron.ui.theme import E
from vyron.utils.helpers import is_chat_admin, is_owner, is_private_chat

logger = logging.getLogger(__name__)

_CONTROL_ACTIONS = {
    "pause", "resume", "skip", "stop", "loop", "shuffle", "queue",
    "clearqueue", "vol", "set", "pick", "get", "dl", "lock", "fx", "video",
    # `radio` persists a chat setting, so it follows the same rule as set.
    "radio",
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


async def _drop(client, chat_id: int, message_id: int | None) -> None:
    """Delete a card the now-playing picture has made redundant."""
    from vyron.ui.nowplaying import drop_message

    await drop_message(client, chat_id, message_id)


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
            if "QUERY_ID_INVALID" in str(exc).upper().replace(" ", "_"):
                # The tap was older than Telegram's answer window: nothing to
                # report, and nothing to fix — the user simply tapped again.
                logger.debug("stale button tap: %s", exc)
                return
            logger.exception("callback failed: %s", exc)
            await rich.answer(cq, "Something went wrong — try again.", show_alert=True)

    async def _dispatch(client: Client, cq: CallbackQuery) -> None:
        parts = (cq.data or "").split(":")
        action = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""
        chat = cq.message.chat if cq.message else None
        if chat is None:
            return

        if not await _authorized(client, cq, action):
            await rich.answer(cq, "Only group admins can control playback.", show_alert=True)
            return

        # These prefixes have their own routers (extras.py, logs_cmd.py). Answer
        # here too and Telegram rejects the second ack, so step aside entirely.
        if action in {"logs", "unblock"}:
            return

        # captcha buttons belong to a person, not to the player: handle them
        # before the player check so a booting bot can still verify people.
        if action == "captcha":
            from vyron.modules.groupadmin import verify_captcha

            await verify_captcha(client, cq, chat.id, arg)
            return

        # ── owner credentials (DM only) ────────────────────────────────────
        if action == "token":
            from vyron.core import tokens
            from vyron.core.musicapi import get_music_api

            actor = cq.from_user.id if cq.from_user else 0
            if not is_owner(actor) or not is_private_chat(chat):
                await rich.answer(cq, "Owner only, in a private chat.", show_alert=True)
                return
            if not settings.bot_token:
                await rich.answer(cq, "BOT_TOKEN is not set.", show_alert=True)
                return

            if arg == "revoke":
                # first tap asks, second tap does it — never a one-tap kill
                await _show(
                    client,
                    cq,
                    cards.confirm_card(
                        "Revoke every owner token?",
                        "Anywhere you pasted this token stops working immediately. "
                        "The Mini App is unaffected.",
                        confirm="v:token:confirm",
                        cancel="v:token:cancel",
                        danger=True,
                    ),
                )
                await rich.answer(cq)
                return

            if arg == "cancel":
                await _show(
                    client,
                    cq,
                    cards.notice_card(
                        "Nothing changed",
                        "Your token is still valid.",
                        tone="info",
                    ),
                )
                await rich.answer(cq)
                return

            if arg == "confirm":
                epoch = await tokens.revoke_all(actor)
                await _show(client, cq, cards.token_revoked_card(epoch=epoch))
                await rich.answer(cq, "Revoked")
                return

            if arg == "rotate":
                from vyron.web.auth import OWNER_TOKEN_TTL, make_owner_token

                epoch = await tokens.revoke_all(actor)
                token = make_owner_token(settings.bot_token, actor, epoch=epoch)
                roster = await get_music_api().keys(reveal=False)
                await _show(
                    client,
                    cq,
                    cards.token_card(
                        token,
                        base=settings.webapp_url or "",
                        owner_id=actor,
                        ttl_days=OWNER_TOKEN_TTL // 86400,
                        epoch=epoch,
                        active_keys=len([key for key in roster if key.get("active")]),
                    ),
                )
                await rich.answer(cq, "New token issued — the old one is dead")
                return

            if arg == "keys":
                roster = await get_music_api().keys(reveal=False)
                await _show(
                    client,
                    cq,
                    cards.api_keys_card(roster, base=settings.webapp_url or ""),
                )
                await rich.answer(cq)
                return

            await rich.answer(cq)
            return

        # ── API keys: revoke / rotate from the card ────────────────────────
        if action == "key":
            from vyron.core.musicapi import find_key, get_music_api

            actor = cq.from_user.id if cq.from_user else 0
            if not is_owner(actor):
                await rich.answer(cq, "Owner only.", show_alert=True)
                return
            identifier = ":".join(parts[3:])
            if not identifier:
                await rich.answer(cq, "Which key?", show_alert=True)
                return
            api = get_music_api()
            roster = await api.keys(reveal=False)
            target = find_key(roster, identifier)
            if target is None:
                await rich.answer(cq, "That key is gone already.", show_alert=True)
                return

            if arg == "revoke":
                done = await api.revoke(None, str(target.get("id") or identifier), force=True)
                roster = await api.keys(reveal=False)
                await _show(client, cq, cards.api_keys_card(roster, base=settings.webapp_url or ""))
                await rich.answer(cq, "Key revoked" if done else "Could not revoke")
                return

            if arg == "rotate":
                record, error = await api.rotate(actor, str(target.get("id") or identifier))
                roster = await api.keys(reveal=False)
                if record is None:
                    await rich.answer(cq, error or "Could not rotate", show_alert=True)
                    return
                await _show(
                    client,
                    cq,
                    cards.api_key_card(
                        key=str(record.get("key") or ""),
                        label=str(record.get("label") or "key"),
                        base=settings.webapp_url or "",
                        rate=int(record.get("rate_limit") or settings.music_api_rate),
                        scopes=record.get("scopes"),
                        expires_at=record.get("expires_at"),
                        owner_id=record.get("owner_id"),
                        key_id=str(record.get("id") or ""),
                    ),
                )
                await rich.answer(cq, "Rotated — copy the new key")
                return

            await rich.answer(cq)
            return

        # ── group manager panel (admins only) ──────────────────────────────
        if action == "grp":
            from vyron.core import chatcfg
            from vyron.modules.locks import locks_panel

            actor = cq.from_user.id if cq.from_user else 0
            if not actor or not (is_owner(actor) or await is_chat_admin(client, chat.id, actor)):
                await rich.answer(cq, "Admins only.", show_alert=True)
                return

            if arg == "locks" or arg == "flood":
                locks_cfg = await chatcfg.get(chat.id, "locks", {})
                flood_cfg = await chatcfg.get(chat.id, "flood", {})
                if arg == "flood":
                    flood_cfg["enabled"] = not flood_cfg.get("enabled", True)
                    await chatcfg.set(chat.id, "flood", flood_cfg)
                    await rich.answer(cq, "Anti-flood " + ("on" if flood_cfg["enabled"] else "off"))
                else:
                    await rich.answer(cq)
                await _show(client, cq, locks_panel(locks_cfg, flood_cfg))
                return

            if arg == "rules":
                admins = 0
                try:
                    admins = (await client.get_chat(chat.id)).admins_count or 0
                except Exception:
                    admins = 0
                await _show(
                    client,
                    cq,
                    cards.rules_card(
                        chat.title or "this chat",
                        await chatcfg.get(chat.id, "rules", "") or "",
                        admins=admins,
                        can_edit=True,
                    ),
                )
                await rich.answer(cq)
                return

            if arg == "approved":
                ids = await chatcfg.get(chat.id, "approved", []) or []
                entries = [(f"user {index + 1}", str(uid)) for index, uid in enumerate(ids)]
                await _show(client, cq, cards.approved_card(entries))
                await rich.answer(cq)
                return

            await rich.answer(cq, "This tool needs a group.", show_alert=True)
            return

        player = runtime.player
        if player is None:
            await rich.answer(cq, "Player is still starting up…")
            return
        state = player.queues.get(chat.id)

        # ── navigation ─────────────────────────────────────────────────────
        if action == "noop":
            await rich.answer(cq)
            return

        if action == "close":
            try:
                await cq.message.delete()
            except Exception:
                await rich.answer(cq)
            return

        if action == "help":
            section = arg or "main"
            await _show(client, cq, cards.help_card(section), keyboards.help_nav(section))
            await rich.answer(cq)
            return

        if action == "about":
            await _show(client, cq, cards.about_card(), keyboards.back_close("v:help:main"))
            await rich.answer(cq)
            return

        # ── entry buttons (welcome card, quick actions) ────────────────────
        if action == "play":
            query = ":".join(parts[2:]).strip()
            if not query or runtime.youtube is None:
                await rich.answer(cq, "Nothing to play.", show_alert=True)
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
                if outcome == "streamed":
                    # The poster is the message now; this button card is spent.
                    await _drop(client, chat.id, cq.message.id)
                await rich.answer(cq, 
                    {
                        "streamed": f"Playing · {truncate(track.title, 26)}",
                        "queued": f"Queued · {truncate(track.title, 26)}",
                        "error": "Could not start the voice chat",
                    }.get(outcome, "Done")
                )
            except Exception as exc:
                await rich.answer(cq, f"Could not play that: {truncate(str(exc), 60)}", show_alert=True)
            return

        if action == "forget":
            # Two taps, always: the confirm card carries `v:forget:yes`.
            actor = cq.from_user.id if cq.from_user else 0
            if not actor or runtime.storage is None:
                await rich.answer(cq, "Nothing to delete", show_alert=True)
                return
            if arg != "yes":
                await _show(
                    client,
                    cq,
                    cards.confirm_card(
                        "Delete your data?",
                        "Your history, favourites and playlists are removed from "
                        "this deployment. Group settings and the bot's counters stay.",
                        confirm="v:forget:yes",
                        danger=True,
                        confirm_label="Yes, delete it",
                    ),
                )
                await rich.answer(cq)
                return
            try:
                removed = await runtime.storage.forget_user(actor)
            except Exception as exc:  # pragma: no cover - a broken backend
                logger.warning("forget_user failed: %s", exc)
                await rich.answer(cq, "Could not delete right now — try again.", show_alert=True)
                return
            total = sum(int(value) for value in removed.values())
            from vyron.ui import blocks as B

            await _show(
                client,
                cq,
                B.head("Deleted", glyph="check")
                + B.context(
                    "Your history, favourites and playlists are gone from this "
                    "deployment. Nothing else was touched."
                )
                + B.stat_pairs(
                    [
                        ("clock", "History", f"<b>{removed.get('history', 0)}</b>"),
                        ("star", "Favourites", f"<b>{removed.get('favorites', 0)}</b>"),
                        ("queue", "Playlists", f"<b>{removed.get('playlists', 0)}</b>"),
                    ]
                )
                + B.actions(B.row(B.btn("Close", data="v:close", style="primary"))),
            )
            await rich.answer(cq, f"Deleted {total} item(s)")
            return

        if action == "start":
            # The home card, rebuildable from any other card ("Home" buttons).
            # In a group that is the *group* card (setup checklist), the same
            # one `/start` sends there — a tapped button and a typed command
            # must never show different things.
            from vyron.modules.start import group_card, home_card

            private = is_private_chat(chat)
            await _show(
                client,
                cq,
                await home_card(chat, cq.from_user)
                if private
                else await group_card(client, chat, cq.from_user),
                keyboards.start_panel(player=private),
            )
            await rich.answer(cq, "Home")
            return

        if action == "app":
            if not keyboards.app_url():
                await rich.answer(cq, "Set WEBAPP_URL first.", show_alert=True)
                return
            if is_private_chat(chat):
                await _show(
                    client,
                    cq,
                    cards.webapp_card(settings.webapp_url or ""),
                    keyboards.app_markup(with_close=True),
                )
            else:
                await _show(
                    client,
                    cq,
                    cards.webapp_group_card(settings.bot_username),
                    keyboards.dm_markup(),
                )
            await rich.answer(cq)
            return

        if action == "ui":
            from vyron.modules import uistyle

            actor = cq.from_user.id if cq.from_user else 0
            if not is_owner(actor):
                await rich.answer(cq, "Owner only", show_alert=True)
                return
            chosen = await uistyle.set_style(arg)
            await _show(client, cq, uistyle.card(), keyboards.back_close("v:help:main"))
            await rich.answer(cq, f"Interface: {uistyle.STYLES.get(chosen, chosen)}")
            return

        if action == "settings":
            # A fresh process starts from defaults; the persisted loop/volume
            # only arrive through restore_settings, so ask before showing them.
            state = await player.restore_settings(chat.id)
            cfg = await panels.chat_panel(chat.id, state)
            await _show(
                client,
                cq,
                cards.settings_card(cfg, chat.title or ""),
                keyboards.settings_panel(cfg),
            )
            await rich.answer(cq)
            return

        if action == "log":
            from vyron.core import logsink
            from vyron.modules.logs_cmd import _logger_kb, logger_card

            actor = cq.from_user.id if cq.from_user else 0
            if not is_owner(actor):
                await rich.answer(cq, "Owner only", show_alert=True)
                return
            state = await logsink.set_enabled(runtime.storage, arg == "on")
            await _show(client, cq, logger_card(), _logger_kb())
            await rich.answer(cq, "Log channel on" if state else "Log channel off")
            return

        if action == "lang":
            from vyron.core import chatcfg
            from vyron.modules.language import keyboard as lang_keyboard
            from vyron.modules.language import language_card

            catalog = await i18n.for_chat(chat.id)
            code = arg
            if not code or code == "menu":
                current = str(await chatcfg.get(chat.id, "lang", "") or "")
                await _show(client, cq, language_card(current), lang_keyboard(current))
                await rich.answer(cq)
                return
            if not i18n.is_known(code):
                await rich.answer(cq, catalog.t("lang.unknown"), show_alert=True)
                return
            actor = cq.from_user.id if cq.from_user else 0
            if not is_private_chat(chat) and not (
                is_owner(actor) or await is_chat_admin(client, chat.id, actor)
            ):
                await rich.answer(cq, catalog.t("lang.admin_only"), show_alert=True)
                return
            chosen = await i18n.set_for_chat(chat.id, code)
            fresh = i18n.catalog(chosen)
            await _show(
                client,
                cq,
                language_card(chosen, text_key="lang.saved"),
                lang_keyboard(chosen),
            )
            await rich.answer(cq, fresh.t("lang.saved"))
            return

        if action == "vote":
            from vyron.modules.power import cast_vote

            if cq.from_user is None:
                await rich.answer(cq)
                return
            outcome, tally, needed, _state = await cast_vote(chat.id, cq.from_user.id)
            if outcome == "disabled":
                await rich.answer(cq, "Vote-skip is off — an admin can enable it.", show_alert=True)
                return
            if outcome == "duplicate":
                await rich.answer(cq, f"You already voted · {tally.remaining} more needed")
                return
            if outcome == "passed":
                skipped = await player.skip(chat.id, count=1)
                await rich.answer(cq, "Skipped by vote!" if skipped else "Queue is empty")
                return
            await rich.answer(cq, f"Vote counted · {tally.count}/{needed}")
            return

        if action == "np":
            if not state or not state.current:
                await rich.answer(cq, "Nothing is playing.", show_alert=True)
                return
            # the card follows the message it is edited into: a poster takes a
            # caption, a text card takes full markup
            markup = (
                cards.now_playing_caption(state)
                if cq.message and rich.is_photo(chat.id, cq.message.id)
                else cards.player_panel(state)
            )
            await _show(client, cq, markup, keyboards.now_playing(state))
            await rich.answer(cq)
            return

        # ── queue ──────────────────────────────────────────────────────────
        if action == "queue":
            page = int(arg) if arg.isdigit() else 0
            markup, pages = cards.queue_card(state, page)
            await _show(client, cq, markup, keyboards.queue(state, min(page, pages - 1), pages))
            await rich.answer(cq)
            return

        if action == "clearqueue":
            removed = player.queues.clear(chat.id, keep_current=True)
            await player.refresh_now_playing(chat.id)
            await rich.answer(cq, f"Cleared {removed} tracks")
            return

        # ── transport ──────────────────────────────────────────────────────
        catalog = await i18n.for_chat(chat.id)

        if action == "pause":
            await rich.answer(cq, 
                catalog.t("ctl.paused")
                if await player.pause(chat.id)
                else catalog.t("ctl.nothing_playing")
            )
            return

        if action == "resume":
            await rich.answer(cq, 
                catalog.t("ctl.resumed")
                if await player.resume(chat.id)
                else catalog.t("ctl.nothing_paused")
            )
            return

        if action == "skip":
            track = await player.skip(chat.id)
            await rich.answer(cq, 
                f"⏭ {truncate(track.title, 40)}" if track else catalog.t("ctl.queue_empty")
            )
            return

        if action == "stop":
            await player.stop(chat.id, leave=True)
            await rich.answer(cq, catalog.t("ctl.stopped"))
            try:
                await cq.message.delete()
            except Exception:
                pass
            return

        if action == "seek":
            current = state.current
            if current is None:
                await rich.answer(cq, "Nothing is playing")
                return
            step = int(arg) if arg.lstrip("+-").isdigit() else 15
            target = max(0, int(state.elapsed()) + step)
            if current.duration:
                target = min(current.duration - 1, target)
            if await player.seek(chat.id, target):
                mark = "⏩" if step > 0 else "⏪"
                await rich.answer(cq, f"{mark} {catalog.t('ctl.seek', time=fmt_duration(target))}")
            else:
                await rich.answer(cq, "Could not seek")
            return

        # ── the end of a session: "again" and "keep going" ─────────────────
        if action == "replay":
            if not state or not state.history:
                await rich.answer(cq, "Nothing to play again.", show_alert=True)
                return
            track = state.history[-1]
            try:
                await player.play_track(chat.id, track, video=track.is_video)
            except Exception as exc:
                logger.info("replay failed for %s: %s", track.id, exc)
                await rich.answer(cq, "Could not start it again — try /play.", show_alert=True)
                return
            await _drop(client, chat.id, cq.message.id)
            await rich.answer(cq, f"▶️ {truncate(track.title, 32)}")
            return

        if action == "radio":
            # One tap from "the queue ended" to "keep the same kind of music
            # going" — no command to remember, and it survives the next
            # restart because it is persisted.
            state.autoplay = True
            state.autoplay_set = True
            await player.persist(chat.id)
            seed = state.history[-1] if state.history else None
            chosen = None
            if seed is not None:
                from vyron.core import autoplay as auto

                try:
                    chosen = await auto.next_track(
                        runtime.youtube,
                        seed,
                        mood=state.mood,
                        language=state.language,
                        played=state.history,
                    )
                except Exception as exc:  # pragma: no cover - network paths
                    logger.info("radio pick failed: %s", exc)
            if chosen is None:
                await rich.answer(cq, 
                    "Radio is on — the next /play will keep going by itself.",
                    show_alert=True,
                )
                return
            try:
                await player.enqueue(chat.id, chosen, play_now=True)
            except Exception as exc:
                logger.info("radio start failed: %s", exc)
                await rich.answer(cq, "Radio is on, but that track would not start.", show_alert=True)
                return
            await _drop(client, chat.id, cq.message.id)
            await rich.answer(cq, f"📻 {truncate(chosen.title, 32)}")
            return

        if action == "video":
            # /play picks audio on purpose (it is a music bot), so the card
            # offers the other half of the choice: this same track, with its
            # picture — from where it is now, not from the start.
            current = state.current
            if current is None:
                await rich.answer(cq, "Nothing is playing", show_alert=True)
                return
            resume_at = int(max(0, state.elapsed()))
            try:
                await player.play_track(chat.id, current, video=True, seek=resume_at)
            except Exception as exc:
                logger.info("video switch failed for %s: %s", current.id, exc)
                await rich.answer(cq, 
                    "No video for this one on this server — the song keeps playing.",
                    show_alert=True,
                )
                return
            if getattr(state, "is_video", False):
                await rich.answer(cq, "Video on")
                await _show(
                    client,
                    cq,
                    cards.started_card(current),
                    keyboards.now_playing(state),
                )
            else:
                await rich.answer(cq, 
                    "This server has no video for it — playing the song instead.",
                    show_alert=True,
                )
            return

        if action == "loop":
            state.loop = state.loop.next()
            await player.persist(chat.id)
            await player.refresh_now_playing(chat.id)
            await rich.answer(cq, catalog.t("ctl.loop", mode=state.loop.label))
            return

        if action == "shuffle":
            count = player.queues.shuffle(chat.id)
            await player.refresh_now_playing(chat.id)
            await rich.answer(cq, catalog.t("ctl.shuffled", count=count))
            return

        if action == "vol":
            if arg == "show":
                await rich.answer(cq, f"Volume: {state.volume}%")
                return
            delta = int(arg) if arg.lstrip("+-").isdigit() else 0
            volume = await player.set_volume(chat.id, state.volume + delta)
            await rich.answer(cq, catalog.t("ctl.volume", volume=volume))
            return

        # ── settings ───────────────────────────────────────────────────────
        if action == "set":
            from vyron.core import chatcfg

            if arg == "loop":
                state.loop = state.loop.next()
            elif arg == "autoplay":
                state.autoplay = not state.autoplay
                state.autoplay_set = True
            elif arg == "always":
                state.always_on = not state.always_on
            elif arg == "poster":
                await chatcfg.set(
                    chat.id, "poster", not await chatcfg.get(chat.id, "poster", True)
                )
            elif arg == "playmode":
                # Toggling who may request is an admin action (BadMusic's
                # playmode): a member must not be able to lock the bot.
                uid = cq.from_user.id if cq.from_user else 0
                if not (is_owner(uid) or await is_chat_admin(client, chat.id, uid)):
                    await rich.answer(cq, "Admins only", show_alert=True)
                    return
                await chatcfg.set(
                    chat.id,
                    "admins_only",
                    not await chatcfg.get(chat.id, "admins_only", False),
                )
            await player.persist(chat.id)
            cfg = await panels.chat_panel(chat.id, state)
            await _show(
                client,
                cq,
                cards.settings_card(cfg, chat.title or ""),
                keyboards.settings_panel(cfg),
            )
            await rich.answer(cq, "Saved")
            return

        # ── favourites / lyrics ────────────────────────────────────────────
        if action == "fav":
            if arg == "list":
                # `v:fav:list` — the shelf itself. Kept on the same action so
                # the router's action list does not grow a near-duplicate.
                items = await runtime.storage.favorites(cq.from_user.id, limit=10)
                await _show(
                    client,
                    cq,
                    cards.favorites_card(items),
                    keyboards.back_close("v:help:tools"),
                )
                await rich.answer(cq, f"{len(items)} saved")
                return
            if not state or not state.current:
                await rich.answer(cq, "Nothing is playing.", show_alert=True)
                return
            added = await runtime.storage.add_favorite(cq.from_user.id, state.current.to_dict())
            await rich.answer(cq, "Saved to favourites" if added else "Already saved")
            return

        if action == "lyrics":
            await _lyrics(client, cq, state)
            return

        # ── search results ─────────────────────────────────────────────────
        if action in {"pick", "dl"}:
            entry = pending.get(chat.id, cq.message.id)
            if entry is None:
                await rich.answer(cq, "That search expired — run the command again.", show_alert=True)
                return

            # `v:pick:list` reopens the picker. /play already started the
            # obvious match, so this is the "no, not that one" door.
            if action == "pick" and arg == "list":
                await _show(
                    client,
                    cq,
                    cards.search_card(
                        entry.query,
                        entry.tracks,
                        mode=entry.mode,
                        note="These are the other matches for that search.",
                    ),
                    keyboards.search_results(entry.tracks),
                )
                await rich.answer(cq, "Pick one")
                return

            # `v:pick:q2` queues result #3 and `v:pick:n2` puts it *next*,
            # so a good search does not have to interrupt the song playing now.
            queued = arg[:1] in {"q", "n"}
            digits = arg[1:] if queued else arg
            if not digits.isdigit() or int(digits) >= len(entry.tracks):
                await rich.answer(cq, "That search expired — run the command again.", show_alert=True)
                return
            index = int(digits)
            if queued and action == "pick":
                track = entry.tracks[index]
                next_up = arg.startswith("n")
                position = await player.enqueue(
                    chat.id,
                    track,
                    video=entry.video or track.is_video,
                    index=0 if next_up else None,
                )
                if position == 1:
                    reply = f"Starting · {truncate(track.title, 32)}"
                elif position > 0:
                    reply = (
                        f"Playing next · {truncate(track.title, 32)}"
                        if next_up
                        else f"Queued at #{position} · {truncate(track.title, 32)}"
                    )
                elif position == -1:
                    reply = "That is already in the queue"
                else:
                    reply = "The queue is full — skip or clear something first"
                await rich.answer(cq, reply)
                return
            if action == "dl":
                await _show(client, cq, cards.download_choice_card(entry.tracks[index]))
                await rich.answer(cq)
                return

            from vyron.modules.play import begin

            track = entry.tracks[index]
            want_video = bool(entry.video or track.is_video)
            outcome = await begin(
                client,
                chat.id,
                track,
                # a video result stays video even when the picker was opened
                # from /song (entry.video) — otherwise the track decides.
                video=want_video,
                status_id=cq.message.id,
            )
            if outcome == "streamed":
                # Playing: the now-playing poster replaces the picker instead of
                # leaving a second card under it.
                await _drop(client, chat.id, cq.message.id)
            elif outcome != "error":
                await _show(
                    client,
                    cq,
                    cards.queued_card(track, 0),
                    keyboards.now_playing(state),
                )
            await rich.answer(cq, 
                {"streamed": "Starting", "queued": "Queued", "error": "Could not stream that"}.get(
                    outcome, "Done"
                )
            )
            return

        # ── /suggest picker: queue one of the suggestions ──────────────────
        if action == "p":
            entry = pending.get(chat.id, cq.message.id)
            if not entry or not arg.isdigit() or int(arg) >= len(entry.tracks):
                await rich.answer(cq, "That list expired — run /suggest again.", show_alert=True)
                return
            if runtime.player is None:
                await rich.answer(cq, "Playback is not ready yet.", show_alert=True)
                return
            track = entry.tracks[int(arg)]
            try:
                position = await runtime.player.enqueue(chat.id, track)
            except Exception as exc:
                await rich.answer(cq, f"Could not queue that: {truncate(str(exc), 60)}", show_alert=True)
                return
            await rich.answer(cq, 
                f"Queued · {truncate(track.title, 26)}"
                if position > 0
                else "Already in the queue"
            )
            return

        # ── saved playlist: queue the whole thing ──────────────────────────
        if action == "pl":
            from vyron.core import playlists as playlists_store

            if runtime.player is None:
                await rich.answer(cq, "Playback is not ready yet.", show_alert=True)
                return
            actor = cq.from_user.id if cq.from_user else 0
            name = ""
            queued = 0
            if arg:
                name, tracks = await playlists_store.as_tracks(actor, arg)
                for track in tracks:
                    try:
                        if await runtime.player.enqueue(chat.id, track) > 0:
                            queued += 1
                    except Exception:
                        continue
            if not name:
                await rich.answer(cq, "That playlist is gone — send /playlists.", show_alert=True)
                return
            await rich.answer(cq, 
                f"Queued {queued} from {truncate(name, 22)}" if queued else "Already queued"
            )
            return

        if action == "get":
            entry = pending.get(chat.id, cq.message.id)
            kind = parts[2] if len(parts) > 2 else "audio"
            index = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0
            if not entry or index >= len(entry.tracks):
                await rich.answer(cq, "That result expired.", show_alert=True)
                return
            from vyron.modules.play import deliver

            await rich.answer(cq, "Downloading…")
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
            await rich.answer(cq, "Saved")
            return

        # ── audio effects ──────────────────────────────────────────────────
        if action == "fx":
            from vyron.core import effects as audio_fx
            from vyron.modules.effects_cmd import panel as fx_panel, save as save_fx

            active = audio_fx.resolve(await chatcfg.get(chat.id, "effects", []) or [])
            if arg == "off":
                active = []
            elif arg in audio_fx.EFFECTS:
                if arg in active:
                    active = [name for name in active if name != arg]
                else:
                    active = audio_fx.resolve(active + [arg])
            # The board toggles the live stream too: a filter you can see
            # switched on should be a filter you can already hear.
            live = await save_fx(chat.id, active)
            await _show(client, cq, fx_panel(active))
            await rich.answer(cq, 
                f"{'Live: ' if live else 'Next track: '}{audio_fx.labels(active)}"
            )
            return

        # ── owner panel ────────────────────────────────────────────────────
        if action == "admin":
            if not is_owner(cq.from_user.id):
                await rich.answer(cq, "Owner only.", show_alert=True)
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
                await rich.answer(cq)
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
                await rich.answer(cq)
                return

        await rich.answer(cq)

    async def _lyrics(client: Client, cq: CallbackQuery, state) -> None:
        if not state or not state.current:
            await rich.answer(cq, "Nothing is playing.", show_alert=True)
            return
        from vyron.core.lyrics import split_title

        await rich.answer(cq, "Fetching lyrics…")
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
