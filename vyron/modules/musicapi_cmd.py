# ---------------------------------------------------------------------------
#  VYRON — Music API commands
#
#  /api [metrics]                 card: what the API does, base URL, docs
#  /getapi [label] [scopes=…] [days=N]   owner: mint a key (shown once)
#  /listkey                       owner: every key with scopes + usage
#  /revoke <id|prefix|key>        owner: deactivate a key
#  /rotatekey <id|prefix>         owner: swap a key, old one dies instantly
#  /apiusage                      owner: traffic, latency and per-key meters
#  /apitoken                      owner: signed token for the web app + API
#
#  The API itself is served by the same aiohttp process on /v1 — see
#  vyron/api/ — so there is nothing to deploy separately.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.api.metrics import METRICS
from vyron.config import settings
from vyron.core import acl
from vyron.core.musicapi import SCOPES, find_key, get_music_api, mask_key, normalise_scopes
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args, display_name, is_private_chat
from vyron.web.auth import OWNER_TOKEN_TTL, make_owner_token

logger = logging.getLogger(__name__)


def _base() -> str:
    return settings.api_base or settings.keepalive_url or settings.webapp_url


async def _reply(client: Client, message: Message, markup: str) -> None:
    await rich.send(client, message.chat.id, markup, reply_to=message.id)


async def _reply_private(client: Client, message: Message, markup: str, what: str = "Key") -> None:
    """Secrets never go to a group — deliver them in the caller's DM."""
    if getattr(message.chat.type, "name", "") == "PRIVATE":
        await _reply(client, message, markup)
        return
    try:
        await rich.send(client, message.from_user.id, markup)
    except Exception as exc:  # owner has never started the bot in DM
        logger.info("could not DM %s: %s", message.from_user.id, exc)
        await _reply(
            client,
            message,
            cards.warn_card(
                f"<b>{what} not sent</b> — open a private chat with me first, then run the "
                f"command again. Secrets are never posted in groups."
            ),
        )
        return
    await _reply(
        client,
        message,
        cards.ok_card(f"{what} sent to your DM {E('shield')}"),
    )


def parse_key_args(raw: str) -> dict:
    """Parse `label scopes=read,search days=30 rate=60` (all optional)."""
    label: list[str] = []
    scopes: list[str] = []
    days: int | None = None
    rate: int | None = None
    for token in (raw or "").split():
        low = token.lower()
        if low.startswith(("scopes=", "scope=")):
            scopes += [chunk for chunk in low.split("=", 1)[1].replace("+", ",").split(",") if chunk]
        elif low.startswith("days=") and low[5:].isdigit():
            days = int(low[5:])
        elif low.startswith("rate=") and low[5:].isdigit():
            rate = int(low[5:])
        elif low.endswith("d") and low[:-1].isdigit():
            days = int(low[:-1])
        elif low in SCOPES or low in {"all", "*"}:
            scopes.append(low)
        else:
            label.append(token)
    return {
        "label": " ".join(label).strip()[:40],
        "scopes": normalise_scopes(scopes) if scopes else None,
        "days": days,
        "rate_limit": rate,
    }


