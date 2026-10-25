# ---------------------------------------------------------------------------
#  VYRON — access control
#
#  `OWNER_ID` and `SUDO_USERS` come from the environment, but the owner can
#  also hand out (and revoke) trust from inside Telegram:
#
#      /addsudo 123456789    /delsudo 123456789    /sudolist
#
#  Runtime grants live in the storage document under the pseudo-chat `0`, so
#  they survive restarts and work with both the JSON and MongoDB backends.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from vyron.config import settings

logger = logging.getLogger(__name__)

SUDO_CHAT = 0
SUDO_KEY = "sudo_users"

_extra: set[int] = set()


def extra_ids() -> set[int]:
    """Ids granted from inside Telegram (env values are not included)."""
    return set(_extra)


def is_sudo(user_id: int) -> bool:
    """True for env sudoers *and* runtime grants."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    return uid in _extra or uid in {int(i) for i in settings.sudo_users}


def roster() -> list[int]:
    """Every privileged id, sorted: owner first, then sudoers."""
    ids = {int(i) for i in settings.sudo_users} | _extra
    if settings.owner_id:
        ids.add(int(settings.owner_id))
    return sorted(ids)


async def load(storage) -> None:
    """Rehydrate runtime grants at boot."""
    if storage is None:
        return
    try:
        data = await storage.chat_settings(SUDO_CHAT)
    except Exception as exc:  # pragma: no cover - storage hiccup
        logger.debug("could not load runtime sudoers: %s", exc)
        return
    raw = data.get(SUDO_KEY) or []
    _extra.clear()
    for item in raw:
        try:
            _extra.add(int(item))
        except (TypeError, ValueError):
            continue
    if _extra:
        logger.info("runtime sudoers: %s", ", ".join(str(i) for i in sorted(_extra)))


async def _persist(storage) -> None:
    if storage is None:
        return
    try:
        await storage.set_chat_setting(SUDO_CHAT, SUDO_KEY, sorted(_extra))
    except Exception as exc:  # pragma: no cover - storage hiccup
        logger.warning("could not persist runtime sudoers: %s", exc)


async def add(storage, user_id: int) -> bool:
    """Grant sudo. Returns False when the id is already privileged."""
    uid = int(user_id)
    if uid in _extra or uid == int(settings.owner_id or 0):
        return False
    if uid in {int(i) for i in settings.sudo_users}:
        return False
    _extra.add(uid)
    await _persist(storage)
    return True


async def remove(storage, user_id: int) -> bool:
    """Revoke a runtime grant. Env-configured sudoers cannot be removed."""
    uid = int(user_id)
    if uid not in _extra:
        return False
    _extra.discard(uid)
    await _persist(storage)
    return True


def reset() -> None:
    """Test helper — forget runtime grants."""
    _extra.clear()


__all__ = ["add", "extra_ids", "is_sudo", "load", "remove", "reset", "roster"]
