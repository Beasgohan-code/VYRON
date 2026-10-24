"""UI-layer tests: rich ↔ HTML conversion, emoji fallbacks, card rendering."""
from __future__ import annotations

import pytest

pytest.importorskip("pyrogram")

from vyron.core.queue import ChatState, Track
from vyron.ui import cards, rich
from vyron.ui.theme import E, GLYPHS, emoji_enabled, raw_glyph


def test_rich_tag_detection():
    assert rich.has_rich_tags("<h2>title</h2>")
    assert rich.has_rich_tags("<table><tr><td>a</td></tr></table>")
    assert rich.has_rich_tags('<tg-button url="https://x.dev">go</tg-button>')
    assert not rich.has_rich_tags("<b>plain</b> <code>x</code>")


def test_normalize_newlines_and_hrefs():
    out = rich.normalize("line one\nline two")
    assert "<br/>" in out
    quoted = rich.normalize('<a href=tg://user?id=1>me</a>')
    assert 'href="tg://user?id=1"' in quoted


def test_to_html_strips_rich_only_tags():
    markup = (
        "<h2>Title</h2><p>Body</p>"
        "<table><tr><td>a</td><td>b</td></tr></table>"
        '<tg-button url="https://example.com">Open</tg-button>'
        "<footer>foot</footer>"
    )
    html = rich.to_html(markup)
    for forbidden in ("<h2", "<table", "<tr", "<td", "<tg-button", "<footer", "<p>"):
        assert forbidden not in html
    assert "<b>Title</b>" in html
    assert 'href="https://example.com"' in html


def test_to_plain_text_is_tag_free():
    text = rich.to_plain_text("<h2>Hi</h2><p>there <b>you</b></p>")
    assert "<" not in text and ">" not in text
    assert "Hi" in text and "you" in text


def test_esc():
    assert rich.esc("<b>&") == "&lt;b&gt;&amp;"
    assert rich.esc(None) == ""


def test_emoji_fallbacks_without_pack():
    # conftest disables the premium pack
    assert emoji_enabled() is False
    assert E("play") == GLYPHS["play"]
    assert raw_glyph("unknown-name").strip() != ""


def test_now_playing_card_is_editable_html():
    state = ChatState(
        chat_id=1,
        current=Track(id="abc", title="Title <b>", duration=200, uploader="Artist"),
        playing=True,
        offset=50,
    )
    markup = cards.now_playing_card(state)
    assert not rich.has_rich_tags(markup)   # editable lane
    assert "50" in markup or "0:50" in markup
    assert "&lt;b&gt;" in markup            # untrusted text escaped


def test_queue_card_pages():
    state = ChatState(chat_id=1)
    state.queue = [Track(id=str(i), title=f"T{i}", duration=60) for i in range(20)]
    markup, pages = cards.queue_card(state, page=0, per_page=8)
    assert pages == 3
    assert rich.has_rich_tags(markup)
    markup2, pages2 = cards.queue_card(state, page=2, per_page=8)
    assert pages2 == 3 and markup2 != markup


def test_empty_queue_card():
    markup, pages = cards.queue_card(ChatState(chat_id=1))
    assert pages == 1 and "empty" in markup.lower()


def test_stats_and_settings_cards():
    stats = cards.stats_card(
        uptime=3661, chats=3, active=1, tracks=42, downloads=7,
        cache_bytes=5 * 1024 * 1024, backend="mongo", version="1.0.0",
    )
    assert "42" in stats and "mongo" in stats
    settings_markup = cards.settings_card({"volume": 60, "loop": "all", "autoplay": False}, "Chat")
    assert "60%" in settings_markup and "All" in settings_markup


# ── /start picture + credential cards ──────────────────────────────────────
class _PhotoBot:
    """Minimal client that records photo sends and can be told to fail."""

    def __init__(self, fail: bool = False):
        self.calls: list[dict] = []
        self.fail = fail

    async def send_photo(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("upload failed")

        class _Sent:
            id = 1

            class photo:  # noqa: N801 - mimics pyrogram's attribute
                file_id = "AgAC-start"

        return _Sent()

    async def send_message(self, **kwargs):
        self.calls.append({"text": kwargs.get("text")})
        return None


def test_send_photo_flattens_the_caption_and_keeps_the_keyboard():
    import asyncio

    bot = _PhotoBot()
    markup = "<h2>Title</h2><p>Body</p>"
    sent = asyncio.run(
        rich.send_photo(bot, 1, "assets/start.jpg", markup, reply_markup="KB")
    )
    assert sent is not None
    call = bot.calls[0]
    assert call["photo"] == "assets/start.jpg"
    assert "<h2" not in call["caption"] and "Title" in call["caption"]
    assert call["reply_markup"] == "KB"


def test_send_photo_falls_back_to_a_text_card():
    import asyncio

    bot = _PhotoBot(fail=True)
    asyncio.run(rich.send_photo(bot, 1, "missing.jpg", "<b>hi</b>"))
    assert bot.calls[-1]["text"] == "<b>hi</b>"


def test_start_card_carries_the_display_name():
    from vyron.ui.theme import BRAND_DISPLAY

    text = rich.to_plain_text(cards.start_card("Rahul", {"chats": 1, "tracks": 2}))
    assert BRAND_DISPLAY in text


def test_token_card_explains_revocation():
    text = rich.to_plain_text(
        cards.token_card("vown_abc.sig", base="https://v.test", owner_id=7, epoch=1)
    )
    assert "vown_abc.sig" in text
    assert "revoke all" in text.lower() and "generation" in text.lower()
    markup = cards.token_card("vown_abc.sig", base="https://v.test", owner_id=7)
    assert 'data="v:token:revoke"' in markup
    assert 'data="v:token:rotate"' in markup


def test_api_keys_card_offers_a_revoke_button_per_key():
    keys = [
        {"id": "k1", "label": "phone", "masked": "vyrn_aa…", "active": True, "uses": 3},
        {"id": "k2", "label": "old", "masked": "vyrn_bb…", "active": False, "uses": 1},
    ]
    markup = cards.api_keys_card(keys, base="https://v.test")
    assert 'data="v:key:revoke:k1"' in markup
    assert 'data="v:key:revoke:k2"' not in markup  # already dead


def test_confirm_card_is_a_two_step_action():
    markup = cards.confirm_card("Really?", "detail", confirm="v:x:yes", danger=True)
    assert 'data="v:x:yes"' in markup
    assert "Cancel" in rich.to_plain_text(markup)


def test_start_card_swaps_the_manual_for_the_track():
    live = {"title": "Believer", "artist": "Imagine Dragons", "duration": 204, "queue": 3}
    text = rich.to_plain_text(cards.start_card("Rahul", {}, live=live))
    assert "Believer" in text and "3" in text
    assert "Set it up in three steps" not in text  # no manual for a live chat
    assert "Set it up in three steps" in rich.to_plain_text(cards.start_card("Rahul", {}))


def test_to_caption_drops_button_rows():
    markup = (
        '<h2>Title</h2><tg-button-row><tg-button data="v:app">Player</tg-button>'
        "</tg-button-row><p>Body</p>"
    )
    caption = rich.to_caption(markup)
    assert "Player" not in caption and "Body" in caption
