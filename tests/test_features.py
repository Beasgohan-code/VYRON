"""Tests for the Videl/Fallen-derived feature set (pure logic only)."""
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
