"""The card that exists for a second or two.

`/play` used to answer with two lines of orange text and an italic apology —
"⏱️ Searching YouTube…" over "✨ give it a moment — VYRON is on it" — the one
reply in the app that did not look like the app, and the one that named the
wrong engine. These tests keep it a card, keep it honest about what it is
doing, and keep its live updates from overwriting the answer.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from vyron.ui import cards, rich


def _plain(markup: str) -> str:
    return rich.to_html(markup)


def test_the_working_card_is_the_same_shape_as_every_other_card():
    from vyron.ui import rich

    markup = cards.working_card("searching", "", glyph="search", query="Kesariya", step="asking the catalogues")
    text = _plain(markup)

    # Rich lane: a real heading and a real divider, which is what makes the
    # card a rich message rather than bold text.
    rich.set_rich_enabled(True)
    try:
        rich_markup = cards.working_card("searching", "", glyph="search", query="Kesariya", step="x")
        assert rich_markup.startswith("<h2>"), "no rich masthead"
        assert "<hr/>" in rich_markup
        assert rich.has_rich_tags(rich_markup)
    finally:
        rich.set_rich_enabled(None)

    assert text, "the classic lane still renders"
    assert "ꜱᴇᴀʀᴄʜɪɴɢ" in text, "the banner is small-caps like the rest of the app"
    assert "<b>Kesariya</b>" in text
    assert "asking the catalogues" in text
    # The apology that used to sit under every /play.
    assert "give it a moment" not in text
    assert "<i>✨ VYRON" in text, "still carries the footer"


def test_the_working_card_says_what_it_is_looking_for():
    link = _plain(cards.working_card("reading the link", "", glyph="link", query="https://youtu.be/x", step="resolving", label="link"))
    playlist = _plain(cards.working_card("loading the playlist", "", glyph="queue", query="PL1", step="reading", label="playlist"))

    assert "ʟɪɴᴋ" in link and "https://youtu.be/x" in link
    assert "ᴘʟᴀʏʟɪꜱᴛ" in playlist and "PL1" in playlist
    assert "looking for" not in link


def test_the_old_call_shape_still_works():
    """Five other commands post this card with only a title and a sentence."""
    text = _plain(cards.working_card("doctor", "Running the checks — this takes a few seconds."))
    assert "ᴅᴏᴄᴛᴏʀ" in text
    assert "Running the checks" in text


def test_a_live_stage_update_never_overwrites_the_answer(monkeypatch):
    from vyron.modules import play

    sent: list[str] = []

    class FakeRich:
        async def send(self, client, chat_id, markup, **kwargs):
            sent.append(markup)
            return types.SimpleNamespace(id=99)

        async def edit(self, client, chat_id, message_id, markup, **kwargs):
            sent.append(markup)

    monkeypatch.setattr(play, "rich", FakeRich())

    class Message:
        id = 5
        chat = types.SimpleNamespace(id=1)
        from_user = types.SimpleNamespace(id=9, first_name="Asha")

    async def scenario():
        await play._thinking(
            None,
            Message(),
            "searching",
            glyph="search",
            query="Kesariya",
            step="asking the catalogues",
            stages=[(0.01, "matching the results")],
        )
        await asyncio.sleep(0.08)
        await play._edit(None, 1, 99, "the picker")
        await asyncio.sleep(0.08)
        assert play._TICKERS == {}, "the ticker outlived the answer"

    asyncio.run(scenario())

    assert "this card updates itself" in sent[0]
    assert "matching the results" in sent[1]
    assert sent[-1] == "the picker"
    # Nothing arrived after the answer was written.
    assert sent.index("the picker") == len(sent) - 1


def test_a_cancelled_ticker_is_forgotten():
    from vyron.modules import play

    async def scenario():
        play._TICKERS[123] = asyncio.create_task(asyncio.sleep(30))
        play._stop_ticker(123)
        assert 123 not in play._TICKERS
        await asyncio.sleep(0)          # let the cancellation land

    try:
        asyncio.run(scenario())
    finally:
        play._TICKERS.clear()


@pytest.mark.parametrize("title", ["searching", "reading the link", "loading the playlist"])
def test_no_working_card_mentions_a_single_engine(title):
    """The card used to promise YouTube; the catalogues answer first now."""
    text = _plain(cards.working_card(title, "", query="x", step="working")).lower()
    assert "youtube" not in text


# ── the download card is a live card ───────────────────────────────────────
def test_the_download_card_shows_where_the_bytes_are():
    """"preparing audio" used to sit at one italic sentence for a whole minute."""
    from vyron.core.queue import Track

    track = Track(id="abcdefghijk", title="Kesariya", duration=268, uploader="Arijit")
    idle = _plain(cards.download_card(track, "audio"))
    assert "fetching the best quality" in idle
    assert "%" not in idle

    live = _plain(cards.download_card(track, "audio", step="downloading · 2.1 MB / 7.4 MB", fraction=0.28))
    assert "downloading" in live and "2.1 MB" in live
    assert "28%" in live
    assert "▰" in live and "▱" in live


def test_the_download_card_survives_text_it_did_not_write():
    """Progress text comes from yt-dlp, aria2 and the mirror — never trust it."""
    from vyron.core.queue import Track

    track = Track(id="x", title="t")
    markup = cards.download_card(track, "audio", step="<script>alert(1)</script>", fraction=2.0)
    text = _plain(markup)
    assert "alert(1)" in text and "<script>" not in text
    # a fraction outside 0..1 must clamp rather than draw a negative bar
    assert "100%" in text and "▱" not in text


# ── the rich lane gets a second chance before it gives up ──────────────────
def test_a_refused_rich_card_is_retried_without_the_optional_tags():
    """One unsupported tag used to cost the whole rich card."""
    from vyron.ui import rich

    card = (
        "<h2>🎧 ᴘʟᴀʏᴇʀ</h2><hr/>"
        "<blockquote expandable><tg-thinking></tg-thinking> working</blockquote>"
        "<aside>note</aside><footer>v1.0</footer>"
    )
    safe = rich.safe_markup(card)
    assert "expandable" not in safe
    assert "<tg-thinking>" not in safe
    assert "<aside>" not in safe and "<blockquote>note</blockquote>" in safe
    assert "<footer>" not in safe and "<i>v1.0</i>" in safe
    assert "<h2>" in safe, "the part that makes it a rich card must survive"


def test_the_rich_lane_can_explain_itself():
    from vyron.ui import rich

    line = rich.status()
    assert isinstance(line, str) and line
    if not rich.RICH_AVAILABLE:
        assert "unavailable" in line
