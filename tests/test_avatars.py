"""Profile pictures for the Mini App: what counts as one, and what is cached."""
from __future__ import annotations

import asyncio
import io

from vyron.web import auth, avatars

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 400
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 400


def setup_function():
    avatars.forget()


# ── what is a picture ───────────────────────────────────────────────────────
def test_a_jpeg_is_recognised_by_its_bytes():
    picture = avatars._build(JPEG)
    assert picture is not None
    assert picture.content_type == "image/jpeg"
    assert picture.etag.startswith('"')


def test_a_png_and_a_webp_are_recognised_too():
    assert avatars.sniff(PNG) == "image/png"
    assert avatars.sniff(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


def test_junk_and_oversized_bodies_are_not_pictures():
    assert avatars.sniff(b"<html>nope</html>") == ""
    assert avatars._build(b"<html>nope</html>") is None
    assert avatars._build(b"") is None
    assert avatars._build(JPEG + b"\x00" * avatars.MAX_BYTES) is None


def test_a_changed_picture_gets_a_changed_tag():
    assert avatars._build(JPEG).etag != avatars._build(JPEG + b"\x01\x02").etag


# ── only Telegram URLs are followed ─────────────────────────────────────────
def test_only_telegram_hosts_are_accepted_for_a_photo_url():
    assert auth.safe_photo_url("https://t.me/i/userpic/320/abc.jpg")
    assert auth.safe_photo_url("https://cdn4.telegram-cdn.org/file/abc.jpg")
    # not https, not Telegram, or a lookalike host that merely starts the same
    assert auth.safe_photo_url("http://t.me/i/userpic/320/abc.jpg") == ""
    assert auth.safe_photo_url("https://evil.example/t.me/x.jpg") == ""
    assert auth.safe_photo_url("https://t.me.evil.example/x.jpg") == ""
    assert auth.safe_photo_url("javascript:alert(1)") == ""


def test_init_data_carries_the_signed_picture_url():
    import hashlib
    import hmac
    import json
    import time
    from urllib.parse import urlencode

    from vyron.config import settings

    token = settings.bot_token
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH-avatar",
        "user": json.dumps(
            {
                "id": 424242,
                "first_name": "Test",
                "photo_url": "https://t.me/i/userpic/320/abc.jpg",
            }
        ),
    }
    check = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()

    user = auth.verify_init_data(urlencode(fields), token)
    assert user is not None and user.photo.endswith("/abc.jpg")


# ── fetching ────────────────────────────────────────────────────────────────
def test_the_url_is_tried_before_the_bot(monkeypatch):
    calls = {"url": 0, "bot": 0}

    async def fake_url(url):
        calls["url"] += 1
        return avatars._build(JPEG)

    async def fake_bot(user_id):
        calls["bot"] += 1
        return avatars._build(PNG)

    monkeypatch.setattr(avatars, "from_url", fake_url)
    monkeypatch.setattr(avatars, "from_bot", fake_bot)

    picture = asyncio.run(avatars.avatar_for(7, "https://t.me/i/userpic/320/a.jpg"))
    assert picture is not None and picture.content_type == "image/jpeg"
    assert calls == {"url": 1, "bot": 0}


def test_the_bot_is_used_when_there_is_no_photo_url(monkeypatch):
    async def fake_bot(user_id):
        return avatars._build(PNG)

    monkeypatch.setattr(avatars, "from_bot", fake_bot)
    picture = asyncio.run(avatars.avatar_for(7, ""))
    assert picture is not None and picture.content_type == "image/png"


def test_a_fetched_picture_is_not_fetched_twice(monkeypatch):
    calls = {"n": 0}

    async def fake_bot(user_id):
        calls["n"] += 1
        return avatars._build(JPEG)

    monkeypatch.setattr(avatars, "from_bot", fake_bot)
    asyncio.run(avatars.avatar_for(7))
    asyncio.run(avatars.avatar_for(7))
    asyncio.run(avatars.avatar_for(7))
    assert calls["n"] == 1


def test_a_user_without_a_picture_is_not_asked_again(monkeypatch):
    calls = {"n": 0}

    async def fake_bot(user_id):
        calls["n"] += 1
        return None

    monkeypatch.setattr(avatars, "from_bot", fake_bot)
    assert asyncio.run(avatars.avatar_for(9)) is None
    assert asyncio.run(avatars.avatar_for(9)) is None
    assert calls["n"] == 1  # a miss is remembered for MISS_TTL

    avatars.forget(9)
    assert asyncio.run(avatars.avatar_for(9)) is None
    assert calls["n"] == 2


def test_the_bot_source_survives_a_broken_client(monkeypatch):
    from vyron.runtime import runtime

    class Broken:
        async def get_chat(self, _user):  # pragma: no cover - must be caught
            raise RuntimeError("telegram is down")

        async def get_profile_photos(self, *_a, **_k):  # pragma: no cover
            raise RuntimeError("telegram is down")

    monkeypatch.setattr(runtime, "bot", Broken(), raising=False)
    assert asyncio.run(avatars.from_bot(5)) is None


def test_the_bot_source_downloads_the_biggest_picture(monkeypatch):
    from vyron.runtime import runtime

    class Photo:
        big_file_id = "big"
        small_file_id = "small"

    class Chat:
        photo = Photo()

    asked: list[str] = []

    class Bot:
        async def get_chat(self, _user):
            return Chat()

        async def download_media(self, file_id, **_kwargs):
            asked.append(file_id)
            return io.BytesIO(JPEG)

    monkeypatch.setattr(runtime, "bot", Bot(), raising=False)
    picture = asyncio.run(avatars.from_bot(11))
    assert picture is not None and picture.content_type == "image/jpeg"
    assert asked == ["big"]
