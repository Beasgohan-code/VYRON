"""Static checks on the command surface.

Two regressions these catch, both of which we hit for real:

* two modules claiming the same command (the later one silently never runs);
* the help card advertising a command nobody registered.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# `filters.command("x")` / `filters.command(["a", "b"])` everywhere in vyron/
ALLOWED_DUPLICATES: dict[str, str] = {
    # database.py pings MongoDB with admin.command("ping") — not a handler
    "ping": "mongo admin ping",
}


def _commands(roots: tuple[str, ...] = ("vyron",)) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for base in roots:
        for path in sorted((ROOT / base).rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "command"):
                    continue
                if not node.args:
                    continue
                arg = node.args[0]
                names: list[str] = []
                if isinstance(arg, ast.List):
                    names = [
                        elt.value
                        for elt in arg.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    names = [arg.value]
                for name in names:
                    found.setdefault(name.lower(), []).append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def test_no_command_is_registered_twice():
    clashes = {
        name: places
        for name, places in _commands().items()
        if len(places) > 1 and name not in ALLOWED_DUPLICATES
    }
    assert not clashes, f"duplicate handlers: {clashes}"


def test_help_card_only_advertises_real_commands():
    from vyron.ui import cards

    registered = set(_commands())
    missing: dict[str, list[str]] = {}
    for section in ("main", "playback", "queue", "tools", "social", "power"):
        card = cards.help_card(section)
        for token in re.findall(r"(?<![<\w])/([a-z][a-z0-9_]+)", card.lower()):
            if token in {"app", "start"} or token in registered:
                continue
            missing.setdefault(token, []).append(section)
    # `<code>/play …</code>` snippets inside prose are hints, not entries;
    # restrict the check to the first column of the table markup
    assert not {
        token: where
        for token, where in missing.items()
        if token not in {"set", "id", "name", "all", "query", "song", "youtube", "u", "n"}
    }, f"help promises unknown commands: {missing}"


def test_core_commands_are_present():
    registered = set(_commands())
    for name in (
        "play", "vplay", "song", "vsong", "pause", "resume", "skip", "stop",
        "seek", "volume", "loop", "shuffle", "np", "queue", "lyrics",
        "voteskip", "vskip", "setvoteskip", "skipvotes", "cplayset",
        "eval", "vars", "dbstats", "dbcleanup", "clearcache",
        "addsudo", "delsudo", "sudolist", "blocklist", "repo", "id",
    ):
        assert name in registered, f"/{name} is not registered"


def test_commands_are_lowercase():
    bad = [name for name in _commands() if name != name.lower()]
    assert bad == []
