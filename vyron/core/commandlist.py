# ---------------------------------------------------------------------------
#  VYRON — the real command surface, read from source
# ---------------------------------------------------------------------------
# The alias prune made the handler list authoritative but invisible: nothing at
# runtime could say "these are the commands that exist", so an unknown-command
# hint had to guess. Parsing the decorators once (cached) is exact, needs no
# second list to keep in sync, and cannot drift from what pyrogram registered.
#
# Handlers register through `utils.commands.cmd(...)` (the multi-prefix filter)
# rather than `filters.command(...)`, so both spellings are recognised here.
from __future__ import annotations

import ast
import difflib
import pathlib
from functools import lru_cache

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _names_from(call: ast.Call) -> list[str]:
    if not call.args:
        return []
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return [arg.value]
    if isinstance(arg, (ast.List, ast.Tuple, ast.Set)):
        return [elt.value for elt in arg.elts if isinstance(elt, ast.Constant) and isinstance(elt.value, str)]
    return []


@lru_cache(maxsize=4)
def command_names(root: str | None = None) -> tuple[str, ...]:
    """Every ``filters.command(...)`` name in the package, lowercased + sorted."""
    base = pathlib.Path(root) if root else _ROOT
    found: set[str] = set()
    for path in base.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if getattr(node.func, "attr", "") != "command" and getattr(node.func, "id", "") != "cmd":
                continue
            found.update(name.strip().lower() for name in _names_from(node) if name.strip())
    return tuple(sorted(found))


def suggest(name: str, limit: int = 1) -> list[str]:
    """Closest live commands to *name* (``/pl`` → ``/play``, ``/favs`` → ``/fav``).

    The cutoff is deliberately high: a hint that guesses wildly is worse than
    no hint, so only genuinely close names come back.
    """
    wanted = name.strip().lower().lstrip("/")
    if not wanted:
        return []
    return difflib.get_close_matches(wanted, list(command_names()), n=limit, cutoff=0.62)


__all__ = ["command_names", "suggest"]
