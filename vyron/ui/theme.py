# ---------------------------------------------------------------------------
#  VYRON — theme & premium emoji engine
#
#  Every card renders its glyphs through `E("name")`.  When a premium-emoji
#  pack is configured (emoji.json / PREMIUM_EMOJI_FILE) the glyph is emitted
#  as a real Telegram *custom emoji entity*:
#
#      <tg-emoji emoji-id="5368324170671202286">🎵</tg-emoji>
#
#  ...and when it is not, the plain unicode fallback is used instead.  That
#  means the UI never breaks for deployments without a premium pack, and bots
#  with one get the animated look automatically.
# ---------------------------------------------------------------------------
from __future__ import annotations

from vyron.config import settings

# ── Palette / structure ─────────────────────────────────────────────────────
BRAND = "VYRON"
BRAND_LINE = "◈"
DOT = "•"
DASH = "—"
ARROW = "›"
HEART = "♥"
NBSP = "\u00a0"
ZWSP = "\u200b"

# Decorative separators used across cards.
LINE = "─" * 22
THIN_LINE = "┄" * 24
SPARK = "✦"
BULLET = "▸"

# Font-ish numerals for the "now playing" hero (keeps cards aligned).
SMALL_CAPS = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘQʀꜱᴛᴜᴠᴡxʏᴢ",
)


def small_caps(text: str) -> str:
    return text.translate(SMALL_CAPS)


# ── Default glyph set (unicode) ─────────────────────────────────────────────
# name -> fallback glyph.  A premium pack can override any key; unknown keys
# degrade gracefully to the fallback, so packs can ship partial coverage.
GLYPHS: dict[str, str] = {
    "brand": "🎧",
    "play": "▶️",
    "pause": "⏸️",
    "resume": "▶️",
    "skip": "⏭️",
    "stop": "⏹️",
    "queue": "📜",
    "volume": "🔊",
    "mute": "🔇",
    "loop": "🔁",
    "shuffle": "🔀",
    "search": "🔎",
    "download": "💾",
    "song": "🎵",
    "video": "🎬",
    "lyrics": "📝",
    "favorite": "❤️",
    "star": "⭐",
    "fire": "🔥",
    "spark": "✨",
    "crown": "👑",
    "settings": "⚙️",
    "shield": "🛡️",
    "stats": "📊",
    "clock": "⏱️",
    "user": "👤",
    "users": "👥",
    "chat": "💬",
    "link": "🔗",
    "back": "◀️",
    "close": "✖️",
    "check": "✅",
    "cross": "❌",
    "warn": "⚠️",
    "info": "ℹ️",
    "live": "📡",
    "radio": "📻",
    "rocket": "🚀",
    "bolt": "⚡",
    "heart": "💖",
    "note": "🎶",
    "disc": "💿",
    "headphone": "🎧",
    "microphone": "🎤",
    "gift": "🎁",
    "wave": "🌊",
    "moon": "🌙",
    "sun": "☀️",
    "globe": "🌐",
    "code": "🧩",
    "tools": "🛠️",
    "cloud": "☁️",
    "playlist": "≡",
    "plus": "➕",
    "minus": "➖",
    "id": "🆔",
    "next": "⏭️",
    "web": "🌐",
    "interface": "🪄",
}

# ── Premium-emoji pack loader ───────────────────────────────────────────────
_PACK: dict[str, dict[str, str]] = settings.emoji_map
_PREMIUM_ON = bool(_PACK) and settings.premium_emoji_enabled


def emoji_enabled() -> bool:
    return _PREMIUM_ON


def reload_pack() -> None:
    """Re-read the emoji pack from disk (used by /emojireload)."""
    global _PACK, _PREMIUM_ON
    _PACK = settings.emoji_map
    _PREMIUM_ON = bool(_PACK) and settings.premium_emoji_enabled


def raw_glyph(name: str) -> str:
    """The plain unicode glyph for *name* (never markup)."""
    entry = _PACK.get(name) if _PREMIUM_ON else None
    if entry:
        return entry.get("fallback") or GLYPHS.get(name, "✨")
    return GLYPHS.get(name, "✨")


def E(name: str, fallback: str | None = None) -> str:
    """Premium emoji for *name*, or its unicode fallback."""
    glyph = fallback or GLYPHS.get(name) or "✨"
    if not _PREMIUM_ON:
        return glyph
    entry = _PACK.get(name)
    if not entry:
        return glyph
    custom_id = entry.get("id")
    if not custom_id:
        return glyph
    # Telegram requires the plain emoji as the tag body (accessibility +
    # clients that cannot render custom emoji).
    return f'<tg-emoji emoji-id="{custom_id}">{glyph}</tg-emoji>'


def decor(name: str, text: str) -> str:
    """`glyph text` — the most common card lead-in."""
    return f"{E(name)} {text}"


def pill(name: str, text: str) -> str:
    """Compact `text glyph` used in tables/footers."""
    return f"{text} {E(name)}"


__all__ = [
    "E",
    "BRAND",
    "BULLET",
    "DASH",
    "DOT",
    "LINE",
    "SPARK",
    "THIN_LINE",
    "decor",
    "emoji_enabled",
    "pill",
    "raw_glyph",
    "reload_pack",
    "small_caps",
]
