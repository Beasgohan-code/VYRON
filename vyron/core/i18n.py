# ---------------------------------------------------------------------------
#  VYRON — languages
#
#  Every string that a listener actually reads lives here as a key. Catalogs
#  are plain dicts, English is the source of truth, and a missing key simply
#  falls back to English — a half-finished translation never shows a blank.
#
#  Adding a language is one file: drop ``vyron/locales/<code>.json`` with
#  {"name": …, "strings": {…}} — keys copied from English, values translated.
#  Nothing else needs touching: /language reads ``available()`` at call time,
#  the picker pages itself, and `/setlang <code>` accepts the new code at once.
#
#  A catalog is only *complete* when it carries every English key: the tests
#  refuse to ship a half translation, and ``coverage()`` is what the picker
#  shows for a file somebody added by hand.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT = "en"

# code → what /language calls it.  JSON locales fill this in themselves; the
# entry here is the fallback for English (which has no file — it *is* the keys).
NAMES: dict[str, str] = {"en": "English"}

# Right-to-left scripts.  Nothing in a Rich card needs flipping, but the Mini
# App renders the native names itself and has to.
RTL: frozenset[str] = frozenset({"ar", "ur", "fa", "he", "ps", "sd"})

# ── English: the reference catalog ─────────────────────────────────────────
_EN: dict[str, str] = {
    # language picker
    "lang.title": "language",
    "lang.note": "VYRON's replies follow this chat. Pick a language — it applies instantly.",
    "lang.current": "current",
    "lang.saved": "Language saved.",
    "lang.unknown": "That language isn't available.",
    "lang.admin_only": "Only admins can change the language here.",
    "lang.switched": "Switched to {name}.",
    "lang.page": "page {page}/{pages}",
    # now playing
    "np.streaming": "streaming",
    "np.paused": "paused",
    "np.up_next": "up next",
    "np.queued": "{count} queued",
    "np.now_playing": "now playing",
    "np.by": "by",
    # The poster's own badge. It was read by `cards.now_playing_caption` but
    # never existed here, so every language printed the literal "np.live".
    "np.live": "live",
    # control acknowledgements
    "ctl.paused": "Paused",
    "ctl.resumed": "Resumed",
    "ctl.nothing_playing": "Nothing is playing",
    "ctl.nothing_paused": "Nothing is paused",
    "ctl.skipped": "Skipped",
    "ctl.queue_empty": "Queue is empty",
    "ctl.stopped": "Stopped and left the voice chat",
    "ctl.volume": "Volume: {volume}%",
    "ctl.loop": "Loop: {mode}",
    "ctl.shuffled": "Shuffled {count} tracks",
    "ctl.autoplay_on": "Autoplay is on",
    "ctl.autoplay_off": "Autoplay is off",
    "ctl.seek": "Jumped to {time}",
}

# English is the only catalog in code: it is the reference every other one is
# measured against.  Everything else is a file under ``vyron/locales/``.
CATALOGS: dict[str, dict[str, str]] = {"en": _EN}


_LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"


class Catalog(dict):
    """A language's strings, with English behind every missing key."""

    def __init__(self, code: str, strings: dict[str, str], name: str = "") -> None:
        super().__init__(_EN)
        self.update(strings)
        self.code = code
        self.name = name or NAMES.get(code, code.upper())

    def t(self, key: str, **values: Any) -> str:
        raw = self.get(key) or _EN.get(key) or key
        if not values:
            return raw
        try:
            return raw.format(**values)
        except (KeyError, IndexError, ValueError):  # a bad translation must not raise
            return raw


def _load_json_locales() -> None:
    """Pick up ``vyron/locales/*.json`` — translations need no code change."""
    if not _LOCALES_DIR.is_dir():
        return
    for path in sorted(_LOCALES_DIR.glob("*.json")):
        code = path.stem.lower()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # broken file: skip it, keep booting
            logger.warning("ignoring locale %s: %s", path.name, exc)
            continue
        if not isinstance(payload, dict):
            continue
        strings = payload.get("strings")
        if not isinstance(strings, dict):
            continue
        CATALOGS[code] = {str(k): str(v) for k, v in strings.items()}
        name = payload.get("name")
        if isinstance(name, str) and name.strip():
            NAMES[code] = name.strip()


_load_json_locales()

_CACHE: dict[str, Catalog] = {}


def resolve(code: str | None) -> str:
    """Map anything to a language we can actually render."""
    raw = str(code or "").strip().lower().replace("_", "-")
    if raw in CATALOGS:
        return raw
    base = raw.split("-", 1)[0]
    return base if base in CATALOGS else DEFAULT


def catalog(code: str | None = None) -> Catalog:
    key = resolve(code)
    cached = _CACHE.get(key)
    if cached is None:
        cached = Catalog(key, CATALOGS.get(key, {}), NAMES.get(key, key.upper()))
        _CACHE[key] = cached
    return cached


def available() -> dict[str, str]:
    """code → display name, English first, then alphabetical."""
    codes = sorted(CATALOGS, key=lambda item: (item != DEFAULT, item))
    return {code: NAMES.get(code, code.upper()) for code in codes}


def name(code: str | None) -> str:
    return NAMES.get(resolve(code), resolve(code).upper())


def is_rtl(code: str | None) -> bool:
    """True for a right-to-left script, so a renderer knows to flip."""
    return resolve(code) in RTL


def is_known(code: str | None) -> bool:
    return str(code or "").strip().lower() in CATALOGS


def missing(code: str | None) -> list[str]:
    """Keys English has that this catalog does not translate.

    A missing key falls back to English (that is deliberate), but a *half*
    translation is invisible until somebody sees the wrong language mid-card —
    so this is the number `/language` and the tests look at.
    """
    target = CATALOGS.get(resolve(code)) or {}
    return sorted(key for key in _EN if key not in target)


def stray(code: str | None) -> list[str]:
    """Keys a catalog carries that English does not — usually a typo."""
    target = CATALOGS.get(resolve(code)) or {}
    return sorted(key for key in target if key not in _EN)


def coverage() -> dict[str, float]:
    """code → percentage of the English catalog that is translated."""
    total = max(1, len(_EN))
    return {
        code: round(100.0 * (total - len(missing(code))) / total, 1)
        for code in available()
    }


async def for_chat(chat_id: int) -> Catalog:
    """This chat's language, read from the per-chat config."""
    try:
        from vyron.core import chatcfg

        return catalog(await chatcfg.get(chat_id, "lang", "") or "")
    except Exception:  # pragma: no cover - never break a reply over a setting
        return catalog()


async def set_for_chat(chat_id: int, code: str) -> str:
    """Persist a language choice; returns the code that is now in effect."""
    chosen = resolve(code)
    from vyron.core import chatcfg

    await chatcfg.set(chat_id, "lang", chosen)
    return chosen


__all__ = [
    "CATALOGS",
    "RTL",
    "Catalog",
    "DEFAULT",
    "NAMES",
    "available",
    "coverage",
    "missing",
    "stray",
    "catalog",
    "for_chat",
    "is_known",
    "is_rtl",
    "name",
    "resolve",
    "set_for_chat",
]
