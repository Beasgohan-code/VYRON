"""Tests for moderation, locks and effects (pure logic only)."""
from __future__ import annotations

import pytest

pytest.importorskip("pyrogram")

from vyron.core import effects
from vyron.core.chatcfg import DEFAULTS, render


# ── effects ─────────────────────────────────────────────────────────────────
def test_effect_resolution_and_cap():
    assert effects.resolve(["bass", "bass", "nightcore"]) == ["bass", "nightcore"]
    assert len(effects.resolve(list(effects.EFFECTS))) == effects.MAX_ACTIVE
    assert effects.resolve(["nope"]) == []


def test_ffmpeg_filter_chain():
    assert effects.ffmpeg_filter([]) is None
    chain = effects.ffmpeg_filter(["bass", "treble"])
    assert chain == f"{effects.EFFECTS['bass'].filters},{effects.EFFECTS['treble'].filters}"


def test_ffmpeg_parameters_with_seek():
    params = effects.ffmpeg_parameters(["bass"], seek=30)
    assert params.startswith("-ss 30")
    assert '-af "' in params
    assert effects.ffmpeg_parameters([]) is None


def test_every_effect_actually_does_something():
    """A no-op filter is worse than a missing one: it lies on the panel.

    `reverb` used to be `afreqshift=shift=0`, which changes nothing at all.
    """
    for name, effect in effects.EFFECTS.items():
        assert effect.filters.strip(), f"{name} has an empty filter chain"
        assert "shift=0" not in effect.filters.replace(" ", ""), (
            f"{name} is a no-op filter"
        )
        assert effect.label and effect.note


def test_reverb_has_a_real_tail():
    chain = effects.ffmpeg_filter(["reverb"])
    assert chain and chain.startswith("aecho=")
    delays = chain.split(":")[2].split("|")
    assert all(float(d) > 0 for d in delays)


def test_parse_effects():
    accepted, rejected = effects.parse("bass, nightcore nonsense")
    assert accepted == ["bass", "nightcore"] and rejected == ["nonsense"]
    assert effects.parse("off") == ([], [])
    assert effects.labels(["bass"]) == effects.EFFECTS["bass"].label
    assert effects.labels([]) == "off"


# ── chat config helpers ────────────────────────────────────────────────────
def test_placeholder_rendering():
    out = render("hi {mention} in {chat} ({count})", mention="@bob", chat="Group", count=7)
    assert out == "hi @bob in Group (7)"
    assert "{missing}" in render("keep {missing}", other="x")
    assert render("", mention="x") == ""


def test_defaults_shape():
    assert "locks" in DEFAULTS and "flood" in DEFAULTS
    assert DEFAULTS["locks"]["media"] is False
    assert DEFAULTS["warn_limit"] == 3


# ── locks panel ────────────────────────────────────────────────────────────
def test_locks_panel_renders():
    from vyron.modules.locks import LOCK_LABELS, locks_panel

    panel = locks_panel(
        {"media": True, "links": False},
        {"enabled": True, "limit": 7, "window": 9},
    )
    assert "<tg-button" in panel
    assert "🔒 locked" in panel and "🔓 open" in panel
    assert "v:lock:media" in panel and "v:lock:flood" in panel
    assert set(LOCK_LABELS) >= {"media", "links", "forwards"}


def test_effects_panel_renders():
    from vyron.modules.effects_cmd import panel

    panel_markup = panel(["bass"])
    assert "<tg-button" in panel_markup and "v:fx:bass" in panel_markup
    assert "v:fx:off" in panel_markup


# ── stream-end de-duplication ───────────────────────────────────────────────
def test_duplicate_stream_end_is_ignored_for_the_same_track():
    from vyron.core.player import Player
    from vyron.core.queue import ChatState, Track

    state = ChatState(chat_id=-100)
    state.current = Track(id="abc12345678", title="Believer", duration=200)
    state.is_video = False

    assert Player.duplicate_stream_end(state, 1000.0) is False
    # both the audio and the video stream report "ended" for a video track;
    # a repeat within the window must not skip the track that just started
    assert Player.duplicate_stream_end(state, 1000.4) is True

    state.current = Track(id="def12345678", title="Thunder", duration=180)
    assert Player.duplicate_stream_end(state, 1001.0) is False

    # a genuinely later end for the same track (after the window) is honoured
    state.current = Track(id="abc12345678", title="Believer", duration=200)
    assert Player.duplicate_stream_end(state, 1009.0) is False


def test_reset_stream_clears_end_state():
    from vyron.core.queue import ChatState, Track

    state = ChatState(chat_id=-100)
    state.current = Track(id="abc12345678", title="Believer")
    state.ended_track = "abc12345678:a"
    state.ended_at = 5.0
    state.reset_stream()
    assert state.ended_track == "" and state.ended_at == 0.0
