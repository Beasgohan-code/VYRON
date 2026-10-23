"""The generated now-playing poster, and everything that hangs off it."""
from __future__ import annotations

import asyncio
import io
import time

import pytest

pytest.importorskip("pyrogram")

from vyron.core.queue import ChatState, Track
from vyron.ui import cards, rich
from vyron.utils import thumbnails


def _cover_bytes() -> bytes:
    """A colourful square, so the accent picker has something to chew on."""
    from PIL import Image

    image = Image.new("RGB", (480, 480), (24, 26, 40))
    for x in range(480):
        for y in range(0, 480, 4):
            image.putpixel((x, y), ((x * 3) % 255, (y * 2) % 255, 120))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _state(title="Believer", **kwargs) -> ChatState:
    state = ChatState(chat_id=1)
    state.current = Track(
        id="track-1",
        title=title,
        duration=kwargs.pop("duration", 204),
        uploader=kwargs.pop("uploader", "Imagine Dragons"),
        **kwargs,
    )
    state.playing = True
    return state


@pytest.mark.skipif(not thumbnails.PIL_AVAILABLE, reason="Pillow is not installed")
def test_render_produces_a_jpeg_with_brand_fonts():
    state = _state()
    raw = thumbnails.render(state, state.current, _cover_bytes())
    assert raw and raw[:2] == b"\xff\xd8"
    assert len(raw) > 20_000


@pytest.mark.skipif(not thumbnails.PIL_AVAILABLE, reason="Pillow is not installed")
def test_long_titles_do_not_blow_up_the_layout():
    state = _state(title="Chris Grey - LET THE WORLD BURN (Official Lyric Video) [4K]")
    raw = thumbnails.render(state, state.current, _cover_bytes())
    assert raw and len(raw) > 10_000


@pytest.mark.skipif(not thumbnails.PIL_AVAILABLE, reason="Pillow is not installed")
def test_render_needs_a_track():
    assert thumbnails.render(_state(), None) is None


@pytest.mark.skipif(not thumbnails.PIL_AVAILABLE, reason="Pillow is not installed")
def test_devanagari_titles_pick_a_font_that_can_draw_them():
    state = _state(title="तुम ही हो", uploader="Arijit Singh")
    face = thumbnails.font(40, 700, "तुम ही हो")
    assert face is not None
    assert thumbnails.render(state, state.current) is not None


def test_caption_is_short_and_live():
    state = _state()
    state.queue = [Track(id="n", title="Next one", duration=180)]
    caption = rich.to_caption(cards.now_playing_caption(state))
    assert "streaming" in caption.lower()
    assert "3:24" in caption  # duration
    assert "Believer" not in caption  # the poster already says it
    assert len(caption) <= 1024


