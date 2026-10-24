"""Autoplay — title hygiene, the mood/language lane, and de-duplication.

Autoplay is the feature people notice only when it is wrong: the same song
twice, a karaoke upload, a language switch mid-queue. These tests pin the
rules that keep it listenable without touching the network.
"""
from __future__ import annotations

import asyncio

from vyron.core import autoplay as auto
from vyron.core.queue import Track


def test_clean_title_strips_the_noise_youtubers_add():
    cases = {
        "Kesariya (Official Video) | Brahmastra": "Kesariya",
        "Tum Hi Ho - Official Music Video": "Tum Hi Ho",
        "Lofi Mix [HD] (Lyrics)": "Lofi Mix",
        "Song ft. Somebody Else": "Song",
        "  Simple  Title  ": "Simple Title",
    }
    for raw, expected in cases.items():
        assert auto.clean_title(raw) == expected, raw


def test_same_song_matches_reuploads_but_not_different_tracks():
    assert auto.same_song("Kesariya (Official Video)", "Kesariya")
    assert auto.same_song("Tum Hi Ho", "tum hi ho - official audio")
    assert not auto.same_song("Kesariya", "Kesariya Lofi Remix Extended")


def test_usable_rejects_shorts_karaoke_and_hour_long_mixes():
    assert auto.usable("Kesariya", 240)
    assert not auto.usable("Kesariya", 30)          # a short
    assert not auto.usable("Kesariya", 4000)        # an hour-long loop
    assert not auto.usable("Kesariya karaoke", 240)
    assert not auto.usable("Minecraft gameplay", 240)


def test_build_queries_puts_the_lane_first_and_never_repeats():
    queries = auto.build_queries("Kesariya (Official Video)", mood="chill", language="hindi", artist="Arijit Singh")
    assert queries[0] == "Kesariya hindi songs"
    assert queries[1] == "Kesariya lofi chill relaxing"
    assert "Kesariya Arijit Singh" in queries
    assert len(queries) == len(set(q.lower() for q in queries))


def test_build_queries_without_a_seed_still_offers_something():
    queries = auto.build_queries("", mood="party", language="")
    assert queries == ["party dance hits"]


def test_pick_skips_ids_and_titles_already_played():
    played = [Track(id="aaaa1111111", title="Kesariya", duration=240, uploader="x")]
    candidates = [
        Track(id="aaaa1111111", title="Kesariya (Official Video)", duration=240, uploader="x"),
        Track(id="bbbb2222222", title="Kesariya (Lyrics)", duration=240, uploader="y"),
        Track(id="cccc3333333", title="Raata Lambiyo", duration=230, uploader="z"),
    ]
    chosen = auto.pick(candidates, played=played, seed_title="Kesariya (Official Video)")
    assert chosen is not None and chosen.id == "cccc3333333"


def test_pick_returns_none_when_everything_is_a_repeat():
    played = [Track(id="aaaa1111111", title="Kesariya", duration=240, uploader="x")]
    candidates = [Track(id="aaaa1111111", title="Kesariya", duration=240, uploader="x")]
    assert auto.pick(candidates, played=played) is None


class _YouTube:
    def __init__(self, results):
        self.results = results
        self.queries: list[str] = []

    async def search(self, query, limit=5, requester=(0, "")):
        self.queries.append(query)
        return list(self.results)


def test_next_track_marks_the_request_as_autoplay():
    youtube = _YouTube([Track(id="fresh000001", title="Somewhere New", duration=200, uploader="x")])
    seed = Track(id="seed0000001", title="Kesariya (Official Video)", duration=240, uploader="Arijit")

    picked = asyncio.run(auto.next_track(youtube, seed, language="hindi"))

    assert picked is not None and picked.requested_name == "autoplay"
    assert youtube.queries[0].startswith("Kesariya hindi")


def test_next_track_gives_up_quietly_when_search_fails():
    class Broken:
        async def search(self, *args, **kwargs):
            raise RuntimeError("upstream down")

    seed = Track(id="seed0000001", title="Song", duration=200, uploader="x")
    assert asyncio.run(auto.next_track(Broken(), seed, mood="chill")) is None


def test_describe_reads_like_a_sentence():
    assert auto.describe("chill", "hindi") == "lofi chill relaxing · hindi songs"
    assert auto.describe("", "") == ""


def test_pick_rotates_the_artist_when_it_can():
    candidates = [
        Track(id="aaaa1111111", title="Tum Hi Ho", duration=240, uploader="Arijit Singh"),
        Track(id="bbbb2222222", title="Kesariya", duration=240, uploader="Arijit Singh"),
        Track(id="cccc3333333", title="Raata Lambiyo", duration=230, uploader="Shreya Ghoshal"),
        Track(id="dddd4444444", title="Channa Mereya", duration=250, uploader="Pritam"),
    ]
    for _ in range(20):
        chosen = auto.pick(
            candidates,
            seed_title="Some Arijit song",
            seed_artist="Arijit Singh",
        )
        assert chosen is not None
        assert chosen.uploader != "Arijit Singh"


def test_pick_falls_back_to_the_same_artist_when_that_is_all_there_is():
    candidates = [
        Track(id="aaaa1111111", title="Tum Hi Ho", duration=240, uploader="Arijit Singh"),
        Track(id="bbbb2222222", title="Kesariya", duration=240, uploader="Arijit Singh"),
    ]
    chosen = auto.pick(candidates, seed_title="x", seed_artist="Arijit Singh")
    assert chosen in candidates


def test_soft_shuffle_keeps_every_track():
    pool = [Track(id=f"id{i:09d}", title=f"t{i}", duration=200) for i in range(7)]
    shuffled = auto._soft_shuffle(pool, group=3)
    assert sorted(t.id for t in shuffled) == sorted(t.id for t in pool)
