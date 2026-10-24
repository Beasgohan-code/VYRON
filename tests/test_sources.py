# ---------------------------------------------------------------------------
#  Extra sources: Spotify / Deezer / Apple Music / SoundCloud catalogues
#  and the optional YouTube Music search provider.
#
#  All offline: link parsing is pure, and the network paths are fed canned
#  payloads that match the real endpoints' shapes.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from vyron.core import metasources as meta
from vyron.core import ytmusic


# ── link detection ──────────────────────────────────────────────────────────
def test_spotify_links_in_every_shape():
    cases = {
        "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT": ("track", "4cOdK2wGLETKBW3PvgPWqT"),
        "https://open.spotify.com/intl-de/track/4cOdK2wGLETKBW3PvgPWqT?si=abc": (
            "track",
            "4cOdK2wGLETKBW3PvgPWqT",
        ),
        "https://open.spotify.com/album/1ATL5GLyefJaxhQzSPVrLX": ("album", "1ATL5GLyefJaxhQzSPVrLX"),
        "spotify:track:4cOdK2wGLETKBW3PvgPWqT": ("track", "4cOdK2wGLETKBW3PvgPWqT"),
    }
    for url, (kind, ident) in cases.items():
        link = meta.detect(url)
        assert link is not None, url
        assert (link.service, link.kind, link.id) == ("spotify", kind, ident)


def test_deezer_links_include_short_ones():
    track = meta.detect("https://www.deezer.com/en/track/3135556")
    assert track is not None and (track.kind, track.id) == ("track", "3135556")

    album = meta.detect("https://www.deezer.com/album/302127")
    assert album is not None and album.kind == "album"

    short = meta.detect("https://deezer.page.link/abc123")
    assert short is not None and short.kind == "short"


def test_apple_music_track_album_and_song_links():
    song = meta.detect("https://music.apple.com/us/album/brahmastra/1635000000?i=1635000001")
    assert song is not None and (song.kind, song.id) == ("song", "1635000001")

    album = meta.detect("https://music.apple.com/us/album/brahmastra/1635000000")
    assert album is not None and (album.kind, album.id) == ("album", "1635000000")

    direct = meta.detect("https://music.apple.com/us/song/tum-hi-ho/1440857781")
    assert direct is not None and (direct.kind, direct.id) == ("song", "1440857781")


