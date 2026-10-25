"""Searching the way people actually type.

Two real chats, in order: `.play wrong cheris grey` and `.play let the world
burn` — Chris Grey's songs — both answered "No results" while the same bot had
played them minutes earlier. The name was misspelt, and the search stack
treated a misspelling as a reason to return nothing at all.
"""
from __future__ import annotations

import asyncio

import pytest

from vyron.core import search as search_module
from vyron.core.public_streams import parse_search_item
from vyron.core.queue import Track
from vyron.core.search import YouTube, is_confident_match, match_confidence


@pytest.fixture(autouse=True)
def clean_cache():
    search_module.clear_search_cache()
    yield
    search_module.clear_search_cache()


def _grey(title: str = "Wrong", uploader: str = "Chris Grey") -> Track:
    return Track(id="yt1", title=title, uploader=uploader, duration=187, source="youtube")


def test_a_misspelt_artist_name_is_still_the_same_artist():
    track = _grey()
    assert match_confidence("wrong cheris grey", track) > 0.0
    assert is_confident_match("wrong cheris grey", track), "this is the song they meant"


def test_a_typo_does_not_make_the_whole_query_irrelevant():
    engine = YouTube.__new__(YouTube)
    picked = engine._relevant("wrong cheris grey", [_grey(), Track(id="x", title="Piano Cover", uploader="Someone")])
    assert [track.id for track in picked] == ["yt1"]


def test_a_different_word_is_not_a_match():
    """"cheris" may be "chris"; "live" must not become "love"."""
    assert not is_confident_match("love story", _grey("Live Forever", "Chris Grey"))


def test_the_song_without_the_artist_still_matches():
    assert is_confident_match("let the world burn", _grey("LET THE WORLD BURN", "Chris Grey"))


# ── the ladder keeps going when one lane dies ─────────────────────────────
class _Engine(YouTube):
    def __init__(self, *, ytmusic=(), ytsearch=None, instances=(), walled=False):
        self.settings = type("S", (), {"search_results": 6, "music_sources": "jiosaavn"})()
        self._ytmusic = list(ytmusic)
        self._ytsearch = ytsearch
        self._instances = list(instances)
        self._walled = walled

    def walled(self) -> bool:
        return self._walled

    async def _ytmusic_search(self, query, limit):
        return list(self._ytmusic)

    async def _async_extract(self, target, **extra):
        if self._ytsearch is None:
            raise RuntimeError("ERROR: [youtube] sign in to confirm you're not a bot")
        return {"entries": self._ytsearch}

    async def _instance_search(self, query, limit, requester):
        return list(self._instances)


def test_a_refused_ytsearch_does_not_throw_away_the_other_lanes():
    engine = _Engine(instances=[_grey()])
    tracks = asyncio.run(engine._search_youtube("wrong cheris grey", 6, 6, (0, "")))
    assert [track.id for track in tracks] == ["yt1"]


def test_the_instance_lane_answers_when_youtube_treats_us_as_a_bot():
    engine = _Engine(ytsearch=None, instances=[_grey("LET THE WORLD BURN")])
    tracks = asyncio.run(engine._search_youtube("let the world burn", 6, 6, (0, "")))
    assert tracks and tracks[0].title == "LET THE WORLD BURN"
    assert tracks[0].source == "youtube", "an instance row is a YouTube video"


# ── reading both instance dialects ────────────────────────────────────────
def test_an_invidious_row_becomes_a_track():
    row = parse_search_item(
        "invidious",
        {
            "videoId": "dQw4w9WgXcQ",
            "title": "Wrong",
            "lengthSeconds": 187,
            "author": "Chris Grey",
            "viewCount": 12_345_678,
        },
    )
    assert row["id"] == "dQw4w9WgXcQ" and row["duration"] == 187
    assert row["uploader"] == "Chris Grey" and row["views"] == 12_345_678
    assert row["thumbnail"].endswith("hqdefault.jpg")


def test_a_piped_row_becomes_a_track():
    row = parse_search_item(
        "piped",
        {"id": "dQw4w9WgXcQ", "title": "Let the World Burn", "duration": "PT3M7S", "uploaderName": "Chris Grey"},
    )
    assert row["duration"] == 187 and row["uploader"] == "Chris Grey"


def test_a_junk_row_is_dropped():
    assert parse_search_item("piped", {"id": "", "title": "x"}) is None
    assert parse_search_item("invidious", {"videoId": "dQw4w9WgXcQ", "title": ""}) is None
