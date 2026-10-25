# ---------------------------------------------------------------------------
#  VYRON — one command filter, many prefixes
# ---------------------------------------------------------------------------
# Telegram users type `/play`; Discord users type `!play`; people who came from
# other bots type `.play` or `?play`. All of them mean the same thing, and
# making somebody learn our punctuation is a bad reason to lose a listener.
#
# So every handler in the package is registered through `cmd(...)` instead of
# `filters.command(...)` directly, and the prefix set lives in one place:
#
#   COMMAND_PREFIXES=/!.?#          (env, comma or space separated)
#   COMMAND_PREFIXES=off            → slash only
#   COMMAND_PREFIXES=all            → the defaults below
#
# Notes that matter:
#   * a prefix only matches at the *start* of a message, and only when a real
#     command name follows — ". play" is not a command, ".play" is.
#   * `/` is always included, even if the env forgets it: Telegram's own UI
#     and every client's autocomplete send it.
#   * `""` (an empty entry) enables prefix-less commands, e.g. `play x`; it is
#     opt-in because a group with members named "play" gets weird fast.
from __future__ import annotations

import re

from pyrogram import filters

from vyron.config import settings

# Order is only cosmetic (the menus show the first one), but `/` first matters:
# it is what every Telegram client autocompletes.
DEFAULT_PREFIXES = ("/", "!", ".", "?", "#", "%", "$", "&", "~")
_ALIASES = {"slash": "/", "bang": "!", "dot": ".", "question": "?", "hash": "#", "none": ""}

# A runtime override (tests, and an owner who wants to change the set without a
# redeploy). `None` means "read the environment".
_override: tuple[str, ...] | None = None


def override(value: str | tuple[str, ...] | None) -> None:
    """Force the prefix set, or pass ``None`` to go back to the environment."""
    global _override
    if value is None:
        _override = None
    elif isinstance(value, str):
        _override = _parse(value)
    else:
        _override = tuple(value)


def configured() -> tuple[str, ...]:
    """The configured prefixes, normalised, always containing `/`."""
    if _override is not None:
        return _override
    raw = (getattr(settings, "command_prefixes", "") or "").strip()
    return _parse(raw)


def _parse(raw: str) -> tuple[str, ...]:
    """Turn ``!/./?`` or ``! . ?`` or ``slash,dot`` into a clean tuple."""
    raw = (raw or "").strip()
    if not raw:
        return DEFAULT_PREFIXES
    if raw.lower() in {"off", "none", "no", "slash only"}:
        return ("/",)
    if raw.lower() in {"all", "default", "defaults", "auto"}:
        return DEFAULT_PREFIXES

    # A backslash lets somebody use a character that is also a separator
    # (`\\,` is a comma prefix). Protect those, then split.
    escaped: list[str] = []

    def _protect(match) -> str:
        escaped.append(match.group(1))
        return f"\x00{len(escaped) - 1}\x00"

    work = re.sub(r"\\(.)", _protect, raw)

    tokens: list[str] = []
    chunks = work.split(",")
    for chunk in chunks:
        pieces = chunk.split()
        if not pieces and len(chunks) > 1:
            pieces = [""]  # a comma with nothing after it: prefix-less
        tokens.extend(pieces)

    parts: list[str] = []
    for token in tokens:
        token = re.sub(
            r"\x00(\d+)\x00", lambda m: escaped[int(m.group(1))], token
        )
        if token == "":
            if "" not in parts:
                parts.append("")
            continue
        lowered = token.lower()
        if lowered in _ALIASES:
            token = _ALIASES[lowered]
        elif len(token) > 1:
            # `!.?#` is a list of prefixes, not one long prefix
            for char in token:
                char = _ALIASES.get(char.lower(), char)
                if char not in parts:
                    parts.append(char)
            continue
        if token not in parts:
            parts.append(token)

    parts = [part for part in parts if part != "/"]
    return ("/", *parts)


def describe() -> str:
    """A human list for the help card and `/prefixes` (`/  !  .  ?`)."""
    return "  ".join(prefix or "(none)" for prefix in configured())


def cmd(
    names: str | list[str],
    *,
    prefixes: str | list[str] | None = None,
    case_sensitive: bool = False,
):
    """``filters.command`` with VYRON's prefix set."""
    chosen = prefixes if prefixes is not None else list(configured())
    return filters.command(names, prefixes=chosen, case_sensitive=case_sensitive)


# Readable alias: `commands.prefixes()` reads better at a call site than
# `commands.configured()`, and neither shadows the `cmd(prefixes=…)` argument.
prefixes = configured


__all__ = ["DEFAULT_PREFIXES", "cmd", "configured", "describe", "override", "prefixes"]
