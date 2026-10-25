"""Cover art: the proxy that replaced a hotlink to i.ytimg.com."""
from __future__ import annotations

import asyncio
import io

import pytest

pytest.importorskip("aiohttp")
pytest.importorskip("pyrogram")

from aiohttp.test_utils import TestClient, TestServer

from vyron.config import settings
from vyron.core.queue import Track
from vyron.utils.health import build_app
from vyron.web import artwork, auth, stream

TOKEN = settings.bot_token
THUMB = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def _jpeg(size: int = 480) -> bytes:
    """A real, decodable JPEG — the resizer has to actually open it."""
    pillow = pytest.importorskip("PIL.Image")
    image = pillow.new("RGB", (size, size), (120, 80, 200))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _fresh():
    artwork.forget()
    yield
    artwork.forget()


# ── the three widths ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("asked", "snapped"),
    [("", 300), ("1", 96), ("96", 96), ("120", 96), ("300", 300), ("999", 600), ("junk", 300)],
)
def test_a_requested_width_snaps_to_one_we_cache(asked, snapped):
    assert artwork.size_from(asked) == snapped


# ── which URLs may be proxied ───────────────────────────────────────────────
def test_only_picture_cdns_are_proxied():
    assert artwork.allowed(THUMB) == THUMB
    assert artwork.allowed("https://yt3.googleusercontent.com/abc=s240") != ""
    # an arbitrary host, a non-https URL, and a lookalike domain are refused
    assert artwork.allowed("https://evil.example/x.jpg") == ""
    assert artwork.allowed("http://i.ytimg.com/vi/x/hq.jpg") == ""
    assert artwork.allowed("https://i.ytimg.com.evil.example/x.jpg") == ""
    assert artwork.allowed("file:///etc/passwd") == ""
    assert artwork.allowed("https://i.ytimg.com/" + "a" * 1000) == ""


# ── resizing ────────────────────────────────────────────────────────────────
def test_a_big_picture_is_shrunk_and_re_encoded():
    body = _jpeg(480)
    small, content_type = artwork.shrink(body, 96)
    assert content_type == "image/webp"
    assert len(small) < len(body)

    pillow = pytest.importorskip("PIL.Image")
    with pillow.open(io.BytesIO(small)) as image:
        assert max(image.size) <= 96


def test_a_smaller_picture_is_not_blown_up():
    body = _jpeg(64)
    pillow = pytest.importorskip("PIL.Image")
    out, _ = artwork.shrink(body, 600)
    with pillow.open(io.BytesIO(out)) as image:
        assert max(image.size) == 64


def test_a_broken_file_is_served_as_is_instead_of_failing():
    junk = b"\xff\xd8\xff\xe0" + b"0" * 64
    body, content_type = artwork.shrink(junk, 300)
    assert body == junk and content_type == "image/jpeg"


# ── the endpoint ────────────────────────────────────────────────────────────
async def _with_client(scenario):
    app = build_app(with_webapp=True)
    async with TestClient(TestServer(app)) as client:
        return await scenario(client)


def _register(track_id: str = "yt-art-1", thumbnail: str = THUMB) -> Track:
    track = Track(id=track_id, title="Art", duration=200, thumbnail=thumbnail)
    stream.remember(track)
    return track


def test_the_route_serves_the_track_artwork_and_then_304s(monkeypatch):
    async def no_network(url, limit=0):  # the fetch is what we are replacing
        return _jpeg(480)

    monkeypatch.setattr(artwork, "fetch_bytes", no_network)
    _register()

    async def scenario(client):
        first = await client.get("/api/art/yt-art-1?s=96")
        assert first.status == 200
        assert first.headers["Content-Type"].startswith("image/")
        assert "immutable" in first.headers["Cache-Control"]
        assert first.headers["ETag"]
        assert len(await first.read()) > 0

        again = await client.get("/api/art/yt-art-1?s=96", headers={"If-None-Match": first.headers["ETag"]})
        assert again.status == 304
        assert await again.read() == b""

    asyncio.run(_with_client(scenario))


