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
