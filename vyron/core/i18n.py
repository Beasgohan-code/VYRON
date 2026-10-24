# ---------------------------------------------------------------------------
#  VYRON — languages
#
#  Every string that a listener actually reads lives here as a key. Catalogs
#  are plain dicts, English is the source of truth, and a missing key simply
#  falls back to English — a half-finished translation never shows a blank.
#
#  Adding a language:
#    1. drop ``vyron/locales/<code>.json`` with {"name": …, "strings": {…}}
#       (keys copied from English, values translated), or
#    2. add a dict to ``CATALOGS`` below.
#  Nothing else needs touching: /language reads ``available()`` at call time.
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT = "en"

# code → what /language calls it
NAMES: dict[str, str] = {
    "en": "English",
    "hi": "हिन्दी",
    "ml": "മലയാളം",
    "pa": "ਪੰਜਾਬੀ",
}

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
    # now playing
    "np.streaming": "streaming",
    "np.paused": "paused",
    "np.up_next": "up next",
    "np.queued": "{count} queued",
    "np.now_playing": "now playing",
    "np.by": "by",
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

CATALOGS: dict[str, dict[str, str]] = {
    "en": _EN,
    # ── Hindi ──────────────────────────────────────────────────────────────
    "hi": {
        "lang.title": "भाषा",
        "lang.note": "VYRON के जवाब इस चैट की भाषा में आएंगे। भाषा चुनें — तुरंत लागू होगी।",
        "lang.current": "वर्तमान",
        "lang.saved": "भाषा सहेजी गई।",
        "lang.unknown": "यह भाषा उपलब्ध नहीं है।",
        "lang.admin_only": "यहाँ केवल एडमिन भाषा बदल सकते हैं।",
        "lang.switched": "भाषा {name} कर दी गई।",
        "np.streaming": "चल रहा है",
        "np.paused": "रुका हुआ",
        "np.up_next": "अगला",
        "np.queued": "{count} कतार में",
        "np.now_playing": "अभी चल रहा है",
        "np.by": "द्वारा",
        "ctl.paused": "रोका गया",
        "ctl.resumed": "फिर शुरू",
        "ctl.nothing_playing": "कुछ नहीं चल रहा",
        "ctl.nothing_paused": "कुछ रुका नहीं है",
        "ctl.skipped": "आगे बढ़ाया",
        "ctl.queue_empty": "कतार खाली है",
        "ctl.stopped": "रोका गया और वॉइस चैट छोड़ दी",
        "ctl.volume": "आवाज़: {volume}%",
        "ctl.loop": "लूप: {mode}",
        "ctl.shuffled": "{count} ट्रैक शफल किए",
        "ctl.autoplay_on": "ऑटोप्ले चालू",
        "ctl.autoplay_off": "ऑटोप्ले बंद",
        "ctl.seek": "{time} पर पहुँचे",
    },
    # ── Malayalam ─────────────────────────────────────────────────────────
    "ml": {
        "lang.title": "ഭാഷ",
        "lang.note": "VYRON-ന്റെ മറുപടികൾ ഈ ചാറ്റിന്റെ ഭാഷയിൽ വരും. ഒരു ഭാഷ തിരഞ്ഞെടുക്കുക.",
        "lang.current": "നിലവിലുള്ളത്",
        "lang.saved": "ഭാഷ സേവ് ചെയ്തു.",
        "lang.unknown": "ഈ ഭാഷ ലഭ്യമല്ല.",
        "lang.admin_only": "ഇവിടെ അഡ്മിനുകൾക്ക് മാത്രമേ ഭാഷ മാറ്റാനാകൂ.",
        "lang.switched": "{name} തിരഞ്ഞെടുത്തു.",
        "np.streaming": "പ്ലേ ചെയ്യുന്നു",
        "np.paused": "നിർത്തിവച്ചു",
        "np.up_next": "അടുത്തത്",
        "np.queued": "{count} ക്യൂവിൽ",
        "np.now_playing": "ഇപ്പോൾ പ്ലേ ചെയ്യുന്നത്",
        "np.by": "ഗായകൻ",
        "ctl.paused": "നിർത്തി",
        "ctl.resumed": "തുടർന്നു",
        "ctl.nothing_playing": "ഒന്നും പ്ലേ ചെയ്യുന്നില്ല",
        "ctl.nothing_paused": "ഒന്നും നിർത്തിയിട്ടില്ല",
        "ctl.skipped": "അടുത്തതിലേക്ക് പോയി",
        "ctl.queue_empty": "ക്യൂ ശൂന്യമാണ്",
        "ctl.stopped": "നിർത്തി വോയ്സ് ചാറ്റ് വിട്ടു",
        "ctl.volume": "ശബ്ദം: {volume}%",
        "ctl.loop": "ലൂപ്പ്: {mode}",
        "ctl.shuffled": "{count} ട്രാക്കുകൾ ഷഫിൾ ചെയ്തു",
        "ctl.autoplay_on": "ഓട്ടോപ്ലേ ഓൺ",
        "ctl.autoplay_off": "ഓട്ടോപ്ലേ ഓഫ്",
        "ctl.seek": "{time} ലേക്ക് പോയി",
    },
    # ── Punjabi ───────────────────────────────────────────────────────────
    "pa": {
        "lang.title": "ਭਾਸ਼ਾ",
        "lang.note": "VYRON ਦੇ ਜਵਾਬ ਇਸ ਚੈਟ ਦੀ ਭਾਸ਼ਾ ਵਿੱਚ ਆਉਣਗੇ। ਇੱਕ ਭਾਸ਼ਾ ਚੁਣੋ।",
        "lang.current": "ਮੌਜੂਦਾ",
        "lang.saved": "ਭਾਸ਼ਾ ਸੰਭਾਲੀ ਗਈ।",
        "lang.unknown": "ਇਹ ਭਾਸ਼ਾ ਉਪਲਬਧ ਨਹੀਂ।",
        "lang.admin_only": "ਇੱਥੇ ਸਿਰਫ਼ ਐਡਮਿਨ ਭਾਸ਼ਾ ਬਦਲ ਸਕਦੇ ਹਨ।",
        "lang.switched": "{name} ਚੁਣੀ ਗਈ।",
        "np.streaming": "ਚੱਲ ਰਿਹਾ",
        "np.paused": "ਰੁਕਿਆ",
        "np.up_next": "ਅਗਲਾ",
        "np.queued": "{count} ਕਤਾਰ ਵਿੱਚ",
        "np.now_playing": "ਹੁਣ ਚੱਲ ਰਿਹਾ",
        "np.by": "ਦੁਆਰਾ",
        "ctl.paused": "ਰੋਕਿਆ",
        "ctl.resumed": "ਜਾਰੀ",
        "ctl.nothing_playing": "ਕੁਝ ਨਹੀਂ ਚੱਲ ਰਿਹਾ",
        "ctl.nothing_paused": "ਕੁਝ ਰੁਕਿਆ ਨਹੀਂ",
        "ctl.skipped": "ਅੱਗੇ ਵਧਾਇਆ",
        "ctl.queue_empty": "ਕਤਾਰ ਖਾਲੀ ਹੈ",
        "ctl.stopped": "ਰੋਕਿਆ ਅਤੇ ਵਾਇਸ ਚੈਟ ਛੱਡੀ",
        "ctl.volume": "ਆਵਾਜ਼: {volume}%",
        "ctl.loop": "ਲੂਪ: {mode}",
        "ctl.shuffled": "{count} ਟਰੈਕ ਸ਼ਫਲ ਕੀਤੇ",
        "ctl.autoplay_on": "ਆਟੋਪਲੇ ਚਾਲੂ",
        "ctl.autoplay_off": "ਆਟੋਪਲੇ ਬੰਦ",
        "ctl.seek": "{time} 'ਤੇ ਪਹੁੰਚੇ",
    },
}

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
    "name",
    "resolve",
    "set_for_chat",
]
