"""`/thumbnail` — a chat's own artwork behind the now-playing poster."""
from __future__ import annotations

import asyncio
import io
from types import SimpleNamespace

import pytest

pytest.importorskip("pyrogram")

from vyron.core import chatcfg
from vyron.core.queue import ChatState, Track
from vyron.modules import thumbnail_cmd
from vyron.ui import cards
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


def _message(*, photo: str = "", reply_photo: str = "", group: bool = True, command=("/thumbnail",)):
    photo_obj = lambda fid: SimpleNamespace(file_id=fid, file_unique_id=fid)  # noqa: E731
    chat = SimpleNamespace(id=-100, type="supergroup" if group else "private", title="Room")
    return SimpleNamespace(
        id=5,
        chat=chat,
        from_user=SimpleNamespace(id=7, first_name="Rin"),
        command=list(command),
        text="/thumbnail",
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
        return store.get((int(chat_id), key), default if default is not None else chatcfg.DEFAULTS.get(key))

    async def fake_set(chat_id, key, value):
        store[(int(chat_id), key)] = value

    monkeypatch.setattr(chatcfg, "get", fake_get)
    monkeypatch.setattr(chatcfg, "set", fake_set)
    nowplaying._CACHE.clear()
    nowplaying._ART.clear()
    monkeypatch.setattr(thumbnail_cmd, "is_owner", lambda user_id: False)
    monkeypatch.setattr(thumbnail_cmd, "is_chat_admin", _always_admin)
    yield store


async def _always_admin(client, chat_id, user_id):
    return True


# ── file ids ────────────────────────────────────────────────────────────────
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


# ── saving / clearing ───────────────────────────────────────────────────────
def test_reply_to_photo_saves_the_artwork(_isolated_state):
    bot = Bot()
    asyncio.run(_run_command(bot, _message(reply_photo="art-1")))
    assert _isolated_state[(-100, "thumbnail")] == "art-1"


def test_thumbnail_off_clears_it(_isolated_state):
    _isolated_state[(-100, "thumbnail")] = "art-1"
    bot = Bot()
    asyncio.run(_run_command(bot, _message(command=("/thumbnail", "off"))))
    assert _isolated_state[(-100, "thumbnail")] == ""


async def _run_command(bot, message):
    """`register()` only wires decorators — drive the handlers directly."""
    handlers = {}
    client = SimpleNamespace(
        on_message=lambda flt: (lambda fn: handlers.setdefault("thumbnail", fn)),
    )
    thumbnail_cmd.register(client)
    await handlers["thumbnail"](bot, message)
    return handlers


def test_non_admin_cannot_replace_a_groups_artwork(_isolated_state, monkeypatch):
    monkeypatch.setattr(thumbnail_cmd, "is_chat_admin", _nobody_admin)
    bot = Bot()
    asyncio.run(_run_command(bot, _message(reply_photo="art-2")))
    assert (-100, "thumbnail") not in _isolated_state
    assert bot.sent and "Admins only" in bot.sent[-1][1]


async def _nobody_admin(client, chat_id, user_id):
    return False


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


def test_chat_art_is_cached_by_file_id(_isolated_state, monkeypatch):
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


# ── the card ───────────────────────────────────────────────────────────────
def test_the_status_card_explains_the_feature():
    text = cards.thumbnail_card(False, can_edit=True)
    assert "/thumbnail" in text
    assert "song cover" in text


def test_the_card_hides_the_remove_button_when_there_is_nothing_to_remove():
    assert "Remove artwork" not in cards.thumbnail_card(False, can_edit=True)
    assert "Remove artwork" in cards.thumbnail_card(True, can_edit=True)


def test_the_card_is_read_only_for_members():
    text = cards.thumbnail_card(True, can_edit=False)
    assert "Remove artwork" not in text
    assert "admin" in text.lower()
