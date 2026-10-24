# ---------------------------------------------------------------------------
#  VYRON — channel playback (/cplay)
#  Streams into the discussion group's voice chat from a linked channel, the
#  Mirrors what plays in a channel to a linked group.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import Message

from vyron.core import chatcfg, effects
from vyron.core.search import MediaError, looks_like_url
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import truncate
from vyron.ui.theme import E
from vyron.ui.progress import human_time
from vyron.utils.helpers import command_args, display_name, is_chat_admin, is_owner, parse_seek
from vyron.utils.commands import cmd

logger = logging.getLogger(__name__)



# ── channel ↔ group links ────────────────────────────────────────────────────
async def _channel_owner(channel_id: int) -> int | None:
    """Which chat already streams into *channel_id* (one channel, one group)."""
    if not runtime.storage:
        return None
    raw = await runtime.storage.get_meta(f"chanlink:{int(channel_id)}", 0)
    try:
        return int(raw) or None
    except (TypeError, ValueError):
        return None


async def _link(chat_id: int, channel_id: int) -> None:
    await chatcfg.set(chat_id, "channel", int(channel_id))
    if runtime.storage:
        await runtime.storage.set_meta(f"chanlink:{int(channel_id)}", int(chat_id))


async def _unlink(chat_id: int, channel_id: int | None = None) -> None:
    if channel_id is None:
        channel_id = int(await chatcfg.get(chat_id, "channel", 0) or 0)
    if channel_id and runtime.storage:
        await runtime.storage.set_meta(f"chanlink:{int(channel_id)}", 0)
    await chatcfg.set(chat_id, "channel", 0)


def _clean_ref(ref: str):
    """``@name`` / ``t.me/name`` / ``https://t.me/name`` / ``-100123`` → id/name."""
    ref = (ref or "").strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if ref.lower().startswith(prefix):
            ref = ref[len(prefix):]
            break
    ref = ref.lstrip("@").split("/")[0].split("?")[0]
    if ref.lstrip("-").isdigit():
        return int(ref)
    return ref


async def _target_chat(client: Client, message: Message) -> int | None:
    """Explicit `/cplayset` binding wins, otherwise the linked chat."""
    chat = message.chat
    bound = await chatcfg.get(chat.id, "channel", 0)
    if bound:
        return int(bound)
    linked = getattr(chat, "linked_chat_id", None)
    if linked:
        return int(linked)
    if chat.type == ChatType.CHANNEL:
        return int(chat.id)
    try:
        full = await client.get_chat(chat.id)
        if getattr(full, "linked_chat_id", None):
            return int(full.linked_chat_id)
    except Exception:
        pass
    return None