def test_soundcloud_and_youtube_music():
    assert meta.detect("https://soundcloud.com/artist/track-name").service == "soundcloud"
    yt = meta.detect("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
    assert yt is not None and yt.service == "ytmusic" and yt.id == "dQw4w9WgXcQ"
    assert meta.is_passthrough("https://music.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not meta.is_catalogue_link("https://music.youtube.com/watch?v=dQw4w9WgXcQ")


def test_unknown_links_are_not_catalogue_links():
    assert meta.detect("https://youtu.be/dQw4w9WgXcQ") is None
    assert not meta.is_catalogue_link("https://example.com/song")
    assert meta.detect("") is None


# ── metadata → search query ─────────────────────────────────────────────────
def test_track_query_is_artist_then_title():
    track = meta.MetaTrack(title="Kesariya", artist="Arijit Singh")
    assert track.query == "Arijit Singh Kesariya"
    assert meta.MetaTrack(title="Kesariya").query == "Kesariya"
    assert meta.MetaTrack(title="Kesariya", artist="Arijit Singh").as_dict()["query"] == (
        "Arijit Singh Kesariya"
    )


def test_collection_queries_are_capped():
    collection = meta.MetaCollection(
        kind="album",
        title="Brahmastra",
        tracks=[meta.MetaTrack(title=f"t{i}", artist="a") for i in range(80)],
    )
    assert len(collection.queries(limit=10)) == 10


# ── endpoint payloads ───────────────────────────────────────────────────────
def test_deezer_track_payload_maps_to_metadata():
    payload = {
        "title": "Kesariya",
        "duration": 268,
        "link": "https://www.deezer.com/track/1",
        "artist": {"name": "Arijit Singh"},
        "album": {"cover_xl": "https://cdn/cover.jpg"},
    }
    track = meta._deezer_track(payload)
    assert track is not None
    assert (track.title, track.artist, track.duration) == ("Kesariya", "Arijit Singh", 268)
    assert track.artwork == "https://cdn/cover.jpg"
    assert meta._deezer_track({"error": {"type": "DataException"}}) is None


def test_deezer_album_and_playlist_collections(monkeypatch):
    async def fake_json(url, session=None):
        if "/album/" in url:
            return {
                "title": "Brahmastra",
                "tracks": {
                    "data": [
                        {"title": "Kesariya", "artist": {"name": "Arijit Singh"}, "duration": 268},
                        {"title": "Deva Deva", "artist": {"name": "Arijit Singh"}, "duration": 240},
                    ]
                },
            }
        return {"title": "Chill", "tracks": {"data": [{"title": "One", "artist": {"name": "X"}}]}}

    monkeypatch.setattr(meta, "_json", fake_json)
    album = asyncio.run(meta._deezer(meta._Link("deezer", "album", "302127")))
    assert isinstance(album, meta.MetaCollection)
    assert album.title == "Brahmastra" and len(album.tracks) == 2

    playlist = asyncio.run(meta._deezer(meta._Link("deezer", "playlist", "908622995")))
    assert isinstance(playlist, meta.MetaCollection) and playlist.kind == "playlist"


def test_apple_song_lookup(monkeypatch):
    async def fake_json(url, session=None):
        assert "lookup?id=1440857781" in url
        return {
            "results": [
                {
                    "trackName": "Tum Hi Ho",
                    "artistName": "Arijit Singh",
                    "trackTimeMillis": 262000,
                    "artworkUrl100": "https://is1/cover.jpg",
                    "trackViewUrl": "https://music.apple.com/x",
                }
            ]
        }

    monkeypatch.setattr(meta, "_json", fake_json)
    track = asyncio.run(meta._apple(meta._Link("apple", "song", "1440857781")))
    assert isinstance(track, meta.MetaTrack)
    assert (track.title, track.artist, track.duration) == ("Tum Hi Ho", "Arijit Singh", 262)


def test_apple_album_becomes_a_collection(monkeypatch):
    async def fake_json(url, session=None):
        return {
            "results": [
                {"wrapperType": "collection", "collectionName": "Brahmastra"},
                {
                    "wrapperType": "track",
                    "trackName": "Kesariya",
                    "artistName": "Arijit Singh",
                    "trackTimeMillis": 268000,
                },
                {
                    "wrapperType": "track",
                    "trackName": "Deva Deva",
                    "artistName": "Arijit Singh",
                    "trackTimeMillis": 240000,
                },
            ]
        }

    monkeypatch.setattr(meta, "_json", fake_json)
    found = asyncio.run(meta._apple(meta._Link("apple", "album", "1635000000")))
    assert isinstance(found, meta.MetaCollection)
    assert found.title == "Brahmastra" and len(found.tracks) == 2


def test_spotify_embed_page_is_parsed():
    entity = {
        "name": "Kesariya",
        "artists": [{"name": "Arijit Singh"}, {"name": "Pritam"}],
        "duration": 268000,
        "coverArt": {"sources": [{"url": "https://i.scdn.co/cover.jpg"}]},
    }
    page = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
        + "</script>"
    )
    parsed = meta._spotify_embed_entity(page)
    assert parsed is not None
    track = meta._spotify_track_from_entity(parsed)
    assert track is not None
    assert track.title == "Kesariya"
    assert track.artist == "Arijit Singh, Pritam"
    assert track.duration == 268
    assert track.artwork == "https://i.scdn.co/cover.jpg"


def test_spotify_playlist_embed_lists_tracks(monkeypatch):
    entity = {
        "name": "Lo-fi",
        "trackList": [
            {"title": "One", "subtitle": "Artist A", "duration": 120000},
            {"title": "Two", "subtitle": "Artist B", "duration": 0},
        ],
    }
    page = (
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"props": {"pageProps": {"state": {"data": {"entity": entity}}}}})
        + "</script>"
    )

    async def fake_text(url):
        return page

    monkeypatch.setattr(meta, "_text", fake_text)
    found = asyncio.run(meta._spotify(meta._Link("spotify", "playlist", "37i9dQZF1DXcBWIGoYBM5M")))
    assert isinstance(found, meta.MetaCollection)
    assert found.title == "Lo-fi" and [t.title for t in found.tracks] == ["One", "Two"]


