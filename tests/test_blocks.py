"""Rich block + button tests (richgram-backed UI layer)."""
from __future__ import annotations

import pytest

pytest.importorskip("pyrogram")

from vyron.ui import blocks as B
from vyron.ui import cards, rich


def test_buttons_and_styles():
    primary = B.btn("Play", data="v:pause", style="primary")
    assert primary.startswith('<tg-button type="callback_data" style="primary"')
    assert 'data="v:pause"' in primary
    for style in ("success", "danger"):
        assert f'style="{style}"' in B.btn("X", data="v:np", style=style)
    # unknown style is dropped rather than rejected by Telegram
    assert "style=" not in B.btn("X", data="v:np", style="neon")
    link = B.btn("Site", url="https://example.com", style="link")
    assert 'type="url"' in link and 'url="https://example.com"' in link


def test_rows_and_grid():
    row = B.row(B.btn("A", data="v:a"), B.btn("B", data="v:b"), align="center")
    assert row.startswith('<tg-button-row align="center">')
    assert row.count("<tg-button ") == 2  # the wrapper tag is <tg-button-row>
    grid = B.grid([B.btn(str(i), data=f"v:{i}") for i in range(5)], columns=2)
    assert grid.count("<tg-button-row>") == 3


def test_tables_details_lists():
    table = B.table(["#", "Title"], [("<b>1</b>", "Song")])
    assert table.startswith('<table border="1"><tr><th>#</th><th>Title</th></tr>')
    assert B.kv([("Vol", "<b>100%</b>")]).count("<td>") == 2
    assert B.details("More", "body", open=True).startswith("<details open>")
    assert B.bullets(["a", "b"]).count("<li>") == 2
    assert B.divider() == "<hr/>"


def test_fallback_conversion_of_buttons():
    markup = (
        B.row(B.btn("Pause", data="v:pause", style="danger")) 
        + B.row(B.btn("Docs", url="https://x.dev"))
    )
    html = rich.to_html(markup)
    assert "<tg-button" not in html
    assert "<b>Pause</b>" in html
    assert 'href="https://x.dev"' in html


def test_rich_detection_and_escaping():
    assert rich.has_rich_tags(B.btn("X", data="v:x"))
    assert rich.has_rich_tags(B.hr() if hasattr(B, "hr") else B.divider())
    assert B.esc('<img src=x onerror="1">') .startswith("&lt;img")


def test_static_cards_carry_rich_buttons():
    start = cards.start_card("Bob", {"chats": 1, "tracks": 2})
    assert "<tg-button" in start
    assert "Add to group" in start

    about = cards.about_card()
    assert "<tg-button" in about

    settings_markup = cards.settings_card({"volume": 55, "loop": "all"})
    assert "<tg-button" in settings_markup and "55%" in settings_markup

    help_markup = cards.help_card("queue")
    assert "<tg-button" in help_markup and "v:help:main" in help_markup


def test_search_and_webapp_cards():
    from vyron.core.queue import Track

    tracks = [Track(id=str(i), title=f"Result {i}", duration=100 + i) for i in range(3)]
    play_card = cards.search_card("query", tracks, mode="play")
    assert "v:pick:0" in play_card and "v:pick:2" in play_card
    download_card = cards.search_card("query", tracks, mode="download")
    assert "v:dl:0" in download_card

    webapp = cards.webapp_card("https://example.com/app/?t=abc")
    assert "https://example.com/app/?t=abc" in webapp and "<tg-button" in webapp