def register(client: Client) -> None:
    @client.on_message(cmd(["cplay"]))
    async def _cplay(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        query = command_args(message)
        if not query:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('globe')} Usage: <code>/cplay song name or link</code>\n"
                    "The linked channel's voice chat is used."
                ),
            )
            return

        target = await _target_chat(client, message)
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                B.row(
                    B.btn(
                        f"{E('cross')} No linked chat — bind a channel first",
                        data="v:noop",
                        style="danger",
                    )
                ),
            )
            return

        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} <b>Resolving for the channel…</b>",
            reply_to=message.id,
        )
        requester = (
            message.from_user.id if message.from_user else 0,
            display_name(message.from_user),
        )
        try:
            if looks_like_url(query):
                track = await runtime.youtube.resolve(query, requester=requester)
            else:
                results = await runtime.youtube.search(query, limit=1, requester=requester)
                track = results[0]
            await runtime.player.play_track(target, track, video=False)
            markup = (
                f"{E('live')} <b>Channel stream started</b>\n"
                f"<blockquote>{E('note')} {rich.esc(truncate(track.title, 54))}\n"
                f"{E('chat')} <code>{target}</code></blockquote>"
            )
        except MediaError as exc:
            markup = f"{E('cross')} <b>Could not start</b>\n<blockquote>{rich.esc(truncate(str(exc), 150))}</blockquote>"
        except Exception as exc:
            logger.warning("cplay failed: %s", exc)
            markup = f"{E('warn')} <b>Channel playback failed</b>\n<blockquote>{rich.esc(truncate(str(exc), 150))}</blockquote>"

        if status:
            await rich.edit(client, message.chat.id, status.id, markup)

    # ── /cplayset — pin the channel a group should stream into ────────────
    @client.on_message(cmd(["cplayset"]))
    async def _cplayset(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        user = message.from_user
        if user and not await is_chat_admin(client, chat_id, user.id):
            await rich.send(
                client,
                chat_id,
                B.row(B.btn(f"{E('shield')} Admins only", data="v:noop", style="danger")),
                reply_to=message.id,
            )
            return
        arg = command_args(message).strip()
        if not arg:
            bound = await chatcfg.get(chat_id, "channel", 0)
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('globe')} Channel playback is bound to <code>{bound}</code>.\n"
                    "<code>/cplayset -1001234567890</code> to change it, "
                    "<code>/cplayset off</code> to use the linked chat."
                    if bound
                    else f"{E('info')} No channel bound — <code>/cplayset &lt;id|@name&gt;</code>"
                ),
                reply_to=message.id,
            )
            return
        if arg.lower() in {"off", "none", "clear", "0"}:
            await chatcfg.set(chat_id, "channel", 0)
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('check')} Cleared — channel playback follows the linked chat again."),
                reply_to=message.id,
            )
            return
        try:
            peer = await client.get_chat(arg if arg.startswith("@") else int(arg))
        except Exception as exc:
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('warn')} Could not resolve that channel: {rich.esc(truncate(str(exc), 90))}"),
                reply_to=message.id,
            )
            return
        await chatcfg.set(chat_id, "channel", int(peer.id))
        await rich.send(
            client,
            chat_id,
            B.heading(f"{E('check')} channel bound", 3)
            + B.kv(
                [
                    (f"{E('globe')} title", f"<b>{rich.esc(truncate(peer.title or '—', 40))}</b>"),
                    (f"{E('id')} id", f"<code>{peer.id}</code>"),
                ]
            )
            + B.note(f"{E('bolt')} <code>/cplay &lt;song&gt;</code> now streams there."),
            reply_to=message.id,
        )

    @client.on_message(cmd(["cstop"]))
    async def _cstop(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        target = await _target_chat(client, message)
        if target is None:
            await rich.send(client, message.chat.id, f"{E('info')} No linked chat found.")
            return
        await runtime.player.stop(target, leave=True)
        await rich.send(
            client,
            message.chat.id,
            B.row(B.btn(f"{E('check')} Channel stream stopped", data="v:noop", style="success")),
        )
    # ── /addchannel · /delchannel — the validated link ────────────────────
    @client.on_message(cmd(["addchannel"]))
    async def _addchannel(_: Client, message: Message) -> None:
        """Bind this group to a channel, with the checks that make it safe.

        The channel must exist, the bot must be an admin there, and the person
        linking it must be an admin of it too — otherwise someone could point a
        group at a channel they do not control.
        """
        chat_id = message.chat.id
        arg = command_args(message).strip()
        user = message.from_user
        uid = user.id if user else 0
        bound = int(await chatcfg.get(chat_id, "channel", 0) or 0)

        if not arg:
            title = "—"
            if bound:
                try:
                    peer = await client.get_chat(bound)
                    title = rich.esc(truncate(peer.title or "—", 40))
                except Exception:
                    title = "(unreachable)"
            rows = [(f"{E('globe')} channel", f"<b>{title}</b>" if bound else "not linked")]
            if bound:
                rows.append((f"{E('id')} id", f"<code>{bound}</code>"))
            await rich.send(
                client,
                chat_id,
                B.heading(f"{E('globe')} channel", 3)
                + B.kv(rows)
                + B.note(
                    "<code>/addchannel @mychannel</code> to link one · "
                    "<code>/delchannel</code> to unlink"
                    if not bound
                    else f"{E('bolt')} <code>/cplay &lt;song&gt;</code> streams there."
                ),
                reply_to=message.id,
            )
            return

        if not (is_owner(uid) or await is_chat_admin(client, chat_id, uid)):
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('shield')} Only admins can link a channel."),
                reply_to=message.id,
            )
            return

        if arg.lower() in {"off", "none", "clear", "0"}:
            await _unlink(chat_id, bound or None)
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('check')} Unlinked — playback follows the linked chat again."),
                reply_to=message.id,
            )
            return

        try:
            peer = await client.get_chat(_clean_ref(arg))
        except Exception as exc:
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('warn')} Could not find that channel: {rich.esc(truncate(str(exc), 90))}"),
                reply_to=message.id,
            )
            return
        if peer.type != ChatType.CHANNEL:
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('warn')} That is not a channel — link the channel itself, not its group."),
                reply_to=message.id,
            )
            return

        try:
            me = await client.get_me()
            bot_member = await client.get_chat_member(peer.id, me.id)
            bot_ok = bot_member.status in {
                ChatMemberStatus.OWNER,
                ChatMemberStatus.ADMINISTRATOR,
            }
        except Exception:
            bot_ok = False
        if not bot_ok:
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('warn')} Add me as an admin of that channel first."),
                reply_to=message.id,
            )
            return

        if not is_owner(uid):
            try:
                member = await client.get_chat_member(peer.id, uid)
                user_ok = member.status in {
                    ChatMemberStatus.OWNER,
                    ChatMemberStatus.ADMINISTRATOR,
                }
            except Exception:
                user_ok = False
            if not user_ok:
                await rich.send(
                    client,
                    chat_id,
                    B.note(f"{E('shield')} You need to be an admin of that channel."),
                    reply_to=message.id,
                )
                return

        other = await _channel_owner(peer.id)
        if other and other != chat_id:
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('warn')} That channel is already linked to another chat "
                    f"(<code>{other}</code>). Unlink it there first."
                ),
                reply_to=message.id,
            )
            return

        if bound and bound != int(peer.id) and runtime.player:
            # switching away from a channel must not leave it streaming
            await runtime.player.stop(bound, leave=True)
        await _link(chat_id, int(peer.id))

        await rich.send(
            client,
            chat_id,
            B.heading(f"{E('check')} channel linked", 3)
            + B.kv(
                [
                    (f"{E('globe')} title", f"<b>{rich.esc(truncate(peer.title or '—', 40))}</b>"),
                    (f"{E('id')} id", f"<code>{peer.id}</code>"),
                    (f"{E('live')} status", "<b>ready</b>"),
                ]
            )
            + B.note(f"{E('bolt')} <code>/cplay &lt;song&gt;</code> now streams there."),
            reply_to=message.id,
        )

    @client.on_message(cmd(["delchannel"]))
    async def _delchannel(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        user = message.from_user
        if user and not (is_owner(user.id) or await is_chat_admin(client, chat_id, user.id)):
            await rich.send(
                client, chat_id, B.note(f"{E('shield')} Only admins can unlink."), reply_to=message.id
            )
            return
        bound = int(await chatcfg.get(chat_id, "channel", 0) or 0)
        if not bound:
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('info')} Nothing is linked — use <code>/addchannel</code>."),
                reply_to=message.id,
            )
            return
        if runtime.player:
            await runtime.player.stop(bound, leave=True)
        await _unlink(chat_id, bound)
        await rich.send(
            client,
            chat_id,
            B.note(f"{E('check')} Unlinked from <code>{bound}</code> — playback is back on the linked chat."),
            reply_to=message.id,
        )

    # ── channel-side playback controls ────────────────────────────────────
    async def _channel_target(message: Message) -> int | None:
        target = await _target_chat(client, message)
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} No channel linked — <code>/addchannel @name</code>."),
                reply_to=message.id,
            )
        return target

    async def _admin_or_warn(message: Message) -> bool:
        user = message.from_user
        uid = user.id if user else 0
        if is_owner(uid) or await is_chat_admin(client, message.chat.id, uid):
            return True
        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('shield')} Only admins can control channel playback."),
            reply_to=message.id,
        )
        return False

    @client.on_message(cmd(["cplayforce"]))
    async def _cplayforce(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        video = False
        target = await _channel_target(message)
        if target is None or not await _admin_or_warn(message):
            return
        query = command_args(message).strip()
        if not query:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Usage: <code>/cplayforce believer</code>"),
                reply_to=message.id,
            )
            return
        user = message.from_user
        requester = (user.id if user else 0, display_name(user))
        try:
            if looks_like_url(query):
                track = await runtime.youtube.resolve(query, requester=requester)
            else:
                results = await runtime.youtube.search(query, limit=1, requester=requester)
                if not results:
                    raise MediaError("No results for that.")
                track = results[0]
            await runtime.player.force_play(target, track, video=video)
        except MediaError as exc:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('cross')} {rich.esc(truncate(str(exc), 140))}"),
                reply_to=message.id,
            )
            return
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('bolt')} <b>Forced in the channel</b> · {rich.esc(truncate(track.title, 54))}"
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["cpause", "cresume", "cskip", "cclear", "cautoplay"]))
    async def _cctl(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        command = message.command[0].lower()
        target = await _channel_target(message)
        if target is None or not await _admin_or_warn(message):
            return
        state = runtime.player.queues.get(target)

        if command == "cpause":
            ok = await runtime.player.pause(target)
            text = "Paused in the channel" if ok else "Nothing is playing there"
        elif command == "cresume":
            ok = await runtime.player.resume(target)
            text = "Resumed in the channel" if ok else "Nothing is paused there"
        elif command == "cskip":
            skipped = await runtime.player.skip(target, count=1)
            text = (
                f"Skipped · {rich.esc(truncate(skipped.title, 46))}"
                if skipped
                else "The channel queue is empty"
            )
        elif command == "cclear":
            count = len(state.queue)
            state.queue.clear()
            state.touch()
            await runtime.player.persist(target)
            text = f"Cleared {count} queued track(s) — the current one keeps playing"
        else:
            state.autoplay = not state.autoplay
            await runtime.player.persist(target)
            text = f"Channel autoplay is {'on' if state.autoplay else 'off'}"

        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('check')} {text}"),
            reply_to=message.id,
        )

    @client.on_message(cmd(["cseek"]))
    async def _cseek(_: Client, message: Message) -> None:
        """Seek the channel's stream — same syntax as `/seek` (`+30`, `1:20`)."""
        if not runtime.player:
            return
        target = await _channel_target(message)
        if target is None or not await _admin_or_warn(message):
            return
        state = runtime.player.queues.get(target)
        if not state or not state.current:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Nothing is playing in the channel."),
                reply_to=message.id,
            )
            return
        arg = command_args(message) or "+15"
        seconds = parse_seek(arg, state.elapsed(), state.current.duration or 0)
        await runtime.player.seek(target, seconds)
        await rich.react(message, "👍")
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('clock')} <b>Channel seek</b> · {human_time(seconds)}"
                f" / {human_time(state.current.duration or 0)}"
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["cvolume"]))
    async def _cvolume(_: Client, message: Message) -> None:
        """Channel volume — `/cvolume 120`, `/cvolume +10`, `/cvolume -10`."""
        if not runtime.player:
            return
        target = await _channel_target(message)
        if target is None or not await _admin_or_warn(message):
            return
        state = runtime.player.queues.get(target)
        arg = command_args(message).strip()
        if not arg:
            current = state.volume if state else 100
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('volume')} <b>Channel volume</b> <code>{current}%</code>"),
                reply_to=message.id,
            )
            return
        base = state.volume if state else 100
        if arg[0] in "+-" and arg[1:].isdigit():
            value = base + (int(arg[1:]) if arg[0] == "+" else -int(arg[1:]))
        elif arg.isdigit():
            value = int(arg)
        else:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('warn')} Use a number between 1 and 200."),
                reply_to=message.id,
            )
            return
        volume = await runtime.player.set_volume(target, value)
        await rich.react(message, "👍")
        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('volume')} <b>Channel volume</b> <code>{volume}%</code>"),
            reply_to=message.id,
        )

    async def _channel_effects(target: int) -> list[str]:
        return effects.resolve(await chatcfg.get(target, "effects", []) or [])

    async def _channel_effect(message: Message, *, enable: bool) -> None:
        if not runtime.player:
            return
        target = await _channel_target(message)
        if target is None or not await _admin_or_warn(message):
            return
        arg = command_args(message).strip()
        current = await _channel_effects(target)
        if not arg:
            if not enable:  # `/ceffectoff` with no name clears everything
                updated: list[str] = []
            else:
                names = ", ".join(effects.EFFECTS)
                await rich.send(
                    client,
                    message.chat.id,
                    B.note(f"{E('info')} Pick one: {names}"),
                    reply_to=message.id,
                )
                return
        else:
            name = effects.resolve([arg])
            if not name:
                await rich.send(
                    client,
                    message.chat.id,
                    B.note(f"{E('warn')} Unknown effect."),
                    reply_to=message.id,
                )
                return
            if enable and name[0] not in current:
                updated = effects.resolve([*current, name[0]])
            else:
                updated = [item for item in current if item != name[0]]
        await chatcfg.set(target, "effects", updated)
        state = runtime.player.queues.get(target)
        if state:
            state.effects = updated
            state.touch()
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('spark')} <b>Channel effects</b> · {effects.labels(updated)}&nbsp;"
                f"<i>(applies from the next track)</i>"
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["ceffecton"]))
    async def _ceffect_on(_: Client, message: Message) -> None:
        await _channel_effect(message, enable=True)

    @client.on_message(cmd(["ceffectoff"]))
    async def _ceffect_off(_: Client, message: Message) -> None:
        await _channel_effect(message, enable=False)

    @client.on_message(cmd(["ceffects"]))
    async def _ceffects(_: Client, message: Message) -> None:
        target = await _channel_target(message)
        if target is None:
            return
        active = await _channel_effects(target)
        available = ", ".join(effects.EFFECTS)
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('spark')} channel effects", 3)
            + B.kv(
                [
                    (f"{E('globe')} channel", f"<code>{target}</code>"),
                    (f"{E('bolt')} active", f"<b>{effects.labels(active)}</b>"),
                    (f"{E('note')} available", f"<i>{available}</i>"),
                ]
            ),
            reply_to=message.id,
        )

    @client.on_message(cmd(["cthumbnail"]))
    async def _cthumbnail(_: Client, message: Message) -> None:
        """The channel's own poster artwork, same rules as `/thumbnail`."""
        from vyron.modules import thumbnail_cmd

        target = await _channel_target(message)
        if target is None or not await _admin_or_warn(message):
            return
        arg = command_args(message).strip().lower()
        if arg in {"off", "none", "clear", "reset"}:
            await chatcfg.set(target, "thumbnail", "")
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('check')} Channel artwork removed — back to the cover art."),
                reply_to=message.id,
            )
            return
        file_id = thumbnail_cmd.photo_file_id(message)
        if not file_id:
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('image')} Reply to a photo with <code>/cthumbnail</code> to set the "
                    "channel's poster art, or <code>/cthumbnail off</code>."
                ),
                reply_to=message.id,
            )
            return
        if thumbnail_cmd.art_too_big(message):
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('warn')} That picture is over "
                    f"{thumbnail_cmd.MAX_ART_BYTES // (1024 * 1024)} MB — a normal photo works best."
                ),
                reply_to=message.id,
            )
            return
        await chatcfg.set(target, "thumbnail", file_id)
        await rich.send(
            client,
            message.chat.id,
            B.note(f"{E('check')} Channel artwork set — every poster in there uses it."),
            reply_to=message.id,
        )


__all__ = ["register"]
