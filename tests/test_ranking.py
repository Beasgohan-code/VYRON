"""Search ranking: the right recording first, the noise after it."""
from __future__ import annotations

from vyron.core.queue import Track
from vyron.core.search import YouTube


def rank(query: str, tracks: list[Track]) -> list[Track]:
    return YouTube.rank(YouTube.__new__(YouTube), query, tracks)  # no I/O in rank()


def test_the_actual_recording_beats_a_reupload():
    official = Track(id="off1", title="Kesariya", duration=268, uploader="Arijit Singh - Topic")
    video = Track(id="vid1", title="Kesariya (Official Video)", duration=268, uploader="Sony Music India")
    reup = Track(id="up1", title="Kesariya full song", duration=270, uploader="Random Uploads")

    order = rank("kesariya", [reup, video, official])
    assert order[0].id == "off1"


def test_covers_and_karaoke_are_demoted_unless_asked_for():
    real = Track(id="real", title="Kesariya", duration=268, uploader="Sony Music")
    cover = Track(id="cover", title="Kesariya cover", duration=268, uploader="Sony Music")

    assert rank("kesariya", [cover, real])[0].id == "real"
    assert rank("kesariya cover", [real, cover])[0].id == "cover"


def test_shorts_and_loops_lose_to_a_song():
    song = Track(id="song", title="Kesariya", duration=268, uploader="Sony")
    short = Track(id="short", title="Kesariya", duration=18, uploader="Clips")
    loop = Track(id="loop", title="Kesariya 10 hours", duration=36000, uploader="Loops")

    order = rank("kesariya", [short, loop, song])
    assert order[0].id == "song"


def test_the_same_song_from_two_channels_appears_once():
    first = Track(id="one", title="Kesariya", duration=268, uploader="Sony Music")
    again = Track(id="two", title="Kesariya", duration=268, uploader="Sony Music India")

    order = rank("kesariya", [first, again])
    assert [item.id for item in order] == ["one"]


def test_artist_match_breaks_a_title_tie():
    right = Track(id="right", title="Tum Hi Ho", duration=260, uploader="Arijit Singh")
    wrong = Track(id="wrong", title="Tum Hi Ho", duration=260, uploader="Cover Band")

    assert rank("tum hi ho arijit singh", [wrong, right])[0].id == "right"


# ── relaxed retry: the query people actually typed ────────────────────────
def test_a_held_letter_accent_or_bracketed_credit_is_relaxed():
    from vyron.core.search import relax_query

    assert relax_query("Kesariyaa") == "Kesariya"
    assert relax_query("Kesariyā") == "Kesariya"
    assert relax_query("Tum Hi Ho (Official Video)") == "Tum Hi Ho"
    assert relax_query("believerr") == "believer"


def test_a_real_word_is_never_damaged_by_relaxing():
    from vyron.core.search import relax_query

    # Nothing to strip: the retry must not fire, or "good" would become "god".
    assert relax_query("good") == ""
    assert relax_query("seem") == ""
    assert relax_query("Arijit Singh") == ""
    assert relax_query("") == ""


def test_search_retries_once_with_the_relaxed_spelling(monkeypatch):
    """An empty first pass retries the relaxed spelling; a second miss still ends."""
    import asyncio
    from types import SimpleNamespace

    from vyron.core import search as search_mod

    asked: list[str] = []

    async def fake_meta(self, query, limit):
        asked.append(query)
        return [{"id": "hit", "title": "Kesariya"}] if query == "Kesariya" else []

    async def fake_extract(self, query, **kwargs):
        return {"entries": []}

    async def no_sources(query, count, settings=None):
        return []

    engine = search_mod.YouTube.__new__(search_mod.YouTube)
    engine.settings = SimpleNamespace(search_results=8, music_sources="on")
    monkeypatch.setattr(search_mod.YouTube, "_ytmusic_search", fake_meta)
    monkeypatch.setattr(search_mod.YouTube, "_async_extract", fake_extract)
    monkeypatch.setattr(search_mod.YouTube, "_track_from_entry",
                        lambda self, entry, requester=(0, ""): Track(**{"id": entry["id"], "title": entry["title"]}))
    monkeypatch.setattr(search_mod.sources, "fallback_search", no_sources)

    found = asyncio.run(engine.search("Kesariyaa"))
    assert [track.id for track in found] == ["hit"]
    assert asked == ["Kesariyaa", "Kesariya"]
