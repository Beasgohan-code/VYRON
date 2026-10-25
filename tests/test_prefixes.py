"""Command prefixes — `/play`, `!play`, `.play`, `?play`, `#play`, …

The filter is the gateway for every command in the package, so it is tested at
the same level pyrogram uses it: a real CommandFilter object, a fake client and
a message. No network, no dispatcher.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("pyrogram")

from vyron.utils import commands


class Client:
    me = SimpleNamespace(username="VyronMusicBot")


def matches(filter_obj, text: str, *, caption: str | None = None) -> bool:
    message = SimpleNamespace(text=text, caption=caption, command=None)

    async def run():
        return await filter_obj(Client(), message)

    return asyncio.run(run())


# ── the configured set ─────────────────────────────────────────────────────
def test_the_default_set_covers_what_people_actually_type():
    assert commands.prefixes() == ("/", "!", ".", "?", "#", "%", "$", "&", "~")


def test_slash_is_always_present_even_if_the_env_forgets_it():
    commands.override("!.?")
    assert commands.prefixes()[0] == "/"
    assert {"!", ".", "?"} <= set(commands.prefixes())


def test_an_env_list_is_normalised():
    commands.override(" ! , .   slash , dot ")
    assert commands.prefixes() == ("/", "!", ".")


def test_prefixes_can_be_turned_off():
    commands.override("off")
    assert commands.prefixes() == ("/",)


def test_an_empty_entry_enables_prefixless_commands():
    commands.override("/,")
    assert "" in commands.prefixes()


def test_an_escaped_prefix_is_accepted():
    commands.override(r"\,\./")
    assert commands.prefixes() == ("/", ",", ".")


def test_describe_is_human_readable():
    assert commands.describe().split() == list(commands.prefixes())


# ── the filter itself ──────────────────────────────────────────────────────
@pytest.mark.parametrize("prefix", ["/", "!", ".", "?", "#", "%", "$", "&", "~"])
def test_every_default_prefix_starts_the_same_command(prefix):
    play = commands.cmd(["play"])
    assert matches(play, f"{prefix}play kesariya")
    assert matches(play, f"{prefix}play")


def test_arguments_and_mentions_still_parse():
    play = commands.cmd(["play"])
    assert matches(play, "/play@VyronMusicBot arijit singh")
    assert matches(play, "!play lofi beats")


def test_a_caption_is_a_command_too():
    play = commands.cmd(["play"])
    assert matches(play, None, caption=".play this one")


@pytest.mark.parametrize("text", ["please play", ". play", "..play", ".playlist x", "/paused", "#playlist"])
def test_near_misses_do_not_fire(text):
    play = commands.cmd(["play"])
    assert not matches(play, text)


def test_a_custom_prefix_list_overrides_the_default():
    only = commands.cmd(["play"], prefixes=[":"])
    assert matches(only, ":play")
    assert not matches(only, "/play")


# ── the surface is registered through it ───────────────────────────────────
def test_every_handler_uses_the_shared_filter():
    """A stray `filters.command` would silently ignore every other prefix."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "vyron" / "modules"
    offenders = [
        path.name
        for path in root.glob("*.py")
        if "filters.command(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_command_names_still_resolve_through_the_helper():
    from vyron.core.commandlist import command_names

    names = set(command_names())
    assert {"play", "queue", "np", "settings"} <= names


def test_the_help_card_advertises_the_prefixes():
    from vyron.ui import cards

    card = cards.help_card("main")
    assert "prefixes" in card.lower()
    for prefix in ("/play", "!play", ".play", "?play", "#play"):
        assert prefix in card


def test_a_custom_prefix_set_flows_into_the_help_card():
    from vyron.ui import cards

    commands.override("/:")
    card = cards.help_card("main")
    assert "/play" in card and ":play" in card
    assert "!play" not in card


def test_all_and_off_keywords():
    from vyron.utils.commands import DEFAULT_PREFIXES, _parse

    assert _parse("all") == DEFAULT_PREFIXES
    assert _parse("defaults") == DEFAULT_PREFIXES
    assert _parse("off") == ("/",)
    assert _parse("slash only") == ("/",)
