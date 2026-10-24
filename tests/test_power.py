"""Vote-skip, owner console helpers and help surface (no Telegram, no network)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from vyron.core.votes import DEFAULT_VOTES, MAX_VOTES, VoteBoard, VoteTally, clamp_votes
from vyron.modules.power import mask, run_eval, var_rows
from vyron.ui import cards


# ── threshold parsing ──────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "raw,expected",
    [
        (3, 3),
        ("5", 5),
        ("0", 0),          # disabled
        ("-2", 0),
        ("999", MAX_VOTES),
        ("abc", DEFAULT_VOTES),
        (None, DEFAULT_VOTES),
    ],
)
def test_clamp_votes(raw, expected):
    assert clamp_votes(raw) == expected


# ── tally semantics ────────────────────────────────────────────────────────
def test_vote_tally_counts_until_threshold():
    tally = VoteTally()
    tally.bind("youtube:abc", 3)
    assert tally.enabled and tally.remaining == 3

    assert tally.cast(1) == "voted"
    assert tally.cast(1) == "duplicate"      # same user cannot vote twice
    assert tally.remaining == 2

    assert tally.cast(2) == "voted"
    assert tally.cast(3) == "passed"
    assert tally.count == 3

    tally.reset()
    assert tally.count == 0 and tally.remaining == 3


def test_vote_tally_disabled_when_zero():
    tally = VoteTally()
    tally.bind("track", 0)
    assert not tally.enabled
    assert tally.cast(7) == "disabled"
    assert tally.remaining == 0


def test_vote_tally_resets_when_the_track_changes():
    tally = VoteTally()
    tally.bind("track-a", 2)
    tally.cast(1)
    assert tally.count == 1

    tally.bind("track-b", 2)     # next song → old votes must not carry over
    assert tally.count == 0

    tally.bind("track-b", 5)     # threshold change also clears
    tally.cast(1)
    tally.bind("track-b", 4)
    assert tally.count == 0


def test_vote_tally_single_voter_threshold():
    tally = VoteTally()
    tally.bind("x", 1)
    assert tally.cast(9) == "passed"


def test_vote_board_is_per_chat():
    board = VoteBoard()
    board.get(-100).bind("a", 2)
    board.get(-200).bind("b", 2)
    board.get(-100).cast(1)

    assert board.get(-100).count == 1
    assert board.get(-200).count == 0

    board.drop(-100)
    assert board.get(-100).count == 0


# ── masking / vars ─────────────────────────────────────────────────────────
def test_mask_never_leaks_secrets():
    assert mask("") == "—"
    assert mask("123456789:AAHsecret-token-value") == "123456" + "•" * 8
    assert set(mask("supersecret").replace("supers", "")) == {"•"}
    assert mask("abc") == "•••"


def test_var_rows_reads_env_and_masks(monkeypatch):
    monkeypatch.setenv("BOT_USERNAME", "VyronMusicBot")
    monkeypatch.setenv("PREMIUM_EMOJI", "true")
    monkeypatch.setenv("WEBAPP_URL", "https://vyron.example")
    rows = var_rows()
    joined = "\n".join(f"{label} {value}" for label, value in rows)
    assert "VyronMusicBot" in joined
    assert "vyron.example" not in joined          # URL is masked like a secret
    assert "•" in joined


# ── eval ───────────────────────────────────────────────────────────────────
def test_run_eval_returns_output_and_errors():
    client = SimpleNamespace()
    message = SimpleNamespace()

    async def scenario():
        printed = await run_eval("print('hello from eval')", client, message)
        assert "hello from eval" in printed
        assert "eval" in printed.lower()

        expression = await run_eval("return 6 * 7", client, message)
        assert "42" in expression

        broken = await run_eval("raise ValueError('boom')", client, message)
        assert "ValueError" in broken and "boom" in broken

    asyncio.run(scenario())


# ── help surface ───────────────────────────────────────────────────────────
def test_help_has_every_section_rendered():
    for section in ("main", "playback", "queue", "tools", "social", "power"):
        card = cards.help_card(section)
        assert card and "<table" in card
    assert "voteskip" in cards.help_card("social")
    assert "eval" in cards.help_card("power")
    # unknown sections fall back to the basics
    fallback = cards.help_card("nope")
    assert "play" in fallback


# ── streaming only: no silent file fallback ───────────────────────────────
def test_play_refuses_without_a_voice_engine(tmp_path, monkeypatch):
    """No STRING_SESSION → /play explains itself and sends nothing."""
    from vyron import runtime as runtime_module
    from vyron.core.queue import Track
    from vyron.modules import play as play_module

    audio = tmp_path / "song.m4a"
    audio.write_bytes(b"\x00" * 64)

    sent: dict = {}
    edits: list = []

    class FakeDownloader:
        async def audio(self, track):  # pragma: no cover - must not be called
            sent["download"] = True
            return audio

        async def video(self, track):  # pragma: no cover
            return audio

    class FakeClient:
        async def send_audio(self, *args, **kwargs):  # pragma: no cover
            sent["audio"] = True

        async def send_video(self, *args, **kwargs):  # pragma: no cover
            sent["video"] = True

        async def edit_message_text(self, chat_id, message_id, text, **kwargs):
            edits.append(text)
            return SimpleNamespace(id=message_id)

    runtime = runtime_module.runtime
    monkeypatch.setattr(runtime, "calls", None)
    monkeypatch.setattr(runtime, "downloader", FakeDownloader())
    monkeypatch.setattr(runtime, "player", None)

    track = Track(
        id="abc123",
        title="Test Song",
        duration=120,
        uploader="VYRON",
        url="https://youtu.be/abc123",
        source="youtube",
    )

    outcome = asyncio.run(
        play_module.begin(FakeClient(), -100, track, status_id=7, reply_to=5)
    )

    assert outcome == "error"
    assert "audio" not in sent and "video" not in sent and "download" not in sent
    assert edits and "STRING_SESSION" in edits[-1]


def test_song_command_still_sends_a_file(tmp_path, monkeypatch):
    """Files are an explicit command now, not a fallback."""
    from vyron.core.queue import Track
    from vyron.modules import play as play_module

    audio = tmp_path / "song.m4a"
    audio.write_bytes(b"\x00" * 64)
    sent: dict = {}

    class FakeDownloader:
        async def audio(self, track):
            return audio

        async def video(self, track):  # pragma: no cover
            return audio

    class FakeClient:
        async def send_audio(self, chat_id, path, **kwargs):
            sent["audio"] = (chat_id, path, kwargs)
            return SimpleNamespace(id=1)

        async def send_video(self, *args, **kwargs):  # pragma: no cover
            return None

        async def delete_messages(self, *args, **kwargs):
            return True

    from vyron import runtime as runtime_module

    monkeypatch.setattr(runtime_module.runtime, "downloader", FakeDownloader())
    monkeypatch.setattr(runtime_module.runtime, "storage", None)

    track = Track(id="abc", title="Test Song", duration=90, uploader="VYRON")
    asyncio.run(play_module.deliver(FakeClient(), -100, track, False, reply_to=5))

    assert sent["audio"][0] == -100
    assert sent["audio"][2]["reply_to_message_id"] == 5


def test_play_streams_when_the_engine_exists(monkeypatch):
    from vyron import runtime as runtime_module
    from vyron.core.queue import Track
    from vyron.modules import play as play_module

    class FakePlayer:
        def __init__(self):
            self.calls = []

        async def enqueue(self, chat_id, track, *, video=False, play_now=False):
            self.calls.append((chat_id, track.id, video, play_now))
            return 1

    runtime = runtime_module.runtime
    player = FakePlayer()
    monkeypatch.setattr(runtime, "calls", SimpleNamespace())
    monkeypatch.setattr(runtime, "player", player)

    track = Track(id="xyz", title="Stream Me", duration=200, url="https://youtu.be/xyz", source="youtube")
    outcome = asyncio.run(play_module.begin(SimpleNamespace(), -200, track, video=True))

    assert outcome == "streamed"
    assert player.calls == [(-200, "xyz", True, True)]
