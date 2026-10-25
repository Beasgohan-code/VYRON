# ---------------------------------------------------------------------------
#  VYRON — custom pyrogram filters
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram import filters
from vyron.utils.helpers import can_control, is_owner


async def _control_check(_, client, message) -> bool:
    return await can_control(client, message)


async def _owner_check(_, client, message) -> bool:
    user = message.from_user
    return bool(user and is_owner(user.id))


control = filters.create(_control_check, "VYRONControl")
owner = filters.create(_owner_check, "VYRONOwner")

group_only = filters.group
private_only = filters.private

__all__ = ["control", "group_only", "owner", "private_only"]
