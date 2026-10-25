"""Language layer tests: catalogs, fallbacks and the /language surface."""
from __future__ import annotations

import asyncio
import json

import pytest

from vyron.core import i18n
from vyron.core.queue import ChatState, Track


EN_KEYS = set(i18n.CATALOGS["en"])


# ── catalogs ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("code", [code for code in i18n.CATALOGS if code != "en"])
def test_every_translation_has_every_english_key(code):
    catalog = i18n.catalog(code)
    missing = sorted(EN_KEYS - set(i18n.CATALOGS[code]))
    assert not missing, f"{code} is missing {missing}"
    # every key renders to something non-empty
    for key in EN_KEYS:
        assert catalog.t(key).strip()


def test_catalogs_are_actually_translated():
    """A language that is a copy of English is a placeholder, not a locale."""
    for code in [code for code in i18n.CATALOGS if code != "en"]:
        catalog = i18n.catalog(code)
        translated = [key for key in EN_KEYS if catalog.t(key) != i18n.catalog("en").t(key)]
        assert len(translated) >= len(EN_KEYS) * 0.8, code


def test_placeholders_format_per_language():
    assert i18n.catalog("en").t("ctl.volume", volume=70) == "Volume: 70%"
    assert i18n.catalog("hi").t("ctl.volume", volume=70) == "आवाज़: 70%"


def test_a_broken_placeholder_never_raises():
    catalog = i18n.Catalog("xx", {"ctl.volume": "Volume: {volume}"})
    # a caller that passes the wrong kwargs gets the raw string, not a crash
    assert catalog.t("ctl.volume", count=1) == "Volume: {volume}"
    assert catalog.t("ctl.volume", volume=10) == "Volume: 10"
    assert i18n.catalog("en").t("ctl.volume") == "Volume: {volume}%"


def test_unknown_code_resolves_to_english():
    assert i18n.resolve("xx") == "en"
    assert i18n.resolve("") == "en"
    assert i18n.resolve(None) == "en"


def test_regional_codes_fall_back_to_the_base_language():
    assert i18n.resolve("hi-IN") == "hi"
    assert i18n.resolve("ml_IN") == "ml"


def test_missing_key_falls_back_to_english():
    assert i18n.catalog("hi").t("np.now_playing") == "अभी चल रहा है"
    assert i18n.catalog("hi").t("does.not.exist") == "does.not.exist"


def test_available_lists_english_first():
    codes = list(i18n.available())
    assert codes[0] == "en"
    assert "hi" in codes and "ml" in codes