def test_each_width_is_a_different_picture(monkeypatch):
    async def no_network(url, limit=0):
        return _jpeg(480)

    monkeypatch.setattr(artwork, "fetch_bytes", no_network)
    _register("yt-art-2")

    async def scenario(client):
        small = await client.get("/api/art/yt-art-2?s=96")
        big = await client.get("/api/art/yt-art-2?s=600")
        assert small.status == 200 and big.status == 200
        assert small.headers["ETag"] != big.headers["ETag"]

    asyncio.run(_with_client(scenario))


def test_the_picture_is_downloaded_once_for_every_size(monkeypatch):
    calls = {"n": 0}

    async def counting(url, limit=0):
        calls["n"] += 1
        return _jpeg(480)

    monkeypatch.setattr(artwork, "fetch_bytes", counting)
    _register("yt-art-3")

    async def scenario(client):
        for size in (96, 300, 600, 96):
            assert (await client.get(f"/api/art/yt-art-3?s={size}")).status == 200

    asyncio.run(_with_client(scenario))
    assert calls["n"] == 1


def test_a_track_nobody_was_shown_has_no_art():
    async def scenario(client):
        response = await client.get("/api/art/unknown-track")
        assert response.status == 404

    asyncio.run(_with_client(scenario))


def test_a_track_without_a_picture_is_a_404_not_a_placeholder():
    _register("yt-art-4", thumbnail="")

    async def scenario(client):
        assert (await client.get("/api/art/yt-art-4")).status == 404

    asyncio.run(_with_client(scenario))


def test_collection_art_is_proxied_by_url(monkeypatch):
    async def no_network(url, limit=0):
        assert url == THUMB
        return _jpeg(300)

    monkeypatch.setattr(artwork, "fetch_bytes", no_network)

    async def scenario(client):
        from urllib.parse import quote

        good = await client.get(f"/api/art?u={quote(THUMB, safe='')}")
        assert good.status == 200

        # and an arbitrary URL is refused before any request is made
        bad = await client.get(f"/api/art?u={quote('https://evil.example/x.jpg', safe='')}")
        assert bad.status == 404

        missing = await client.get("/api/art")
        assert missing.status == 404

    asyncio.run(_with_client(scenario))


def test_a_failing_download_is_a_404(monkeypatch):
    async def down(url, limit=0):
        return None

    monkeypatch.setattr(artwork, "fetch_bytes", down)
    _register("yt-art-5")

    async def scenario(client):
        assert (await client.get("/api/art/yt-art-5")).status == 404

    asyncio.run(_with_client(scenario))


def test_artwork_needs_no_telegram_session():
    """`<img src>` cannot carry a header, so this route is public by design.

    What keeps it honest is that it only serves ids this deployment has already
    shown somebody, and URLs on a fixed list of picture hosts.
    """
    _register("yt-art-6")

    async def scenario(client):
        # no credentials at all, and the deployment still refuses anonymous API
        assert (await client.post("/api/state", json={})).status == 401
        response = await client.get("/api/art/yt-art-6")
        assert response.status in (200, 404)  # 404 when there is no picture

    asyncio.run(_with_client(scenario))


def test_the_picture_never_sends_a_referrer(monkeypatch):
    """The app lives at a URL carrying `?t=`; the picture must not echo it back."""
    async def no_network(url, limit=0):
        return _jpeg(240)

    monkeypatch.setattr(artwork, "fetch_bytes", no_network)
    _register("yt-art-7")
    token = auth.make_token(-100999, 424242, TOKEN)

    async def scenario(client):
        response = await client.get(f"/api/art/yt-art-7?t={token}")
        assert response.status == 200
        assert response.headers["Referrer-Policy"] == "no-referrer"

    asyncio.run(_with_client(scenario))