def test_spotify_oembed_fallback_splits_the_title(monkeypatch):
    async def no_page(url):
        return None

    async def fake_json(url, session=None):
        return {"title": "Kesariya - song and lyrics by Arijit Singh", "thumbnail_url": "https://i/x.jpg"}

    monkeypatch.setattr(meta, "_text", no_page)
    monkeypatch.setattr(meta, "_json", fake_json)
    track = asyncio.run(meta._spotify(meta._Link("spotify", "track", "abc123")))
    assert isinstance(track, meta.MetaTrack)
    assert (track.title, track.artist) == ("Kesariya", "Arijit Singh")


def test_lookup_never_raises_on_a_broken_service(monkeypatch):
    async def boom(url, session=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(meta, "_json", boom)
    monkeypatch.setattr(meta, "_text", boom)
    assert asyncio.run(meta.lookup("https://api.deezer.com/track/1")) is None
    assert asyncio.run(meta.lookup("https://example.com/nope")) is None


# ── YouTube Music provider ──────────────────────────────────────────────────
def test_ytmusic_entry_mapping():
    entry = ytmusic.parse_entry(
        {
            "videoId": "dQw4w9WgXcQ",
            "title": "Kesariya",
            "artists": [{"name": "Arijit Singh"}],
            "album": {"name": "Brahmastra"},
            "duration": "4:28",
            "thumbnails": [
                {"url": "https://i/small.jpg", "width": 60},
                {"url": "https://i/big.jpg", "width": 544},
            ],
        }
    )
    assert entry is not None
    assert entry["id"] == "dQw4w9WgXcQ"
    assert entry["uploader"] == "Arijit Singh"
    assert entry["duration"] == 268
    assert entry["thumbnail"] == "https://i/big.jpg"
    assert entry["is_video"] is False


def test_ytmusic_entry_without_a_video_id_is_skipped():
    assert ytmusic.parse_entry({"title": "no id"}) is None
    assert ytmusic.parse_entry({"videoId": "abc", "duration_seconds": 61})["duration"] == 61


def test_ytmusic_search_is_quiet_when_the_package_is_missing(monkeypatch):
    monkeypatch.setattr(ytmusic, "_unavailable", True)
    assert ytmusic.available() is False
    assert asyncio.run(ytmusic.search("anything")) == []
    assert "not installed" in ytmusic.describe()


def test_ytmusic_search_uses_the_thread_pool(monkeypatch):
    monkeypatch.setattr(ytmusic, "_unavailable", False)
    monkeypatch.setattr(ytmusic, "available", lambda: True)
    captured = {}

    def fake_sync(query, limit, filter_):
        captured["args"] = (query, limit, filter_)
        return [{"id": "abc", "title": "t"}]

    monkeypatch.setattr(ytmusic, "_search_sync", fake_sync)
    result = asyncio.run(ytmusic.search("kesariya", limit=5))
    assert captured["args"] == ("kesariya", 5, "songs")
    assert result == [{"id": "abc", "title": "t"}]


# ── resolver integration ────────────────────────────────────────────────────
def _engine():
    from vyron.config import settings
    from vyron.core.search import YouTube

    return YouTube(settings)


def test_catalogue_link_resolves_through_youtube(monkeypatch):
    """A Spotify link becomes a YouTube track, keeping the catalogue artwork."""
    async def fake_lookup(url):
        return meta.MetaTrack(
            title="Kesariya",
            artist="Arijit Singh",
            artwork="https://i.scdn.co/big.jpg",
            service="spotify",
        )

    async def fake_search(self, query, limit=None, requester=(0, "")):
        assert query == "Arijit Singh Kesariya"
        from vyron.core.queue import Track

        return [Track(id="dQw4w9WgXcQ", title="Kesariya", uploader="", duration=268)]

    monkeypatch.setattr(meta, "lookup", fake_lookup)
    monkeypatch.setattr("vyron.core.search.YouTube.search", fake_search)

    engine = _engine()
    track = asyncio.run(engine.resolve("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"))
    assert track.id == "dQw4w9WgXcQ"
    assert track.thumbnail == "https://i.scdn.co/big.jpg"
    assert track.uploader == "Arijit Singh"
    assert track.source == "spotify·youtube"


def test_catalogue_collection_is_matched_track_by_track(monkeypatch):
    async def fake_lookup(url):
        return meta.MetaCollection(
            kind="album",
            title="Brahmastra",
            service="deezer",
            tracks=[
                meta.MetaTrack(title="Kesariya", artist="Arijit Singh"),
                meta.MetaTrack(title="Deva Deva", artist="Arijit Singh"),
            ],
        )

    calls: list[str] = []

    async def fake_search(self, query, limit=None, requester=(0, "")):
        from vyron.core.queue import Track

        calls.append(query)
        if "missing" in query:
            from vyron.core.search import MediaError

            raise MediaError("no results")
        return [Track(id="id" + str(len(calls)), title=query, duration=200)]

    monkeypatch.setattr(meta, "lookup", fake_lookup)
    monkeypatch.setattr("vyron.core.search.YouTube.search", fake_search)

    engine = _engine()
    title, tracks = asyncio.run(engine.resolve_collection("https://www.deezer.com/album/302127"))
    assert title == "Brahmastra"
    assert len(tracks) == 2
    assert all(track.source == "deezer·youtube" for track in tracks)


def test_catalogue_tier_can_be_switched_off(monkeypatch):
    import dataclasses

    from vyron.config import settings

    async def fake_lookup(url):  # pragma: no cover - must not be called
        raise AssertionError("catalogue lookup should be skipped")

    monkeypatch.setattr(meta, "lookup", fake_lookup)
    engine = _engine()
    engine.settings = dataclasses.replace(settings, music_sources="off")
    assert engine._catalogue_enabled() is False
    assert asyncio.run(engine.resolve_collection("https://www.deezer.com/album/1")) is None


def test_music_sources_off_disables_catalogue_links():
    import dataclasses

    from vyron.config import settings
    from vyron.core.search import YouTube

    off = YouTube(dataclasses.replace(settings, music_sources="off"))
    assert off._catalogue_enabled() is False

    on = YouTube(dataclasses.replace(settings, music_sources="spotify,deezer"))
    assert on._catalogue_enabled() is True

    assert settings.music_sources  # the real setting keeps its default


# ── play mode (BadMusic's "playmode"): everyone vs admins only ──────────────
def meta_message(chat_type: str = "group"):
    from types import SimpleNamespace

    kind = "PRIVATE" if chat_type == "private" else "SUPERGROUP"
    from pyrogram.enums import ChatType

    return SimpleNamespace(
        chat=SimpleNamespace(id=-100 if chat_type != "private" else 42, type=getattr(ChatType, kind)),
        from_user=SimpleNamespace(id=5, first_name="Ann", last_name=None),
        id=9,
    )


def test_play_mode_lets_private_chats_through(monkeypatch):
    from vyron.modules import play as play_module

    message = meta_message(chat_type="private")
    assert asyncio.run(play_module.may_request(None, message)) is True


def test_play_mode_blocks_a_member_when_admins_only(monkeypatch):
    from vyron.modules import play as play_module

    async def admins_only(chat_id, key, default=None):
        assert key == "admins_only"
        return True

    monkeypatch.setattr(play_module.chatcfg, "get", admins_only)
    monkeypatch.setattr(play_module, "is_owner", lambda uid: False)

    async def not_admin(client, chat_id, uid):
        return False

    monkeypatch.setattr(play_module, "is_chat_admin", not_admin)

    sent = {}

    async def fake_send(client, chat_id, markup, **kwargs):
        sent["markup"] = markup
        return SimpleNamespace(id=1)

    monkeypatch.setattr(play_module.rich, "send", fake_send)
    assert asyncio.run(play_module.may_request(None, meta_message())) is False
    assert "Admins only here" in sent["markup"]


def test_play_mode_lets_an_admin_through(monkeypatch):
    from vyron.modules import play as play_module

    async def admins_only(chat_id, key, default=None):
        return True

    monkeypatch.setattr(play_module.chatcfg, "get", admins_only)
    monkeypatch.setattr(play_module, "is_owner", lambda uid: False)

    async def admin(client, chat_id, uid):
        return True

    monkeypatch.setattr(play_module, "is_chat_admin", admin)
    assert asyncio.run(play_module.may_request(None, meta_message())) is True


# ── Audius: a catalogue that can serve the audio itself ─────────────────────
def test_audius_links_are_recognised():
    from vyron.core import audius

    assert audius.is_audius("https://audius.co/artist/track-name")
    assert audius.is_audius("audius.co/artist/track-name")
    assert not audius.is_audius("https://open.spotify.com/track/abc")
    assert audius.stream_url("https://node.audius.co/", "D7KyD") == (
        "https://node.audius.co/v1/tracks/D7KyD/stream?app_name=VYRON"
    )


def test_audius_track_payload_becomes_a_playable_track():
    from vyron.core import audius

    track = audius.parse_track(
        {
            "id": "D7KyD",
            "title": "Sunset Drive",
            "duration": 214,
            "artwork": {"480x480": "https://cdn/art.jpg"},
            "user": {"name": "Nova"},
        },
        "https://node.audius.co",
    )
    assert track is not None
    assert (track.id, track.title, track.duration) == ("D7KyD", "Sunset Drive", 214)
    assert track.uploader == "Nova"
    assert track.thumbnail == "https://cdn/art.jpg"
    assert track.source == "audius"
    assert track.url.endswith("/v1/tracks/D7KyD/stream?app_name=VYRON")
    assert audius.parse_track({"_type": "playlist", "id": "x"}) is None


def test_audius_resolve_uses_a_discovery_node(monkeypatch):
    from vyron.core import audius

    seen = {}

    async def fake_host():
        return "https://node.audius.co"

    async def fake_json(url):
        seen["url"] = url
        return {"data": {"id": "D7KyD", "title": "Sunset Drive", "user": {"name": "Nova"}}}

    monkeypatch.setattr(audius, "host", fake_host)
    monkeypatch.setattr(audius, "_json", fake_json)
    track = asyncio.run(audius.resolve("https://audius.co/nova/sunset-drive"))
    assert track is not None and track.id == "D7KyD"
    assert "/v1/resolve?url=" in seen["url"]
    assert "app_name=VYRON" in seen["url"]


def test_audius_search_is_best_effort(monkeypatch):
    from vyron.core import audius

    async def fake_host():
        return "https://node.audius.co"

    async def fake_json(url):
        if "search" not in url:
            return None
        return {"data": [{"id": "A1", "title": "One"}, {"id": "A2", "title": "Two"}]}

    monkeypatch.setattr(audius, "host", fake_host)
    monkeypatch.setattr(audius, "_json", fake_json)
    assert [t.id for t in asyncio.run(audius.search("one"))] == ["A1", "A2"]
    assert asyncio.run(audius.search("")) == []


def test_a_direct_stream_track_is_downloaded_by_the_accelerator(monkeypatch, tmp_path):
    import dataclasses

    from vyron.config import settings
    from vyron.core import accelerator
    from vyron.core.downloader import Downloader
    from vyron.core.queue import Track

    target_dir = tmp_path / "dl"
    downloader = Downloader(dataclasses.replace(settings, downloads_dir=target_dir))
    called = {}

    async def fake_fetch(url, path, **kwargs):
        called["url"] = url
        path.write_bytes(b"\x00" * 64)
        return "curl"

    monkeypatch.setattr(accelerator, "fetch", fake_fetch)
    track = Track(
        id="D7KyD",
        title="Sunset Drive",
        url="https://node/v1/tracks/D7KyD/stream?app_name=VYRON",
        source="audius",
    )
    path = asyncio.run(downloader.fetch(track))
    assert path.name == "audius-D7KyD.mp3"
    assert path.read_bytes() == b"\x00" * 64
    assert called["url"].startswith("https://node/v1/tracks/D7KyD/stream")


def test_resolver_prefers_audius_for_an_audius_link(monkeypatch):
    from vyron.core import audius
    from vyron.core.queue import Track

    async def fake_resolve(url):
        return Track(id="A1", title="One", url="https://node/stream", source="audius")

    monkeypatch.setattr(audius, "resolve", fake_resolve)
    engine = _engine()
    track = asyncio.run(engine.resolve("https://audius.co/nova/one"))
    assert track.source == "audius" and track.url == "https://node/stream"


# ── JioSaavn: second direct-stream catalogue ────────────────────────────────
def test_jiosaavn_links_and_song_mapping():
    from vyron.core import jiosaavn

    assert jiosaavn.is_jiosaavn("https://www.jiosaavn.com/song/kesariya/ABC123")
    assert not jiosaavn.is_jiosaavn("https://open.spotify.com/track/x")

    track = jiosaavn.parse_song(
        {
            "id": "ABC123",
            "name": "Kesariya&nbsp;(From &quot;Brahmastra&quot;)",
            "duration": "268",
            "artists": {"primary": [{"name": "Arijit Singh"}]},
            "image": [
                {"quality": "50x50", "url": "https://c/50.jpg"},
                {"quality": "500x500", "url": "https://c/500.jpg"},
            ],
            "downloadUrl": [
                {"quality": "96kbps", "url": "https://a/96.mp4"},
                {"quality": "320kbps", "url": "https://a/320.mp4"},
            ],
        }
    )
    assert track is not None
    assert track.id == "ABC123" and track.source == "jiosaavn"
    assert track.title == 'Kesariya (From "Brahmastra")'
    assert track.uploader == "Arijit Singh" and track.duration == 268
    assert track.thumbnail == "https://c/500.jpg"
    assert track.url == "https://a/320.mp4"     # best quality wins
    assert jiosaavn.parse_song({"id": "x", "name": "no url"}) is None


def test_jiosaavn_search_and_resolve(monkeypatch):
    from vyron.core import jiosaavn

    async def fake_json(url):
        assert "search/songs" in url or "/songs/" in url
        return {
            "data": {
                "results": [
                    {
                        "id": "SONG1",
                        "name": "Kesariya",
                        "duration": 268,
                        "artists": {"primary": [{"name": "Arijit Singh"}]},
                        "downloadUrl": [{"quality": "320kbps", "url": "https://a/320.mp4"}],
                    }
                ]
            }
        }

    monkeypatch.setattr(jiosaavn, "_json", fake_json)
    tracks = asyncio.run(jiosaavn.search("kesariya"))
    assert len(tracks) == 1 and tracks[0].url == "https://a/320.mp4"

    resolved = asyncio.run(jiosaavn.resolve("https://www.jiosaavn.com/song/kesariya/ABC"))
    assert resolved is not None and resolved.id == "SONG1"


# ── the registry: order, fallbacks, health ──────────────────────────────────
def test_registry_lists_primary_streams_and_catalogues():
    from vyron.core import sources

    names = sources.names()
    assert names[:2] == ["ytmusic", "ytdlp"]
    assert "audius" in names and "jiosaavn" in names
    assert {"spotify", "deezer", "apple", "soundcloud"} <= set(names)
    assert sources.DIRECT_SOURCES == {"audius", "jiosaavn"}
    order = sources.describe()
    assert order.startswith("ytmusic · ytdlp")


def test_registry_falls_through_to_the_next_stream_source(monkeypatch):
    from vyron.core import sources
    from vyron.core.queue import Track

    class _Breaking:
        async def search(self, query, limit):
            raise RuntimeError("down")

    class _Working:
        def __init__(self):
            self.calls = 0

        async def search(self, query, limit):
            self.calls += 1
            return [Track(id="j1", title=query, duration=100, source="jiosaavn")]

    working = _Working()
    patched = [
        sources.Source("audius", "Audius", "stream", search=_Breaking().search),
        sources.Source("jiosaavn", "JioSaavn", "stream", search=working.search),
    ]
    monkeypatch.setattr(sources, "search_sources", lambda settings=None: patched)

    found = asyncio.run(sources.fallback_search("kesariya", 3))
    assert [track.id for track in found] == ["j1"]
    assert working.calls == 1
    assert patched[0].status()["failures"] == 1


def test_a_source_in_cooldown_is_skipped(monkeypatch):
    from vyron.core import sources

    calls = {"n": 0}

    async def boom(query, limit):
        calls["n"] += 1
        raise RuntimeError("still down")

    source = sources.Source("audius", "Audius", "stream", search=boom)
    monkeypatch.setattr(sources, "search_sources", lambda settings=None: [source])
    assert asyncio.run(sources.fallback_search("x", 2)) == []
    assert asyncio.run(sources.fallback_search("x", 2)) == []
    assert calls["n"] == 2                 # two attempts, then the cooldown bites
    assert source.available() is False


def test_content_status_is_json_safe():
    from vyron.core import sources

    rows = sources.status()
    for row in rows:
        assert set(row) >= {"name", "kind", "enabled", "available", "last_ok"}


# ── SoundCloud / Bandcamp: platforms yt-dlp reads itself ────────────────────
class _FakeYDL:
    """Stands in for yt-dlp: records what was asked, returns canned info."""

    calls: list[str] = []
    info: dict = {}

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, target, download=False):
        _FakeYDL.calls.append(target)
        return _FakeYDL.info


