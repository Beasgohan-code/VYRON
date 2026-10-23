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


def test_the_settings_panel_reports_this_chat_not_the_defaults(monkeypatch):
    """`/settings` used to build its own partial dict: Language always said
    English and Artwork was missing entirely."""
    import asyncio

    from vyron.core import chatcfg, queue
    from vyron.ui import cards, panels

    stored = {(-100, "poster"): False, (-100, "thumbnail"): "art-id", (-100, "lang"): "hi"}

    async def fake_get(chat_id, key, default=None, **_kwargs):
        return stored.get((int(chat_id), key), default)

    monkeypatch.setattr(chatcfg, "get", fake_get)
    state = queue.ChatState(chat_id=-100, volume=45)
    state.autoplay = False

    cfg = asyncio.run(panels.chat_panel(-100, state))

    assert cfg["volume"] == 45
    assert cfg["poster"] is False
    assert cfg["thumbnail"] is True
    assert cfg["lang"] == "hi"

    text = cards.settings_card(cfg, "Room")
    assert "Volume" in text and "45%" in text
    assert "Artwork" in text and "Custom" in text
    assert "\u0939\u093f\u0928\u094d\u0926\u0940" in text or "Hindi" in text


def test_a_live_stream_is_not_described_as_zero_seconds():
    """A live set has no length; `0:00` next to it reads like a broken track."""
    from vyron.core.queue import Track
    from vyron.ui.progress import length_label

    assert length_label(Track(id="x", title="Radio", duration=0)) == "—"
    assert length_label(Track(id="x", title="Radio", duration=0, is_live=True)) == "live"
    assert length_label(Track(id="x", title="Song", duration=205)) == "3:25"

    # the flag has to survive a queue save/restore, or a restart would turn a
    # live stream back into a zero-length song
    restored = Track.from_dict(Track(id="x", title="Radio", is_live=True).to_dict())
    assert restored.is_live is True
