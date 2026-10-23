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
    # Callback buttons are rendered by the real reply_markup keyboard in the
    # classic lane, so they must not be duplicated as bold text.
    assert "Pause" not in html
    assert 'href="https://x.dev"' in html
    assert "Docs" in html


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


def test_webapp_and_start_cards_document_the_player(monkeypatch):
    import dataclasses

    from vyron.config import settings as real_settings

    web = cards.webapp_card("https://example.com/app/?t=abc", "Chill Squad")
    assert "<details>" in web and "device" in web.lower()
    assert "voice chat" in web.lower() and "lyrics" in web.lower()
    assert 'url="https://example.com/app/?t=abc"' in web

    # the start card only advertises the player when the deployment has one
    plain = cards.start_card("Bob", {"chats": 1, "tracks": 2})
    assert "open the player" not in plain.lower()
    monkeypatch.setattr(
        cards,
        "settings",
        dataclasses.replace(real_settings, webapp=True, webapp_url="https://vyron.example"),
    )
    with_app = cards.start_card("Bob", {"chats": 1, "tracks": 2})
    assert 'url="https://vyron.example/app/"' in with_app
    assert "web player" in with_app.lower()


def test_lyrics_card_previews_synced_lines():
    from vyron.core.lyrics import LyricsResult
    from vyron.core.queue import Track

    result = LyricsResult(
        title="Song",
        artist="Artist",
        plain="line one\nline two",
        synced="[00:10.00] line one\n[00:22.50] line two",
    )
    markup = cards.lyrics_card(Track(id="x", title="Song", duration=180), result)
    assert "<table" in markup and "0:10" in markup and "0:22" in markup
    assert "Full lyrics" in markup and "synced" in markup


def test_music_api_cards():
    stats = {
        "enabled": True,
        "open": False,
        "keys": 2,
        "keys_total": 3,
        "requests": 41,
        "bytes": 5 * 1024 * 1024,
        "rate_limit": 30,
        "storage": "mongo",
    }
    markup = cards.music_api_card("https://vyron.example", stats)
    assert "/v1/track/by-video-id" in markup and "/v1/search" in markup
    assert 'url="https://vyron.example/v1/docs"' in markup
    assert "41" in markup and "30" in markup

    compact = cards.music_api_card("https://vyron.example", stats, compact=True)
    assert "<details open>" not in compact and len(compact) < len(markup)

    key_card = cards.api_key_card("vyrn_abcdefghijkl", "my-bot", "https://vyron.example", 30)
    assert "Copy it now" in key_card and "vyrn_abcdefghijkl" in key_card

    listing = cards.api_keys_card(
        [
            {
                "key": "vyrn_abcdefghijklmnop",
                "label": "my-bot",
                "active": True,
                "uses": 7,
                "bytes": 1024,
                "last_used_at": None,
            }
        ],
        "https://vyron.example",
    )
    assert "<table" in listing and "…" in listing and "never" in listing

    usage = cards.api_usage_card(
        stats,
        [{"label": "my-bot", "uses": 7, "bytes": 5 * 1024 * 1024, "last_used_at": None}],
        "https://vyron.example",
        sudo=True,
    )
    assert "5.0 MB" in usage and "41" in usage


def test_owner_access_is_surfaced_in_the_ui(monkeypatch):
    import dataclasses

    from vyron.config import settings as real_settings

    live = dataclasses.replace(real_settings, webapp_url="https://vyron.example", webapp=True)
    monkeypatch.setattr(cards, "settings", live)

    start = cards.start_card("A", {}, owner_token="vown_tok")
    assert "Owner console" in start and "ot=vown_tok" in start
    assert "Owner console" not in cards.start_card("A", {})

    token_card = cards.owner_access_card(
        "vown_abc.def", "https://vyron.example", "https://vyron.example", owner_id=424242
    )
    assert "X-Owner-Token: vown_abc.def" in token_card
    assert "https://vyron.example/app/?ot=vown_abc.def" in token_card
    assert "424242" in token_card and "hashed at rest" not in token_card

    web = cards.webapp_card("https://vyron.example", "chat", owner_token="vown_tok")
    assert 'url="https://vyron.example/app/"' in web
    assert "ot=vown_tok" in web
    assert "owner tools unlocked" in web
