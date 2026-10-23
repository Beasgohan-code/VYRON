# ---------------------------------------------------------------------------
#  VYRON — Music API commands
#
#  /api              public card: what the API does, base URL, docs button
#  /getapi [label]   owner: mint a key (shown once in full)
#  /listkey          owner: every key with usage, masked
#  /revoke <key>     owner: deactivate a key
#
#  The API itself is served by the same aiohttp process on /v1 — see
#  vyron/web/musicapi.py — so there is nothing to deploy separately.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.config import settings
from vyron.core import acl
from vyron.core.musicapi import get_music_api, mask_key
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args, display_name

logger = logging.getLogger(__name__)


def _base() -> str:
    return settings.api_base or settings.keepalive_url or settings.webapp_url


async def _reply(client: Client, message: Message, markup: str) -> None:
    await rich.send(client, message.chat.id, markup, reply_to=message.id)


def register(client: Client) -> None:
    @client.on_message(filters.command(["api", "musicapi"]))
    async def _api_cmd(_: Client, message: Message) -> None:
        stats = await get_music_api().stats()
        compact = bool(getattr(message.chat, "type", None) and message.chat.type.name != "PRIVATE")
        await _reply(client, message, cards.music_api_card(base=_base(), stats=stats, compact=compact))

    @client.on_message(filters.command(["getapi", "newkey"]) & owner)
    async def _getapi(_: Client, message: Message) -> None:
        label = (command_args(message) or display_name(message.from_user) or "key").strip()[:40]
        record, error = await get_music_api().issue(message.from_user.id, label)
        if record is None:
            await _reply(client, message, cards.error_card(rich.esc(error or "could not create a key")))
            return
        logger.info("api key issued for %s (%s)", message.from_user.id, label)
        await _reply(
            client,
            message,
            cards.api_key_card(
                key=str(record["key"]),
                label=str(record.get("label") or label),
                base=_base(),
                rate=int(settings.music_api_rate),
            ),
        )

    @client.on_message(filters.command(["listkey", "apikeys"]) & owner)
    async def _listkeys(_: Client, message: Message) -> None:
        keys = await get_music_api().keys(reveal=True)
        await _reply(client, message, cards.api_keys_card(keys, base=_base()))

    @client.on_message(filters.command(["revoke", "revokekey"]) & owner)
    async def _revoke(_: Client, message: Message) -> None:
        raw = (command_args(message) or "").strip().split()[0] if command_args(message) else ""
        if not raw:
            await _reply(
                client,
                message,
                cards.warn_card("Usage: <code>/revoke vyrn_…</code> — copy the key from <code>/listkey</code>."),
            )
            return
        narrowed = [item for item in await get_music_api().keys(reveal=True)]
        match = next((item for item in narrowed if str(item.get("key")) == raw), None)
        if match is None:
            match = next((item for item in narrowed if str(item.get("key", "")).startswith(raw)), None)
        if match is None:
            await _reply(client, message, cards.warn_card("No key matches that value."))
            return
        revoked = await get_music_api().revoke(None, str(match["key"]), force=True)
        tone = cards.ok_card if revoked else cards.error_card
        await _reply(
            client,
            message,
            tone(
                f"<b>{'Revoked' if revoked else 'Could not revoke'}</b> "
                f"<code>{mask_key(str(match['key']))}</code>"
                + (f" · {rich.esc(str(match.get('label') or ''))}" if match.get("label") else "")
            ),
        )

    @client.on_message(filters.command(["apiusage"]) & owner)
    async def _apiusage(_: Client, message: Message) -> None:
        api = get_music_api()
        stats = await api.stats()
        roster = await api.keys(reveal=True)
        await _reply(
            client,
            message,
            cards.api_usage_card(stats, roster, base=_base(), sudo=acl.is_sudo(message.from_user.id)),
        )

    logger.debug("music api commands ready (storage=%s)", runtime.storage.backend if runtime.storage else "none")


__all__ = ["register"]
