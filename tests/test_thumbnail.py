"""Artwork: the poster draws itself, and the helpers that read a photo.

There is no `/thumbnail` command any more — nobody chose a per-group backdrop,
and the now-playing poster is at its best when it is *this song's* cover. The
channel-side `/cthumbnail` still needs to read a photo message, so that half
stays, together with the poster's own naming and cover-quality rules.
"""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest

from vyron.core import chatcfg
from vyron.core.queue import ChatState, Track
from vyron.modules import thumbnail_cmd
from vyron.ui import nowplaying
from vyron.utils import thumbnails


# ── fixtures ────────────────────────────────────────────────────────────────
def _image(colour, size=(640, 480)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


class Bot:
    def __init__(self, blob: bytes | None = None):
        self.blob = blob
        self.downloads: list = []
        self.sent: list = []

    async def download_media(self, file_id, **kwargs):
        self.downloads.append(file_id)
        return io.BytesIO(self.blob or b"")

    async def send_photo(self, chat_id, photo, caption, **kwargs):
        self.sent.append(("photo", caption))
        return SimpleNamespace(id=11)

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(("text", text))
        return SimpleNamespace(id=12)


def _message(*, photo: str = "", reply_photo: str = ""):
    photo_obj = lambda fid: SimpleNamespace(file_id=fid, file_unique_id=fid)  # noqa: E731
    chat = SimpleNamespace(id=-100, type="supergroup", title="Room")
    return SimpleNamespace(
        id=5,
        chat=chat,
        from_user=SimpleNamespace(id=7, first_name="Rin"),
        command=["/cthumbnail"],
        text="/cthumbnail",
        photo=photo_obj(photo) if photo else None,
        document=None,
        reply_to_message=(
            SimpleNamespace(photo=photo_obj(reply_photo), document=None)
            if reply_photo
            else None
        ),
    )


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    store: dict = {}

    async def fake_get(chat_id, key, default=None):
        return store.get(
            (int(chat_id), key), default if default is not None else chatcfg.DEFAULTS.get(key)
        )

    async def fake_set(chat_id, key, value):
        store[(int(chat_id), key)] = value

    monkeypatch.setattr(chatcfg, "get", fake_get)
    monkeypatch.setattr(chatcfg, "set", fake_set)
    nowplaying._CACHE.clear()
    nowplaying._ART.clear()
    yield store


# ── reading a photo message (used by /cthumbnail) ──────────────────────────
def test_a_replied_photo_wins():
    assert thumbnail_cmd.photo_file_id(_message(reply_photo="reply-id")) == "reply-id"


def test_a_caption_photo_works_too():
    assert thumbnail_cmd.photo_file_id(_message(photo="own-id")) == "own-id"


def test_an_image_document_is_accepted():
    message = _message()
    message.reply_to_message = SimpleNamespace(
        photo=None, document=SimpleNamespace(file_id="doc-id", mime_type="image/png")
    )
    assert thumbnail_cmd.photo_file_id(message) == "doc-id"


def test_no_media_returns_nothing():
    assert thumbnail_cmd.photo_file_id(_message()) == ""


def test_an_oversized_image_file_is_flagged():
    message = _message()
    message.reply_to_message = SimpleNamespace(
        photo=None,
        document=SimpleNamespace(
            file_id="big", mime_type="image/png", file_size=thumbnail_cmd.MAX_ART_BYTES + 1
        ),
    )
    assert thumbnail_cmd.art_too_big(message) is True
    assert thumbnail_cmd.art_too_big(_message(reply_photo="small")) is False


# ── the poster itself ──────────────────────────────────────────────────────
def test_a_custom_backdrop_changes_the_render():
    state = ChatState(chat_id=-100)
    track = Track(id="t1", title="Believer", duration=200, uploader="Imagine Dragons")
    cover = _image((120, 40, 200), (480, 480))
    backdrop = _image((10, 200, 160), (800, 400))

    plain = thumbnails.render(state, track, cover)
    branded = thumbnails.render(state, track, cover, backdrop)

    assert plain and branded
    assert plain != branded
    from PIL import Image

    assert Image.open(io.BytesIO(branded)).size == (1280, 720)


def test_chat_art_is_cached_by_file_id(_isolated_state):
    bot = Bot(blob=_image((30, 30, 30), (300, 300)))
    _isolated_state[(-100, "thumbnail")] = "art-9"

    first = asyncio.run(nowplaying.chat_art(-100, bot))
    second = asyncio.run(nowplaying.chat_art(-100, bot))

    assert first and first == second
    assert bot.downloads == ["art-9"]


def test_no_artwork_means_no_download(_isolated_state):
    bot = Bot()
    assert asyncio.run(nowplaying.chat_art(-100, bot)) is None
    assert bot.downloads == []


def test_poster_uses_the_chat_artwork(_isolated_state, monkeypatch):
    _isolated_state[(-100, "thumbnail")] = "art-3"
    bot = Bot(blob=_image((200, 100, 0), (600, 300)))
    monkeypatch.setattr(nowplaying, "enabled", lambda: True)

    seen = {}

    async def fake_render(state, track, backdrop=None):
        seen["backdrop"] = backdrop
        return b"\xff\xd8poster"

    monkeypatch.setattr(thumbnails, "now_playing", fake_render)
    state = ChatState(chat_id=-100)
    state.current = Track(id="t2", title="Song", duration=100)

    image = asyncio.run(nowplaying.poster(state, state.current, bot=bot, chat_id=-100))

    assert image == b"\xff\xd8poster"
    assert seen["backdrop"] is not None


def test_a_failed_download_never_breaks_the_poster(_isolated_state, monkeypatch):
    """An expired file id must degrade to the normal cover, not raise."""
    bot = Bot()
    _isolated_state[(-100, "thumbnail")] = "stale"

    async def explode(*_args, **_kwargs):
        raise RuntimeError("FILE_REFERENCE_EXPIRED")

    monkeypatch.setattr(bot, "download_media", explode)
    monkeypatch.setattr(nowplaying, "enabled", lambda: True)
    monkeypatch.setattr(
        thumbnails, "now_playing", lambda state, track, backdrop=None: _ok(b"art")
    )

    assert asyncio.run(nowplaying.chat_art(-100, bot)) is None

    state = ChatState(chat_id=-100)
    state.current = Track(id="t3", title="Song", duration=100)
    assert (
        asyncio.run(nowplaying.poster(state, state.current, bot=bot, chat_id=-100)) == b"art"
    )


async def _ok(value):
    return value


# ── automatic artwork: the biggest cover, the real name ────────────────────
def test_the_biggest_cover_is_requested():
    assert (
        thumbnails.best_cover_url("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
        == "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
    )
    assert (
        thumbnails.best_cover_url("https://creatornode2.audius.co/content/480x480/a.jpg")
        == "https://creatornode2.audius.co/content/1000x1000/a.jpg"
    )
    # a stream URL is not a cover, and nothing should be invented for it
    stream = "https://api.audius.co/v1/tracks/1dP3kyX/stream"
    assert thumbnails.best_cover_url(stream) == stream


def test_the_poster_names_the_song_not_the_repost_account():
    """The largest type on the poster is the song, credited to the artist."""
    from vyron.utils.naming import display_parts

    assert display_parts("Chris Grey – LET THE WORLD BURN", "Alone_BoYtm") == (
        "Chris Grey",
        "LET THE WORLD BURN",
    )
    assert display_parts("Believer", "Imagine Dragons - Topic") == (
        "Imagine Dragons",
        "Believer",
    )


def test_the_thumbnail_command_is_gone():
    """"For what?" — the poster art is automatic now."""
    from vyron.__main__ import COMMANDS

    assert "thumbnail" not in {name for name, _description in COMMANDS}