def _use_fake(monkeypatch, info):
    from vyron.core import extract

    _FakeYDL.calls = []
    _FakeYDL.info = info
    monkeypatch.setattr(extract.yt_dlp, "YoutubeDL", _FakeYDL)
    return extract


def test_extract_recognises_its_platforms():
    from vyron.core import extract

    assert extract.service_of("https://soundcloud.com/artist/remix") == "soundcloud"
    assert extract.service_of("https://on.soundcloud.com/abc") == "soundcloud"
    assert extract.service_of("https://artist.bandcamp.com/track/song") == "bandcamp"
    assert extract.service_of("https://open.spotify.com/track/x") == ""
    assert extract.service_of("") == ""
    assert not extract.is_soundcloud("https://soundcloud.example.com/x")


def test_extract_search_builds_scsearch_and_maps_entries(monkeypatch):
    extract = _use_fake(
        monkeypatch,
        {
            "entries": [
                {
                    "id": "123456",
                    "title": "Kesariya (Slowed)",
                    "duration": 260,
                    "uploader": "someone",
                    "webpage_url": "https://soundcloud.com/someone/kesariya",
                    "thumbnails": [{"url": "https://i/120.jpg", "width": 120, "height": 120},
                                   {"url": "https://i/500.jpg", "width": 500, "height": 500}],
                },
                {"id": "broken", "title": ""},
            ]
        },
    )
    tracks = asyncio.run(extract.search_soundcloud("kesariya", 3))
    assert _FakeYDL.calls == ["scsearch3:kesariya"]
    assert len(tracks) == 1                       # the empty entry is dropped
    track = tracks[0]
    assert track.source == "soundcloud" and track.id == "123456"
    assert track.thumbnail == "https://i/500.jpg"  # largest thumbnail wins
    assert track.url == "https://soundcloud.com/someone/kesariya"


