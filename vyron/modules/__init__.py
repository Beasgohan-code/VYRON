# ---------------------------------------------------------------------------
#  VYRON — handler modules
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from pyrogram import Client

from vyron.modules import (
    admin,
    assistant_tools,
    convenience,
    callbacks,
    channel,
    controls,
    diagnostics,
    effects_cmd,
    extras,
    groupadmin,
    inline,
    language,
    uistyle,
    doctor,
    locks,
    logs_cmd,
    moderation,
    musicapi_cmd,
    play,
    power,
    privacy,
    queue_cmd,
    savedplaylists,
    settings_cmd,
    smartqueue,
    sources,
    start,
    thumbnail_cmd,
    tools,
)

logger = logging.getLogger(__name__)

MODULES = (
    start,
    play,
    controls,
    queue_cmd,
    settings_cmd,
    tools,
    effects_cmd,
    channel,
    moderation,
    locks,
    groupadmin,
    admin,
    extras,
    language,
    uistyle,
    doctor,
    sources,
    inline,
    callbacks,
    smartqueue,
    thumbnail_cmd,
    savedplaylists,
    diagnostics,
    logs_cmd,
    power,
    assistant_tools,
    convenience,
    musicapi_cmd,
    privacy,
)


def register_all(client: Client) -> list[str]:
    """Attach every handler module to *client* and report what was loaded."""
    loaded: list[str] = []
    for module in MODULES:
        try:
            module.register(client)
            loaded.append(module.__name__.rsplit(".", 1)[-1])
        except Exception as exc:
            logger.exception("failed to load module %s: %s", module.__name__, exc)
    logger.info("handlers loaded: %s", ", ".join(loaded))
    return loaded


__all__ = ["MODULES", "register_all"]