class _EditBot:
    def __init__(self) -> None:
        self.captions: list[dict] = []

    async def edit_message_caption(self, **kwargs):
        self.captions.append(kwargs)
        return object()

    async def edit_message_text(self, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("a photo cannot be edited as text")


def test_photo_messages_are_edited_as_captions():
    # pretend send_photo delivered message 77 in chat 1
    rich._remember_photo(1, 77)
    bot = _EditBot()
    asyncio.run(rich.edit(bot, 1, 77, "<b>hi</b>", markup_keyboard="KB"))
    assert bot.captions and bot.captions[0]["caption"] == "<b>hi</b>"
    assert bot.captions[0]["reply_markup"] == "KB"


class _PhotoBot:
    def __init__(self) -> None:
        self.photos: list[dict] = []
        self.texts: list[dict] = []

    async def send_photo(self, **kwargs):
        self.photos.append(kwargs)
        return type("M", (), {"id": 501, "photo": None})()

    async def send_message(self, **kwargs):
        self.texts.append(kwargs)
        return type("M", (), {"id": 502})()


def test_announce_posts_the_poster_and_remembers_the_message(monkeypatch):
    from vyron.ui import nowplaying

    if not thumbnails.PIL_AVAILABLE:
        pytest.skip("Pillow is not installed")

    async def fake_poster(state, track, **_):
        return b"\xff\xd8fake"

    monkeypatch.setattr(nowplaying, "poster", fake_poster)
    bot = _PhotoBot()
    state = _state()
    asyncio.run(nowplaying.announce(bot, 1, state))
    assert bot.photos, "the poster should be sent as a photo"
    assert bot.photos[0]["caption"]
    assert state.np_message_id == 501
    assert rich.is_photo(1, 501)


def test_announce_falls_back_to_the_text_card(monkeypatch):
    from vyron.ui import nowplaying

    async def no_poster(state, track, **_):
        return None

    monkeypatch.setattr(nowplaying, "poster", no_poster)
    bot = _PhotoBot()
    state = _state()
    asyncio.run(nowplaying.announce(bot, 1, state))
    assert bot.texts and "NOW PLAYING" in bot.texts[0]["text"]
    assert state.np_message_id == 502


def test_poster_is_cached_per_track(monkeypatch):
    from vyron.ui import nowplaying

    calls = {"n": 0}

    async def counting(state, track, **_):
        calls["n"] += 1
        return b"\xff\xd8cached"

    monkeypatch.setattr(thumbnails, "now_playing", counting)
    nowplaying._CACHE.clear()
    state = _state()
    started = time.time()
    first = asyncio.run(nowplaying.poster(state, state.current))
    second = asyncio.run(nowplaying.poster(state, state.current))
    assert first == second == b"\xff\xd8cached"
    assert calls["n"] == 1
    assert time.time() - started < 5


def test_a_chat_can_turn_the_poster_off(monkeypatch):
    from vyron.core import chatcfg
    from vyron.ui import nowplaying

    async def off(chat_id, key, default=None):
        return False if key == "poster" else default

    monkeypatch.setattr(chatcfg, "get", off)
    assert asyncio.run(nowplaying.allowed(1)) is False

    async def on(chat_id, key, default=None):
        return True

    monkeypatch.setattr(chatcfg, "get", on)
    assert asyncio.run(nowplaying.allowed(1)) is True


def test_settings_surface_the_poster_switch():
    markup = cards.settings_card({"volume": 70, "poster": False})
    assert 'data="v:set:poster"' in markup
    assert "off" in rich.to_plain_text(markup).lower()


def test_bytes_are_wrapped_before_they_reach_pyrogram():
    """Pyrogram rejects raw bytes — the poster must be sent as a file object."""
    from vyron.ui import rich

    class Bot:
        def __init__(self):
            self.photos = []

        async def send_photo(self, **kwargs):
            self.photos.append(kwargs)
            return type("M", (), {"id": 3})()

    bot = Bot()
    asyncio.run(rich.send_photo(bot, 1, b"\xff\xd8poster", "<b>hi</b>"))
    sent = bot.photos[0]["photo"]
    assert isinstance(sent, io.IOBase)
    assert sent.read() == b"\xff\xd8poster"


def test_a_poster_refresh_edits_the_caption_in_place(monkeypatch):
    from vyron.ui import nowplaying

    async def fake_poster(state, track, **_):
        return b"\xff\xd8fake"

    monkeypatch.setattr(nowplaying, "poster", fake_poster)

    class Bot:
        def __init__(self):
            self.captions: list[dict] = []
            self.texts: list[dict] = []

        async def send_photo(self, **kwargs):
            return type("M", (), {"id": 61})()

        async def edit_message_caption(self, **kwargs):
            self.captions.append(kwargs)
            return object()

        async def edit_message_text(self, **kwargs):  # pragma: no cover
            self.texts.append(kwargs)
            return object()

    bot = Bot()
    state = _state()
    asyncio.run(nowplaying.announce(bot, 1, state))
    assert state.np_message_id == 61
    rich._remember_photo(1, 61)
    asyncio.run(nowplaying.announce(bot, 1, state, edit=True))
    assert bot.captions, "the live clock must be a caption edit"
    assert not bot.texts
