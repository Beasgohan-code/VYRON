"""Inline mode: every button must actually do something."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from vyron.modules import inline


class Query:
    def __init__(self, text: str):
        self.query = text
        self.from_user = SimpleNamespace(id=7, first_name="Rin")
        self.answers: list[tuple[list, dict]] = []

    async def answer(self, results, **kwargs):
        self.answers.append((list(results), kwargs))


def _track(**over):
    base = dict(
        id="dQw4w9WgXcQ",
        title="Never Gonna Give You Up",
        duration=213,
        uploader="Rick Astley",
        url="https://youtu.be/dQw4w9WgXcQ",
        thumbnail="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        source="youtube",
        views=1_600_000_000,
        watch_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )
    base.update(over)
    return SimpleNamespace(**base)


# ── payload safety ──────────────────────────────────────────────────────────
def test_play_payload_prefers_the_link_and_fits_telegram():
    data = inline._play_data(_track())
    assert data is not None
    assert data.startswith("v:play:")
    assert len(data.encode()) <= inline.CALLBACK_LIMIT


def test_a_long_link_falls_back_to_a_text_query():
    long_url = "https://soundcloud.com/" + "x" * 120
    data = inline._play_data(_track(watch_url=long_url))
    assert data is not None
    assert long_url not in data
    assert len(data.encode()) <= inline.CALLBACK_LIMIT


def test_no_payload_when_nothing_fits():
    huge = _track(watch_url=None, title="x" * 80, uploader="y" * 40)
    assert inline._play_data(huge) is None
    rows = inline._keyboard(huge).inline_keyboard
    assert all(button.callback_data is None for row in rows for button in row)


# ── share message ───────────────────────────────────────────────────────────
def test_share_text_is_self_contained():
    text = inline._share_text(_track(title="Believer <live>"))
    assert "Believer &lt;live&gt;" in text
    assert "Rick Astley" in text
    assert "3:33" in text
    assert "shared from @" in text


def test_share_text_escapes_the_title():
    assert "<script>" not in inline._share_text(_track(title="<script>"))


# ── search wiring ───────────────────────────────────────────────────────────
def test_results_are_ranked_and_each_has_a_working_button():
    from vyron.runtime import runtime

    class YT:
        async def search(self, text, limit=8, requester=(0, "")):
            return [_track(), _track(id="abc12345678", title="Second", views=0)]

    old = runtime.youtube
    runtime.youtube = YT()
    try:
        query = Query("rick")
        asyncio.run(inline.answer_inline(query))
    finally:
        runtime.youtube = old

    results, _ = query.answers[-1]
    assert len(results) == 2
    assert "top match" in results[0].description
    assert "#2" in results[1].description
    rows = results[0].reply_markup.inline_keyboard
    assert rows[0][0].callback_data.startswith("v:play:")


def test_an_empty_query_shows_the_hint():
    from vyron.runtime import runtime

    old = runtime.youtube
    runtime.youtube = None
    try:
        query = Query("   ")
        asyncio.run(inline.answer_inline(query))
    finally:
        runtime.youtube = old

    results, kwargs = query.answers[-1]
    assert len(results) == 1
    assert "search music" in results[0].title
    assert kwargs["is_personal"] is True
