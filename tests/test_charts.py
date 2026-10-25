"""Discovery shelves — YouTube Music charts first, yt-dlp behind them."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest

from vyron.core import ytmusic
from vyron.core.charts import Charts
from vyron.core.queue import Track


class FakeYouTube:
    def __init__(self, playlist=(), search=()):
        self._playlist = list(playlist)
        self._search = list(search)
        self.calls: list[str] = []

    async def playlist(self, url: str, limit: int = 10):
        self.calls.append(f"playlist:{url}")
        return "", list(self._playlist)

    async def search(self, query: str, limit: int = 5):
        self.calls.append(f"search:{query}")
        return list(self._search)


CHART = {
    "videoId": "abc123",
    "title": "Top Song",
    "artists": [{"name": "Top Artist"}],
    "duration_seconds": 201,
    "thumbnails": [{"url": "https://img/small.jpg", "width": 120},
                   {"url": "https://img/top.jpg", "width": 544}],
    "thumbnail": "https://img/top.jpg",
    "source": "ytmusic",
}


class FakeClient:
    def __init__(self):
        self.playlist_ids: list[str] = []

    def get_charts(self, country: str = "ZZ"):
        assert country == "IN"
        return {
            "videos": [
                {"title": "Top 50 India", "playlistId": "PL_top"},
                {"title": "Top 50 Pop", "playlistId": "PL_pop"},
            ]
        }

    def get_playlist(self, playlist_id: str, limit: int = 25):
        self.playlist_ids.append(playlist_id)
        return {"tracks": [CHART]}


@pytest.fixture
def fake_ytmusic(monkeypatch):
    monkeypatch.setattr(ytmusic, "_client", FakeClient())
    monkeypatch.setattr(ytmusic, "_unavailable", False)
    monkeypatch.setattr(ytmusic, "available", lambda: True)
    return ytmusic


def test_charts_are_preferred_over_yt_dlp(fake_ytmusic):
    youtube = FakeYouTube(playlist=[Track(id="old", title="Trending upload")])
    charts = Charts(youtube, country="IN")

    tracks = asyncio.run(charts.trending(limit=5))

    assert [t.id for t in tracks] == ["abc123"]
    assert tracks[0].uploader == "Top Artist"
    assert tracks[0].thumbnail == "https://img/top.jpg"
    assert tracks[0].url.endswith("watch?v=abc123")
    # The yt-dlp trending feed is not even asked for.
    assert youtube.calls == []


def test_the_all_genres_chart_is_opened_first(fake_ytmusic):
    asyncio.run(Charts(FakeYouTube(), country="IN").trending(limit=5))
    assert fake_ytmusic._client.playlist_ids == ["PL_top"]


def test_falls_back_to_yt_dlp_when_charts_are_empty(monkeypatch):
    monkeypatch.setattr(ytmusic, "available", lambda: True)

    async def none(*args, **kwargs):
        return []

    monkeypatch.setattr(ytmusic, "chart_tracks", none)
    youtube = FakeYouTube(playlist=[Track(id="old", title="Trending upload")])

    tracks = asyncio.run(Charts(youtube, country="IN").trending(limit=5))

    assert [t.id for t in tracks] == ["old"]
    assert any(call.startswith("playlist:") for call in youtube.calls)


def test_missing_ytmusicapi_never_touches_the_network(monkeypatch):
    monkeypatch.setattr(ytmusic, "available", lambda: False)
    youtube = FakeYouTube(search=[Track(id="s1", title="From search")])
    charts = Charts(youtube, country="IN")

    tracks = asyncio.run(charts.trending(limit=3))

    # Trending url fails? No — the FakeYouTube returns nothing for playlist,
    # so the mood-search fallback fills the shelf.
    assert [t.id for t in tracks] == ["s1"]


def test_country_defaults_and_is_normalised():
    assert Charts(FakeYouTube()).country == "ZZ"
    assert Charts(FakeYouTube(), country="in").country == "IN"
    assert Charts(FakeYouTube(), country="").country == "ZZ"


def test_settings_carry_the_charts_country(monkeypatch):
    monkeypatch.setenv("CHARTS_COUNTRY", "in")
    from vyron.config import Settings

    assert dataclasses.replace(Settings()).charts_country == "IN"

    monkeypatch.setenv("CHARTS_COUNTRY", "")
    assert dataclasses.replace(Settings()).charts_country == "ZZ"
