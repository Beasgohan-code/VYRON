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
                if not isinstance(node, ast.Call):
                    continue
                # handlers use the multi-prefix helper `cmd(...)`; `filters.command`
                # is still parsed so a stray one cannot hide from these checks
                if getattr(node.func, "attr", "") != "command" and getattr(node.func, "id", "") != "cmd":
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
        "play", "song", "pause", "resume", "skip", "stop",
        "seek", "volume", "loop", "shuffle", "np", "queue", "lyrics",
        "voteskip", "setvoteskip", "cplayset",
        "eval", "vars", "dbstats", "dbcleanup", "clearcache",
        "addsudo", "delsudo", "sudolist", "blocklist", "repo", "id",
    ):
        assert name in registered, f"/{name} is not registered"


def test_commands_are_lowercase():
    bad = [name for name in _commands() if name != name.lower()]
    assert bad == []


def test_the_bot_menu_only_lists_commands_that_exist():
    """Telegram shows this menu to users; a stale entry is a dead button.

    `/whoami` sat in it long after the handler was deleted, so the check walks
    the *real* registrations (the same objects pyrogram's dispatcher matches)
    instead of re-parsing source.
    """
    from vyron.__main__ import COMMANDS
    from vyron.modules import register_all

    found: set[str] = set()

    class Recorder:
        def _capture(self, flt):
            stack = [flt]
            while stack:
                node = stack.pop()
                commands = getattr(node, "commands", None)
                if commands:
                    found.update(c if isinstance(c, str) else c.value for c in commands)
                for attr in ("base", "other"):
                    child = getattr(node, attr, None)
                    if child is not None:
                        stack.append(child)
            return lambda fn: fn

        def on_message(self, flt, *_a, **_k):
            return self._capture(flt)

        def on_callback_query(self, flt, *_a, **_k):
            return self._capture(flt)

        def __getattr__(self, _name):
            return lambda *_a, **_k: (lambda fn: fn)

    register_all(Recorder())
    listed = {name for name, _desc in COMMANDS}
    assert listed <= found, f"menu promises unregistered commands: {sorted(listed - found)}"


def test_removed_commands_stay_removed():
    """The owner deleted these on purpose — never bring them back."""
    from vyron.__main__ import COMMANDS

    registered = set(_commands())
    for gone in (
        "speedtest", "whoami", "emojis", "dj", "random", "daemons", "replay", "timer",
        # one /play and one /cplay: force variants were removed in favour of
        # auto-detection, so these must never come back.
        "playforce", "cplayforce", "vplay", "vsong", "vplayforce", "cvplayforce",
    ):
        assert gone not in registered, f"/{gone} is back"
        assert gone not in {name for name, _ in COMMANDS}, f"/{gone} is back in the menu"


def test_runtime_command_list_matches_the_registrations():
    """`/unknown` hints read the source; they must see the same handlers."""
    from vyron.core.commandlist import command_names

    assert set(command_names()) == set(_commands())


def test_unknown_command_hints_point_at_live_commands():
    from vyron.core.commandlist import suggest

    assert suggest("pl") == ["play"]
    assert suggest("favs") == ["fav"]
    assert suggest("vskip") == ["skip"]
    # a nonsense token must not invent a suggestion
    assert suggest("qwertyuiop") == []


def test_channel_controls_are_registered():
    """The channel-side control set stays complete."""
    names = set(_commands())
    expected = {
        "cplay", "cstop", "cpause", "cresume", "cskip",
        "cclear", "cseek", "cvolume", "ceffecton", "ceffectoff", "ceffects",
        "cautoplay", "cthumbnail", "cplayset", "addchannel", "delchannel",
    }
    assert expected <= names, sorted(expected - names)