def register(client: Client) -> None:
    @client.on_message(filters.command(["api", "musicapi"]))
    async def _api_cmd(_: Client, message: Message) -> None:
        api = get_music_api()
        stats = await api.stats()
        compact = bool(getattr(message.chat, "type", None) and message.chat.type.name != "PRIVATE")
        sender = message.from_user.id if message.from_user else 0
        owner = bool(sender and sender in settings.owners and is_private_chat(message.chat))
        await _reply(
            client,
            message,
            cards.music_api_card(
                base=_base(),
                stats=stats,
                compact=compact,
                metrics=METRICS.snapshot(),
                owner=owner,
            ),
        )

    @client.on_message(filters.command(["getapi", "newkey"]) & owner)
    async def _getapi(_: Client, message: Message) -> None:
        raw = command_args(message) or ""
        options = parse_key_args(raw)
        record, error = await get_music_api().issue(
            message.from_user.id,
            options["label"] or display_name(message.from_user) or "key",
            scopes=options["scopes"],
            days=options["days"],
            rate_limit=options["rate_limit"],
        )
        if record is None:
            await _reply(client, message, cards.error_card(rich.esc(error or "could not create a key")))
            return
        logger.info("api key issued for %s (%s)", message.from_user.id, record.get("label"))
        await _reply_private(
            client,
            message,
            cards.api_key_card(
                key=str(record["key"]),
                label=str(record.get("label") or "key"),
                base=_base(),
                rate=int(record.get("rate_limit") or settings.music_api_rate),
                scopes=record.get("scopes"),
                expires_at=record.get("expires_at"),
                owner_id=record.get("owner_id"),
            ),
            what="API key",
        )

    @client.on_message(filters.command(["listkey", "apikeys"]) & owner)
    async def _listkeys(_: Client, message: Message) -> None:
        keys = await get_music_api().keys(reveal=False)
        await _reply_private(
            client,
            message,
            cards.api_keys_card(keys, base=_base()),
            what="Key list",
        )

    @client.on_message(filters.command(["rotatekey", "rotateapi"]) & owner)
    async def _rotate(_: Client, message: Message) -> None:
        needle = (command_args(message) or "").strip().split()[0] if command_args(message) else ""
        if not needle:
            await _reply(
                client,
                message,
                cards.warn_card(
                    "Usage: <code>/rotatekey &lt;id|prefix&gt;</code> — ids come from "
                    "<code>/listkey</code>. The old key dies the moment the new one is issued."
                ),
            )
            return
        keys = await get_music_api().keys(reveal=False)
        match = find_key(keys, needle)
        if match is None:
            await _reply(client, message, cards.warn_card("No key matches that id or prefix."))
            return
        record, error = await get_music_api().rotate(
            int(match.get("owner_id") or message.from_user.id), str(match.get("id"))
        )
        if record is None:
            await _reply(client, message, cards.error_card(rich.esc(error or "could not rotate that key")))
            return
        await _reply_private(
            client,
            message,
            cards.api_key_card(
                key=str(record["key"]),
                label=str(record.get("label") or "key"),
                base=_base(),
                rate=int(record.get("rate_limit") or settings.music_api_rate),
                scopes=record.get("scopes"),
                expires_at=record.get("expires_at"),
                owner_id=record.get("owner_id"),
            ),
            what="API key",
        )

    @client.on_message(filters.command(["revoke", "revokekey"]) & owner)
    async def _revoke(_: Client, message: Message) -> None:
        needle = (command_args(message) or "").strip().split()[0] if command_args(message) else ""
        if not needle:
            await _reply(
                client,
                message,
                cards.warn_card(
                    "Usage: <code>/revoke &lt;id|prefix|key&gt;</code> — copy it from <code>/listkey</code>."
                ),
            )
            return
        keys = await get_music_api().keys(reveal=False)
        match = find_key(keys, needle)
        revoked = await get_music_api().revoke(
            None, str((match or {}).get("id") or needle), force=True
        )
        tone = cards.ok_card if revoked else cards.error_card
        await _reply(
            client,
            message,
            tone(
                f"<b>{'Revoked' if revoked else 'Could not revoke'}</b> "
                f"<code>{mask_key(str((match or {}).get('prefix') or needle))}</code>"
                + (f" · {rich.esc(str(match.get('label') or ''))}" if (match or {}).get("label") else "")
            ),
        )

    @client.on_message(filters.command(["apiusage"]) & owner)
    async def _apiusage(_: Client, message: Message) -> None:
        api = get_music_api()
        stats = await api.stats()
        roster = await api.keys(reveal=False)
        await _reply_private(
            client,
            message,
            cards.api_usage_card(
                stats,
                roster,
                base=_base(),
                sudo=acl.is_sudo(message.from_user.id),
                metrics=METRICS.snapshot(),
            ),
            what="Usage report",
        )

    @client.on_message(filters.command(["apitoken", "ownertoken", "ownerkey"]) & owner)
    async def _apitoken(_: Client, message: Message) -> None:
        if not settings.bot_token:
            await _reply(client, message, cards.error_card("Set <code>BOT_TOKEN</code> first."))
            return
        token = make_owner_token(settings.bot_token, message.from_user.id)
        logger.info("owner token issued for %s", message.from_user.id)
        await _reply_private(
            client,
            message,
            cards.owner_access_card(
                token,
                _base() or "",
                owner_id=message.from_user.id,
                ttl_days=OWNER_TOKEN_TTL // 86400,
            ),
            what="Owner token",
        )

    logger.debug(
        "music api commands ready (storage=%s, since %s)",
        runtime.storage.backend if runtime.storage else "none",
        time.strftime("%H:%M"),
    )


__all__ = ["parse_key_args", "register"]
