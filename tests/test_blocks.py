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
    # Block-level pieces end with a newline so cards can be concatenated
    # without two lines welding together in the plain-text fallback.
    assert B.divider() == "<hr/>\n"
    assert B.bullets(["a"]).endswith("</ul>\n")
    assert B.note("x").endswith("</blockquote>\n")
    assert B.details("s", "b").endswith("</details>\n")
    assert B.table(None, [("a",)]).endswith("</table>\n")


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
    assert "Add to a group" in start

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

    # Results read like results: the best match is marked, not tabulated.
    assert "<mark>" in play_card and "Result 0" in play_card
    assert "<table" not in play_card

    # The player card never prints the web app URL: the keyboard carries the
    # Mini App button, and a URL in text would open Chrome instead.
    webapp = cards.webapp_card("https://example.com/app/?t=abc")
    assert "example.com" not in webapp and "http" not in webapp
    assert "inside Telegram" in webapp


def test_webapp_and_start_cards_document_the_player():
    web = cards.webapp_card("https://example.com/app/?t=abc", "Chill Squad")
    assert "voice chat" in web.lower()
    assert "play here" in web.lower()
    assert "browser tab" in web.lower()

    group = cards.webapp_group_card("VyronMusicBot")
    assert "private chat" in group.lower()
    assert "https://t.me/VyronMusicBot" in group

    # the start card advertises the player through a callback button only
    start = cards.start_card("Bob", {"chats": 1, "tracks": 2})
    assert 'data="v:app"' in start
    assert "/app" not in start


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


def test_owner_access_is_surfaced_without_leaking_it_into_the_ui():
    token_card = cards.token_card("vown_abc.def", base="https://vyron.example", owner_id=424242)

    # the credential is the point of *this* card — and it stays in the DM
    assert "X-Owner-Token: vown_abc.def" in token_card
    assert "424242" in token_card
    # but no browser link: the Mini App is reached with the keyboard button
    assert "/app" not in token_card and "ot=" not in token_card
    assert 'data="v:app"' in token_card

    # /start is public: no token, no URL, ever
    start = cards.start_card("A", {})
    assert "vown_" not in start
    assert "/app" not in start


# ── the shared card language ────────────────────────────────────────────────
def test_a_card_is_a_masthead_fields_and_sections():
    """Every screen in the bot is these four primitives in this order."""
    from vyron.ui import rich

    rich.set_rich_enabled(False)
    try:
        top = B.banner("vyron · player")
        assert top.startswith("<blockquote>") and top.endswith("</blockquote>\n")
        assert "ᴘʟᴀʏᴇʀ" in top and top.count("<b>") == 1
        assert B.rule() not in top, "a wall of ━ is not a header"
        assert B.actions(B.row(B.btn("x", data="v:np"))) .startswith("<tg-button-row")
    finally:
        rich.set_rich_enabled(None)

    fields = B.fields([("check", "status", "Online"), ("clock", "uptime", "3d 8h")])
    assert fields.splitlines()[0] == "◈ ✅ <b>ꜱᴛᴀᴛᴜꜱ</b>: Online"
    assert "<b>ᴜᴘᴛɪᴍᴇ</b>: 3d 8h" in fields

    rich.set_rich_enabled(False)
    try:
        section = B.section_title("what i can do")
        assert section.strip() == "✦ <b>ᴡʜᴀᴛ ɪ ᴄᴀɴ ᴅᴏ</b>"
    finally:
        rich.set_rich_enabled(None)
    rich.set_rich_enabled(False)
    try:
        line_items = B.items([("download", "save", "MP3 320")]).strip()
        assert line_items.startswith("◈ ") and line_items.endswith("MP3 320")
    finally:
        rich.set_rich_enabled(None)


def test_the_rich_lane_makes_the_masthead_a_real_heading():
    """The whole point of the rich lane: structure, not bold text."""
    from vyron.ui import rich

    rich.set_rich_enabled(True)
    try:
        top = B.banner("vyron · player")
        assert top.startswith("<h2>") and "<hr/>" in top
        assert "<b>" not in top.splitlines()[0], "a heading is already bold"
        assert rich.has_rich_tags(top)
        section = B.section_title("what i can do")
        assert "<h3>" in section
        # lists become lists, and a labelled block becomes a real heading
        listed = B.items([("download", "save", "MP3 320"), ("search", "find", "")])
        assert listed.startswith("<ul><li>") and listed.count("<li>") == 2
        assert "<b>ꜱᴀᴠᴇ</b> — MP3 320" in listed
        block = B.section("levels", "body text", glyph="bolt")
        assert "<h4>" in block and "<b>ʟᴇᴠᴇʟꜱ</b>" not in block
        assert B.empty_state("moon", "nothing queued", "add a song").startswith("<h3>")
        # and the classic lane still gets readable text out of it
        plain = rich.to_html(B.banner("vyron · player") + B.context("hi"))
        assert "ᴘʟᴀʏᴇʀ" in plain and "──────────" in plain
    finally:
        rich.set_rich_enabled(None)


def test_fields_skip_the_glyph_cleanly():
    assert B.fields([("", "mode", "auto")]).strip() == "◈ <b>ᴍᴏᴅᴇ</b>: auto"


def test_stat_pairs_is_the_field_block_not_a_table():
    pairs = B.stat_pairs([("clock", "Uptime", "3d")])
    assert "<table" not in pairs and pairs.startswith("◈")


def test_no_card_ever_ends_without_an_action():
    """A card with nothing to tap is a dead end on a phone."""
    from vyron.ui import cards

    for markup in (
        cards.start_card("Bob", {"chats": 1}),
        cards.help_card("main"),
        cards.settings_card({"volume": 40}),
        cards.about_card(),
        cards.ping_card(90.0, 60.0),
    ):
        assert "<tg-button" in markup


def test_every_rich_helper_the_code_calls_actually_exists():
    """`rich.blockquote` was called by /logs and never defined.

    Nothing imported it, nothing type-checked it, and the failure only appeared
    when somebody ran the command in a group. This walks the real call sites.
    """
    import ast
    from pathlib import Path

    from vyron.ui import blocks, cards, keyboards, rich, theme

    modules = {"rich": rich, "blocks": blocks, "cards": cards, "keyboards": keyboards, "theme": theme}
    root = Path(__file__).resolve().parents[1] / "vyron"
    missing: list[str] = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in modules
                and not hasattr(modules[node.value.id], node.attr)
            ):
                missing.append(f"{path.relative_to(root)}: {node.value.id}.{node.attr}")

    assert missing == []