def test_extract_resolve_is_host_scoped(monkeypatch):
    extract = _use_fake(
        monkeypatch,
        {
            "id": "99",
            "title": "Home",
            "duration": 200,
            "uploader": "artist",
            "webpage_url": "https://artist.bandcamp.com/track/home",
            "formats": [],
        },
    )
    assert asyncio.run(extract.resolve_soundcloud("https://example.com/x")) is None
    track = asyncio.run(extract.resolve_bandcamp("https://artist.bandcamp.com/track/home"))
    assert track is not None and track.source == "bandcamp" and track.id == "99"


def test_extract_stream_url_prefers_audio_only(monkeypatch):
    extract = _use_fake(
        monkeypatch,
        {
            "formats": [
                {"url": "https://a/128", "acodec": "mp3", "vcodec": "none", "abr": 128},
                {"url": "https://a/256", "acodec": "mp3", "vcodec": "none", "abr": 256},
                {"url": "https://a/video", "acodec": "aac", "vcodec": "h264", "abr": 320},
            ]
        },
    )
    from vyron.core.queue import Track

    url = asyncio.run(extract.stream_url(Track(id="1", title="t", url="https://soundcloud.com/a/b")))
    assert url == "https://a/256"


def test_registry_exposes_soundcloud_and_bandcamp_as_streams():
    from vyron.core import sources

    rows = {row["name"]: row for row in sources.status()}
    assert rows["soundcloud"]["kind"] == "stream"
    assert rows["bandcamp"]["kind"] == "stream"
    assert "soundcloud" not in sources.CATALOGUE_SOURCES
    assert sources.EXTRACT_SOURCES == {"soundcloud", "bandcamp"}


def test_music_sources_names_the_catalogues_and_off_is_the_kill_switch():
    import dataclasses

    from vyron.config import settings
    from vyron.core import sources

    only_spotify = sources.registry(
        dataclasses.replace(settings, music_sources="spotify")
    )
    enabled = {row.name for row in only_spotify if row.kind == "catalogue" and row.is_enabled()}
    assert enabled == {"spotify"}
    # …and the fallback chain does not care: it is still there
    assert {"audius", "jiosaavn", "soundcloud", "bandcamp"} <= {
        row.name for row in only_spotify if row.kind == "stream" and row.is_enabled()
    }

    off = sources.registry(dataclasses.replace(settings, music_sources="off"))
    assert [row for row in off if row.is_enabled() and row.name not in {"ytmusic", "ytdlp"}] == []
    assert sources.describe(dataclasses.replace(settings, music_sources="off")).startswith(
        "ytmusic · ytdlp"
    )
