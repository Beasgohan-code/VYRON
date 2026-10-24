"""UI lanes — the rich card, the classic (old) UI, and the fallback between them.

The bot ships two interfaces. The rich lane is prettier; the classic one is the
old plain-HTML look that always works. `/uicheck` and the boot probe exist so a
deployment can never end up on a lane that renders an empty `/start` card.
"""
from __future__ import annotations

import asyncio

from vyron.modules import uistyle
from vyron.ui import rich


def test_probe_reports_both_lanes():
    report = uistyle.probe()

    assert set(report) >= {"style", "rich_api", "rich_ok", "classic_ok", "rich_chars", "classic_chars", "buttons", "ok"}
    assert report["rich_chars"] > 0
    assert report["classic_chars"] > 0
    assert report["buttons"] >= 1
    assert report["ok"] is True


def test_verify_switches_to_the_old_ui_when_the_rich_card_is_empty(monkeypatch):
    rich.set_rich_enabled(True)
    monkeypatch.setattr(rich, "RICH_AVAILABLE", False)
    monkeypatch.setattr(uistyle, "probe", lambda: {
        "style": "rich",
        "rich_api": False,
        "rich_ok": False,
        "classic_ok": True,
        "rich_chars": 0,
        "classic_chars": 700,
        "buttons": 0,
        "ok": False,
    })

    report = asyncio.run(uistyle.verify())

    assert report["fell_back"] is True
    assert rich.rich_enabled() is False
    assert uistyle.current() == "classic"


def test_verify_leaves_a_healthy_deployment_alone():
    rich.set_rich_enabled(True)
    report = asyncio.run(uistyle.verify())

    assert not report.get("fell_back")
    assert rich.rich_enabled() is True
    rich.set_rich_enabled(None)


def test_style_aliases_still_resolve():
    assert asyncio.run(uistyle.set_style("old")) == "classic"
    assert asyncio.run(uistyle.set_style("rich")) == "rich"
    rich.set_rich_enabled(None)