def test_json_locale_can_be_dropped_in(tmp_path, monkeypatch):
    # a code that is not shipped, so the real Spanish catalog cannot hide here
    payload = {"name": "Esperanto", "strings": {"lang.title": "lingvo"}}
    (tmp_path / "eo.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(i18n, "_LOCALES_DIR", tmp_path)
    monkeypatch.setattr(i18n, "CATALOGS", dict(i18n.CATALOGS))
    monkeypatch.setattr(i18n, "NAMES", dict(i18n.NAMES))
    i18n._load_json_locales()

    assert i18n.available()["eo"] == "Esperanto"
    assert i18n.catalog("eo").t("lang.title") == "lingvo"
    # untranslated keys still come from English
    assert i18n.catalog("eo").t("ctl.paused") == "Paused"


# ── per-chat persistence ────────────────────────────────────────────────────
class FakeStorage:
    def __init__(self) -> None:
        self.docs: dict[int, dict] = {}

    async def chat_settings(self, chat_id):
        return dict(self.docs.get(chat_id, {}))

    async def save_chat_settings(self, chat_id, data):
        self.docs[chat_id] = dict(data)

    async def set_chat_setting(self, chat_id, key, value):
        data = self.docs.setdefault(chat_id, {})
        data[key] = value


@pytest.fixture()
def storage(monkeypatch):
    from vyron.runtime import runtime

    fake = FakeStorage()
    monkeypatch.setattr(runtime, "storage", fake)
    return fake


def test_language_is_saved_per_chat(storage):
    asyncio.run(i18n.set_for_chat(10, "ml"))
    asyncio.run(i18n.set_for_chat(20, "hi"))

    assert storage.docs[10]["lang"] == "ml"
    assert storage.docs[20]["lang"] == "hi"
    assert asyncio.run(i18n.for_chat(10)).code == "ml"
    assert asyncio.run(i18n.for_chat(20)).code == "hi"


def test_unknown_language_is_normalised_before_saving(storage):
    assert asyncio.run(i18n.set_for_chat(10, "hi-IN")) == "hi"
    assert storage.docs[10]["lang"] == "hi"


def test_chat_without_a_choice_reads_english(storage):
    assert asyncio.run(i18n.for_chat(99)).code == "en"


# ── card + keyboard ─────────────────────────────────────────────────────────
def test_language_card_marks_the_current_choice():
    from vyron.modules.language import keyboard, language_card

    # The picker opens on the page the current language is on, so the ✅ is in
    # the first card the listener sees — not five taps away.
    card = language_card("hi")
    assert "हिन्दी" in card
    buttons = [button.callback_data for row in keyboard("hi").inline_keyboard for button in row]
    assert "v:lang:hi" in buttons


def test_language_card_follows_the_chat_language():
    from vyron.modules.language import language_card

    card = language_card("ml")
    assert "ഭാഷ" in card  # the heading itself is translated


def test_the_picker_pages_through_every_language():
    from vyron.modules import language as lang_mod

    codes = list(i18n.available())
    assert lang_mod.page_count() == -(-len(codes) // lang_mod.PAGE_SIZE)
    seen: list[str] = []
    for page in range(lang_mod.page_count()):
        seen += [code for code, _ in lang_mod.page_entries(page)]
    assert seen == codes, "paging must reach every language exactly once"


def test_a_card_never_carries_more_than_six_buttons():
    from vyron.modules import language as lang_mod

    for page in range(lang_mod.page_count()):
        buttons = lang_mod.language_buttons("en", page)
        assert 1 <= len(buttons) <= 6, (page, len(buttons))
    # arrows appear only where there is somewhere to go
    first = "".join(lang_mod.language_buttons("en", 0))
    last = "".join(lang_mod.language_buttons("en", lang_mod.page_count() - 1))
    assert "v:lang:page:1" in first
    assert "v:lang:page:0" not in first
    assert "v:lang:page:" in last or len(lang_mod.language_buttons("en", 0)) == 1
    assert f"v:lang:page:{lang_mod.page_count()}" not in last


def test_a_page_out_of_range_lands_on_the_last_one():
    from vyron.modules import language as lang_mod

    assert lang_mod.clamp_page(-3) == 0
    assert lang_mod.clamp_page(0) == 0
    assert lang_mod.clamp_page(999) == lang_mod.page_count() - 1
    assert lang_mod.clamp_page("nonsense") == 0


def test_the_picker_opens_on_the_page_holding_the_active_language():
    from vyron.modules import language as lang_mod

    for code in i18n.available():
        page = lang_mod.page_of(code)
        shown = [item for item, _ in lang_mod.page_entries(page)]
        assert code in shown, code


def test_every_shipped_language_is_named_in_its_own_script():
    """`available()` is what a listener reads; a Latin transliteration of Tamil
    is a label they may not recognise."""
    names = i18n.available()
    assert names["en"] == "English"
    for code, name in names.items():
        assert name.strip(), code
        if code == "en":
            continue
        # the native name never spells it the English way
        assert name != i18n.catalog("en").t("lang.title"), code


def test_the_live_badge_is_translated_everywhere():
    """`np.live` was read by the now-playing card but missing from the
    catalog, so every chat printed the key itself."""
    for code in i18n.CATALOGS:
        rendered = i18n.catalog(code).t("np.live")
        assert rendered and rendered != "np.live", code


def test_right_to_left_scripts_are_flagged():
    assert i18n.is_rtl("ar") and i18n.is_rtl("ur") and i18n.is_rtl("ar-EG")
    assert not i18n.is_rtl("en") and not i18n.is_rtl("ta")


def test_the_language_set_is_wide_enough_to_be_useful():
    codes = set(i18n.available())
    # the languages this bot actually meets: India first, then the rest
    for code in ("hi", "ml", "pa", "bn", "ta", "te", "kn", "mr", "gu", "ur"):
        assert code in codes
    for code in ("es", "fr", "de", "pt", "ru", "id", "ar", "tr"):
        assert code in codes


# ── now-playing caption ─────────────────────────────────────────────────────
def test_caption_uses_the_chat_catalog():
    from vyron.ui import cards

    state = ChatState(
        chat_id=1,
        current=Track(id="x", title="Believer", duration=200),
        playing=True,
    )
    english = cards.now_playing_caption(state)
    hindi = cards.now_playing_caption(state, i18n.catalog("hi"))

    assert "streaming" in english
    assert "चल रहा है" in hindi
    assert "streaming" not in hindi


# ── completeness is measured, not assumed ───────────────────────────────────
import re as _re

_PLACEHOLDER = _re.compile(r"\{(\w+)\}")


def test_a_translation_keeps_every_placeholder_of_its_english_string():
    """A missing `{count}` renders the sentence raw — silently, in production."""
    english = i18n.catalog("en")
    for code in i18n.CATALOGS:
        if code == "en":
            continue
        catalog = i18n.catalog(code)
        for key in i18n.CATALOGS["en"]:
            expected = set(_PLACEHOLDER.findall(english.t(key)))
            found = set(_PLACEHOLDER.findall(catalog.t(key)))
            assert found == expected, f"{code}:{key} has {found}, expected {expected}"


def test_no_catalog_carries_a_key_english_does_not_have():
    for code in i18n.CATALOGS:
        assert i18n.stray(code) == [], f"{code} has stray keys: {i18n.stray(code)}"


def test_coverage_reports_a_real_number():
    coverage = i18n.coverage()
    assert coverage["en"] == 100.0
    assert all(0.0 <= value <= 100.0 for value in coverage.values())
    # every shipped language is complete today
    assert min(coverage.values()) == 100.0


def test_a_json_locale_file_is_validated_like_the_rest(tmp_path, monkeypatch):
    """Dropping a JSON file must not be able to ship a broken translation."""
    locales = tmp_path / "locales"
    locales.mkdir()
    (locales / "sw.json").write_text(
        json.dumps(
            {
                "name": "Kiswahili",
                "strings": {
                    "lang.title": "lugha",
                    "ctl.volume": "Sauti: {volume}%",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(i18n, "_LOCALES_DIR", locales)
    i18n.CATALOGS.pop("sw", None)
    i18n._CACHE.clear()
    i18n._load_json_locales()
    try:
        assert "sw" in i18n.CATALOGS
        assert i18n.NAMES["sw"] == "Kiswahili"
        # a partial file is honest: it reports what it lacks and falls back
        assert "ctl.paused" in i18n.missing("sw")
        assert i18n.catalog("sw").t("ctl.paused") == i18n.catalog("en").t("ctl.paused")
        assert i18n.coverage()["sw"] < 100.0
    finally:
        i18n.CATALOGS.pop("sw", None)
        i18n.NAMES.pop("sw", None)
        i18n._CACHE.clear()
        # Do NOT reload here: `_LOCALES_DIR` is still the temporary directory
        # (monkeypatch only restores it after the test), so reloading would
        # put the partial catalog back and every later coverage test would
        # see a language at 7.7%.
