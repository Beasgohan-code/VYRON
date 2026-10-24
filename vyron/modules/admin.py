# ---------------------------------------------------------------------------
#  VYRON — owner / maintenance commands
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import re

from pyrogram import Client
from pyrogram.errors import FloodWait
from pyrogram.types import Message

from vyron.runtime import runtime
from vyron.config import settings
from vyron.core.musicapi import get_music_api
from vyron.ui import blocks as B
from vyron.ui import cards, rich
from vyron.ui.theme import E, reload_pack
from vyron.utils.helpers import command_args, is_private_chat

logger = logging.getLogger(__name__)
from vyron.utils.filters import owner
from vyron.utils.commands import cmd


# ── /broadcast flags (ported from ShizuMusic) ────────────────────────────────
def _parse_flags(raw: str) -> tuple[bool, bool, bool, bool]:
    """`-pin` must not match inside `-pinloud` (a real bug in the original)."""
    pin = bool(re.search(r"-pin(?!loud)", raw))
    return pin, "-pinloud" in raw, "-nogroup" in raw, "-user" in raw


def _strip_flags(text: str) -> str:
    """Remove every flag token, leaving the message content behind."""
    for flag in ("-pinloud", "-nogroup", "-user", "-pin"):
        text = text.replace(flag, "")
    return text.strip()


