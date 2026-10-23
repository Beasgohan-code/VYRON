# ---------------------------------------------------------------------------
#  VYRON — per-chat configuration helpers
#
#  Everything chat-scoped (locks, flood limits, warns, welcome text, effects)
#  lives in one document through the Storage interface, so switching between
#  MongoDB and the JSON file needs no code changes.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

from vyron.runtime import runtime

DEFAULTS: dict[str, Any] = {
    "locks": {
        "media": False,
        "links": False,
        "forwards": False,
        "stickers": False,
        "bots": False,
        "commands": False,
        "nsfw": False,
    },
    "flood": {"enabled": True, "limit": 7, "window": 9, "action": "mute"},
    "warns": {},
    "warn_limit": 3,
    "welcome": "",
    "goodbye": "",
    "effects": [],
    "voteskip": 0,
    "channel": 0,
    "thumbnail": "",
}


def _storage():
    return runtime.storage


async def get(chat_id: int, key: str, default: Any = None) -> Any:
    """Read one chat key with a structured default."""
    base = DEFAULTS.get(key)
    if default is None:
        default = base
    storage = _storage()
    if storage is None:
        return default
    data = await storage.chat_settings(chat_id)
    value = data.get(key, default)
    if isinstance(default, dict) and isinstance(value, dict):
        return {**default, **value}
    return value


async def set(chat_id: int, key: str, value: Any) -> None:
    storage = _storage()
    if storage is None:
        return
    await storage.set_chat_setting(chat_id, key, value)


async def toggle(chat_id: int, key: str, item: str, *, default: bool = False) -> bool:
    """Flip ``key[item]`` and return its new value."""
    bucket = await get(chat_id, key, {})
    if not isinstance(bucket, dict):
        bucket = {}
    bucket[item] = not bool(bucket.get(item, default))
    await set(chat_id, key, bucket)
    return bool(bucket[item])


async def replace(chat_id: int, key: str, value: Any) -> Any:
    await set(chat_id, key, value)
    return value


# ── warns ───────────────────────────────────────────────────────────────────
async def add_warn(chat_id: int, user_id: int) -> tuple[int, int]:
    warns = await get(chat_id, "warns", {})
    limit = int(await get(chat_id, "warn_limit", 3) or 3)
    count = int(warns.get(str(user_id), 0)) + 1
    warns[str(user_id)] = count
    await set(chat_id, "warns", warns)
    return count, limit


async def remove_warn(chat_id: int, user_id: int) -> int:
    warns = await get(chat_id, "warns", {})
    count = max(0, int(warns.get(str(user_id), 0)) - 1)
    if count:
        warns[str(user_id)] = count
    else:
        warns.pop(str(user_id), None)
    await set(chat_id, "warns", warns)
    return count


async def warns_of(chat_id: int, user_id: int) -> int:
    warns = await get(chat_id, "warns", {})
    return int(warns.get(str(user_id), 0))


async def reset_warns(chat_id: int) -> int:
    warns = await get(chat_id, "warns", {})
    cleared = sum(int(v) for v in warns.values())
    await set(chat_id, "warns", {})
    return cleared


# ── placeholders for welcome / goodbye text ────────────────────────────────
def render(template: str, **values: Any) -> str:
    """Fill ``{mention}``-style placeholders; unknown ones are left untouched."""
    if not template:
        return ""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value if value is not None else ""))
    return out


__all__ = [
    "DEFAULTS",
    "add_warn",
    "get",
    "remove_warn",
    "render",
    "replace",
    "reset_warns",
    "set",
    "toggle",
    "warns_of",
]
