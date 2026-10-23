# ---------------------------------------------------------------------------
#  VYRON — data behind the chat settings panel
#
#  The panel is shown from three places (`/settings`, the `v:set:*` buttons and
#  `v:lang:*`), and each one used to assemble its own partial dictionary — so
#  the Language row said "English" in Hindi chats and the Artwork row did not
#  exist at all. One collector, every caller.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any

from vyron.core import chatcfg, i18n


async def chat_panel(chat_id: int, state: Any) -> dict:
    """Everything `cards.settings_card` and `keyboards.settings_panel` need."""
    return {
        "volume": getattr(state, "volume", 70),
        "loop": getattr(getattr(state, "loop", None), "value", "off"),
        "autoplay": bool(getattr(state, "autoplay", True)),
        "always_on": bool(getattr(state, "always_on", False)),
        "poster": await chatcfg.get(chat_id, "poster", True),
        "thumbnail": bool(await chatcfg.get(chat_id, "thumbnail", "") or ""),
        "lang": (await i18n.for_chat(chat_id)).code,
    }


__all__ = ["chat_panel"]