def register(client: Client) -> None:
    @client.on_message(cmd(["stats"]))
    async def _stats(_: Client, message: Message) -> None:
        if not runtime.storage:
            return
        counters = await runtime.storage.counters()
        chats = len(await runtime.storage.all_chat_ids())
        active = len(runtime.player.active_chats()) if runtime.player else 0
        cache = runtime.downloader.cache_size() if runtime.downloader else 0
        api_stats = await get_music_api().stats()
        from vyron.utils import sysinfo

        system = await asyncio.to_thread(sysinfo.snapshot)
        links: dict[str, str] = {}
        sender = message.from_user.id if message.from_user else 0
        if sender and sender in settings.owners:
            root = (settings.api_base or settings.keepalive_url or settings.webapp_url or "").rstrip("/")
            if root:
                links["api"] = f"{root}/v1/docs"
            if settings.webapp_ready and is_private_chat(message.chat):
                # Presence only: the button itself carries no URL.
                links["player"] = "1"
        markup = cards.stats_card(
            uptime=runtime.uptime,
            chats=chats,
            active=active,
            tracks=counters.get("tracks", runtime.player.tracks_played if runtime.player else 0),
            downloads=counters.get("downloads", 0),
            cache_bytes=cache,
            backend=runtime.storage.backend,
            version=runtime.version,
            api=api_stats,
            links=links,
            system=system,
        )
        await rich.send(client, message.chat.id, markup, reply_to=message.id)

    @client.on_message(cmd("active") & owner)
    async def _active(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        lines = []
        for chat_id in runtime.player.active_chats():
            state = runtime.player.queues.get(chat_id)
            if state.current:
                lines.append(f"• <code>{chat_id}</code> — {rich.esc(state.current.title[:40])}")
        await rich.send(
            client,
            message.chat.id,
            cards.change_card(
                "active sessions",
                glyph="live",
                label="voice chats",
                value=f"<b>{len(lines)}</b>",
                note="Every chat with a live stream right now.",
                extra=[("live", f"chat {index}", line)
                       for index, line in enumerate(lines[:10], start=1)],
                actions=B.row(
                    B.btn(f"{E('stats')} Statistics", data="v:admin:stats", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                ),
            ),
        )

    # ── /broadcast — flags, forward→copy fallback, one run at a time ──────
    broadcast_lock = asyncio.Lock()
    broadcast_running = {"on": False}

    async def _deliver(chat_id: int, source: Message | None, text: str) -> Message:
        """Reply content is forwarded when possible; copy is the fallback."""
        if source is not None:
            try:
                return await source.forward(chat_id, disable_notification=True)
            except Exception:
                return await source.copy(chat_id, disable_notification=True)
        return await client.send_message(chat_id, text)

    @client.on_message(cmd(["broadcast"]) & owner)
    async def _broadcast(_: Client, message: Message) -> None:
        if broadcast_running["on"]:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card("A broadcast is already running — let it finish."),
                reply_to=message.id,
            )
            return
        raw = command_args(message)
        pin, pinloud, nogroup, to_users = _parse_flags(raw)
        text = _strip_flags(raw)
        source = message.reply_to_message
        if not text and not source:
            await rich.send(
                client,
                message.chat.id,
                cards.error_card(
                    "Usage: <code>/broadcast [-pin] [-pinloud] [-nogroup] [-user] text</code>\n"
                    "…or reply to any message with <code>/broadcast</code>."
                ),
                reply_to=message.id,
            )
            return
        if not runtime.storage:
            return

        chat_ids = await runtime.storage.all_chat_ids()
        groups = [cid for cid in chat_ids if cid < 0]
        users = [cid for cid in chat_ids if cid > 0]
        targets: list[int] = []
        if not nogroup:
            targets += groups
        if to_users:
            targets += users
        if not targets:
            await rich.send(
                client,
                message.chat.id,
                cards.warn_card(
                    "No targets — <code>-nogroup</code> skips groups and "
                    "private chats are only included with <code>-user</code>."
                ),
                reply_to=message.id,
            )
            return

        flags = " ".join(
            flag
            for flag, on in (
                ("-pin", pin),
                ("-pinloud", pinloud),
                ("-nogroup", nogroup),
                ("-user", to_users),
            )
            if on
        ) or "none"
        status = await rich.send(
            client,
            message.chat.id,
            B.banner("broadcast", glyph="rocket")
            + B.kv(
                [
                    (f"{E('chat')} groups", f"<b>{0 if nogroup else len(groups)}</b>"),
                    (f"{E('user')} users", f"<b>{len(users)}</b>" if to_users else "skipped"),
                    (f"{E('bolt')} targets", f"<b>{len(targets)}</b>"),
                    (f"{E('note')} flags", f"<code>{flags}</code>"),
                ]
            ),
        )

        sent = failed = pinned = 0
        broadcast_running["on"] = True
        try:
            async with broadcast_lock:
                for index, chat_id in enumerate(targets, start=1):
                    for attempt in (1, 2):
                        try:
                            delivered = await _deliver(chat_id, source, text)
                            sent += 1
                            if pin or pinloud:
                                try:
                                    await client.pin_chat_message(
                                        chat_id,
                                        delivered.id,
                                        disable_notification=not pinloud,
                                    )
                                    pinned += 1
                                except Exception:
                                    pass
                            break
                        except FloodWait as exc:
                            # Telegram's rate limit is a pause, not a failure.
                            wait = int(getattr(exc, "value", 5) or 5) + 1
                            if attempt == 1 and wait <= 200:
                                logger.info("broadcast flood wait %ss", wait)
                                await asyncio.sleep(wait)
                                continue
                            failed += 1
                        except Exception as exc:
                            logger.debug("broadcast %s failed: %s", chat_id, exc)
                            failed += 1
                            break
                    if status and index % 10 == 0:
                        await rich.edit(
                            client,
                            message.chat.id,
                            status.id,
                            B.banner("broadcasting…", glyph="rocket")
                            + B.kv(
                                [
                                    (f"{E('bolt')} progress", f"<b>{index}/{len(targets)}</b>"),
                                    (f"{E('check')} sent", f"<b>{sent}</b>"),
                                    (f"{E('cross')} failed", f"<b>{failed}</b>"),
                                ]
                            ),
                        )
                    await asyncio.sleep(0.4)
        finally:
            broadcast_running["on"] = False

        if status:
            await rich.edit(
                client,
                message.chat.id,
                status.id,
                cards.ok_card(
                    f"<b>Broadcast finished</b> — {sent} sent"
                    + (f", {pinned} pinned" if pinned else "")
                    + (f", {failed} failed" if failed else "")
                    + f" of {len(targets)}."
                ),
            )

    @client.on_message(cmd(["leaveall"]) & owner)
    async def _leaveall(_: Client, message: Message) -> None:
        if not runtime.player:
            return
        chats = runtime.player.active_chats()
        for chat_id in chats:
            await runtime.player.leave(chat_id)
        await rich.send(
            client,
            message.chat.id,
            cards.ok_card(f"<b>Left {len(chats)} voice chats</b>"),
            reply_to=message.id,
        )

    @client.on_message(cmd(["emojireload", "reload"]) & owner)
    async def _reload(_: Client, message: Message) -> None:
        reload_pack()
        await rich.send(
            client,
            message.chat.id,
            cards.ok_card("<b>Emoji pack reloaded</b>"),
            reply_to=message.id,
        )


__all__ = ["register"]
