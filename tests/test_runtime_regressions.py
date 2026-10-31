"""The bugs that shipped green because nothing ever ran the code.

`vyron/ui/cards.py` was a `SyntaxError` — one stray `,,` in the help table — so
the whole card module was unimportable and *none* of the UI had ever executed.
Every handler that posted a card died with `ImportError` the moment it was
called, and the static gates (ruff, `compileall`, the test suite) all said the
release was fine because none of them touched a card builder.

These tests are the ones that would have caught that, plus the runtime failures
found behind it: clickable buttons nobody handled, background tasks that could
be garbage-collected before they ran, and an API-key panel whose helpers did not
exist. They are intentionally about *behaviour a user sees*, not about shapes.
"""
from __future__ import annotations

import asyncio
import ast
import gc
import inspect
import re
import time
import types
from pathlib import Path

import pytest
from pyrogram.enums import ChatType

from vyron.core.queue import ChatState, Track
from vyron.ui import cards, rich

ROOT = Path(__file__).resolve().parents[1] / "vyron"


def _track() -> Track:
    return Track(
        id="dQw4w9WgXcQ",
        title="Kesariya",
        duration=268,
        uploader="Sony Music",
        requested_name="Asha",
        requested_by=42,
    )


# ── the module that could not be imported ──────────────────────────────────
def test_the_whole_package_imports_and_every_card_renders():
    """One bad character took down every card; importing is the regression test.

    The suite used to pass with `cards.py` unparseable because only a handful of
    tests imported it, and each of those was skipped by a guard. This walks the
    package the way the bot does at boot.
    """
    import importlib
    import pkgutil

    import vyron

    broken = []
    for module in pkgutil.walk_packages(vyron.__path__, "vyron."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:  # pragma: no cover - the assertion reports it
            broken.append(f"{module.name}: {type(exc).__name__}: {exc}")
    assert broken == [], broken


def test_every_card_builder_produces_markup_the_three_lanes_can_read():
    """No card may raise, and all three down-conversions must accept it."""
    track = _track()
    state = ChatState(chat_id=1)
    state.current = track
    state.queue = [track]

    rendered = [
        cards.start_card("Asha", {"chats": 3, "tracks": 40}),
        cards.group_start_card("Room", ("Asha", 42), {"voice": True}, {}),
        cards.about_card(),
        cards.player_panel(state),
        cards.settings_card({"volume": 55, "loop": "all"}, "Room"),
        cards.search_card("kesariya", [track, track]),
        cards.collection_queued_card("Dilwale", 12),
        cards.queue_card(state)[0],
        cards.download_card(track, "audio"),
        cards.lyrics_card(track, None),
        cards.queue_finished_card(track, played=2, left=True),
        cards.working_card("searching", "", glyph="search", query="Kesariya"),
    ]
    for markup in rendered:
        assert markup.strip(), "a card that renders nothing is a blank message"
        rich.to_html(markup)
        rich.to_plain_text(markup)
        rich.to_caption(markup)


# ── the working card `/play` posts ─────────────────────────────────────────
def test_the_play_handler_can_build_its_working_card():
    """`/play` passes query/step/label/live — the card only took a headline."""
    markup = cards.working_card(
        "searching", "", glyph="search", query="Past lives", step="asking the catalogues",
        label="looking for", live=True,
    )
    text = rich.to_html(markup)
    assert "Past lives" in text
    assert "asking the catalogues" in text
    assert "this card updates itself" in text

    static = rich.to_html(cards.working_card("doctor", "Running the checks."))
    assert "Running the checks" in static
    assert "this card updates itself" not in static, "a static card must not promise updates"


def test_no_card_call_site_disagrees_with_its_signature():
    """The real failure mode: a card called with arguments it never accepted.

    `cards.py` was unimportable, so no call site had ever been executed. This
    binds every `cards.*` / `B.*` / `rich.*` call in the package against the
    live signature, which is what turns "ImportError at 3am" into a test.
    """
    modules = {
        "cards": cards,
        "B": __import__("vyron.ui.blocks", fromlist=["blocks"]),
        "rich": rich,
    }
    problems = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            module = modules.get(func.value.id)
            if module is None:
                continue
            target = getattr(module, func.attr, None)
            if not callable(target):
                problems.append(f"{path.name}:{node.lineno} {func.value.id}.{func.attr} does not exist")
                continue
            if any(isinstance(arg, ast.Starred) for arg in node.args):
                continue
            if any(keyword.arg is None for keyword in node.keywords):
                continue
            try:
                inspect.signature(target).bind(
                    *[None] * len(node.args),
                    **{keyword.arg: None for keyword in node.keywords},
                )
            except TypeError as exc:
                problems.append(f"{path.name}:{node.lineno} {func.value.id}.{func.attr}: {exc}")
    assert problems == [], "\n".join(problems)


# ── buttons that were a dead tap ───────────────────────────────────────────
def _emitted_actions() -> dict[str, set[str]]:
    """Every `v:<action>` a card can put in a button, with where it came from."""
    pattern = re.compile(r"""(?:data|confirm|cancel)\s*=\s*f?["']v:([a-z0-9_]+)""")
    literal = re.compile(r"""["']v:([a-z0-9_]+):""")
    emitted: dict[str, set[str]] = {}
    for path in sorted(ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for rx in (pattern, literal):
            for match in rx.finditer(text):
                emitted.setdefault(match.group(1), set()).add(path.name)
    return emitted


def _handled_actions() -> set[str]:
    handled: set[str] = set()
    for path in sorted((ROOT / "modules").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        handled.update(m.group(1) for m in re.finditer(r'action == "([a-z0-9_]+)"', text))
        for block in re.finditer(r"action in \{([^}]*)\}", text):
            handled.update(re.findall(r'"([a-z0-9_]+)"', block.group(1)))
    return handled


def test_every_button_a_card_offers_is_handled_somewhere():
    """A button nobody handles is acknowledged and then does nothing.

    `/doctor` and `/ping` both grew a Refresh button, the now-playing card grew
    a heart, and the settings card opened a volume panel — three of the four
    were dead taps: the router answered the callback and fell through.
    """
    unhandled = sorted(set(_emitted_actions()) - _handled_actions())
    assert unhandled == [], f"buttons that do nothing: {unhandled}"


def test_the_settings_volume_button_opens_a_volume_panel(monkeypatch):
    from vyron.config import settings as app_settings
    from vyron.modules import callbacks
    from vyron.runtime import runtime

    state = ChatState(chat_id=424242, volume=60)
    player = types.SimpleNamespace(queues=types.SimpleNamespace(get=lambda _chat: state))
    monkeypatch.setattr(runtime, "player", player, raising=False)

    edited: list[str] = []

    async def fake_edit(_client, _chat_id, _message_id, markup, **_kwargs):
        edited.append(markup)

    monkeypatch.setattr(callbacks.rich, "edit", fake_edit)

    class Client:
        def on_callback_query(self, *_args, **_kwargs):
            def decorator(fn):
                self.handler = fn
                return fn

            return decorator

    client = Client()
    callbacks.register(client)

    answers: list[str] = []

    class Query:
        data = "v:volume"
        message = types.SimpleNamespace(
            id=11,
            chat=types.SimpleNamespace(id=424242, type=ChatType.PRIVATE, title="Room"),
        )
        from_user = types.SimpleNamespace(id=app_settings.owner_id, first_name="Owner")

        async def answer(self, text="", show_alert=False):
            answers.append(text)

    asyncio.run(client.handler(Client(), Query()))

    assert edited, "the tap must repaint the card"
    assert "60" in rich.to_plain_text(edited[-1])
    assert answers, "every tap is acknowledged"


def test_the_now_playing_heart_saves_the_track(monkeypatch, tmp_path):
    from vyron.config import settings as app_settings
    from vyron.database import JsonStorage
    from vyron.modules import callbacks
    from vyron.runtime import runtime

    storage = JsonStorage(app_settings)
    storage.path = tmp_path / "db.json"
    monkeypatch.setattr(runtime, "storage", storage)

    state = ChatState(chat_id=424242)
    state.current = _track()
    player = types.SimpleNamespace(queues=types.SimpleNamespace(get=lambda _chat: state))
    monkeypatch.setattr(runtime, "player", player, raising=False)

    async def fake_cfg_get(_chat_id, _key, default=None):
        return default

    from vyron.core import chatcfg

    monkeypatch.setattr(chatcfg, "get", fake_cfg_get)

    class Client:
        def on_callback_query(self, *_args, **_kwargs):
            def decorator(fn):
                self.handler = fn
                return fn

            return decorator

    client = Client()
    callbacks.register(client)

    answers: list[str] = []

    class Query:
        data = "v:like"
        message = types.SimpleNamespace(
            id=11,
            chat=types.SimpleNamespace(id=424242, type=ChatType.PRIVATE, title="Room"),
        )
        from_user = types.SimpleNamespace(id=app_settings.owner_id, first_name="Owner")

        async def answer(self, text="", show_alert=False):
            answers.append(text)

    asyncio.run(client.handler(Client(), Query()))

    saved = asyncio.run(storage.favorites(app_settings.owner_id, limit=5))
    assert saved, "the heart must actually save something"
    assert answers and "saved" in answers[-1].lower()


# ── the API-key panel ──────────────────────────────────────────────────────
def test_the_key_panel_states_every_key_and_offers_only_live_revokes():
    now = time.time()
    keys = [
        {"id": "k1", "label": "live", "masked": "vyrn_a…1", "scopes": ["read"],
         "active": True, "expires_at": now + 4 * 86400, "uses": 3},
        {"id": "k2", "label": "revoked", "masked": "vyrn_b…2", "active": False},
        {"id": "k3", "label": "expired", "masked": "vyrn_c…3", "active": True,
         "expires_at": now - 60},
        {"id": "k4", "label": "forever", "masked": "vyrn_d…4", "active": True,
         "expires_at": None},
    ]
    markup = cards.api_keys_card(keys, "https://vyron.example")
    text = rich.to_plain_text(markup)

    assert "revoked" in text and "expired" in text and "never" in text
    assert re.search(r"\dd left", text), "a key with a lifespan must show it"

    # A revoke button on a key that can no longer authenticate changes nothing.
    buttons = re.findall(r'data="v:key:revoke:([^"]+)"', markup)
    assert set(buttons) == {"k1", "k4"}


def test_the_usage_panel_says_when_a_key_was_last_used():
    keys = [
        {"label": "one", "scopes": ["read"], "uses": 7, "bytes": 2048,
         "last_used_at": time.time() - 180},
        {"label": "two", "scopes": [], "uses": 0, "bytes": 0, "last_used_at": None},
    ]
    stats = {"requests": 7, "bytes": 2048, "keys": 2, "keys_total": 2,
             "latency_ms": {"p50": 4, "p95": 9, "p99": 20}}
    text = rich.to_plain_text(cards.api_usage_card(stats, keys, "https://x.tld", sudo=True))

    assert "3m ago" in text and "never" in text


def test_importing_the_preview_tool_does_not_open_the_api(monkeypatch):
    """It used to set MUSIC_API_OPEN/WEBAPP_ALLOW_ANON at import time.

    Anything that merely imported the module — a tool that lists every module,
    a test, an unrelated entrypoint — left the whole process keyless and
    anonymous, which is a security posture changed by an import.
    """
    import importlib

    for key in ("MUSIC_API_OPEN", "WEBAPP_ALLOW_ANON", "BOT_TOKEN", "API_ID", "API_HASH", "OWNER_ID"):
        monkeypatch.delenv(key, raising=False)

    importlib.import_module("vyron.tools.preview")

    for key in ("MUSIC_API_OPEN", "WEBAPP_ALLOW_ANON"):
        assert key not in __import__("os").environ, f"importing the preview tool set {key}"


# ── background tasks ───────────────────────────────────────────────────────
def test_spawn_keeps_the_task_alive_until_it_finishes():
    """`asyncio` holds tasks weakly: a dropped reference can be collected."""
    from vyron.utils import helpers

    ran: list[str] = []

    async def work() -> None:
        await asyncio.sleep(0)
        ran.append("done")

    async def scenario() -> None:
        helpers.spawn(work(), name="test:keepalive")
        gc.collect()
        await asyncio.sleep(0.05)

    asyncio.run(scenario())
    assert ran == ["done"]


def test_a_failing_background_task_is_logged_not_lost(caplog):
    from vyron.utils import helpers

    async def boom() -> None:
        raise RuntimeError("nope")

    async def scenario() -> None:
        task = helpers.spawn(boom(), name="test:boom")
        await asyncio.sleep(0.05)
        assert task.done()

    with caplog.at_level("WARNING"):
        asyncio.run(scenario())
    assert any("test:boom" in record.getMessage() for record in caplog.records)


def test_no_background_task_is_created_without_a_reference():
    """`asyncio.create_task(...)` as a bare statement may never run at all."""
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
                continue
            func = node.value.func
            name = getattr(func, "attr", getattr(func, "id", ""))
            if name in {"create_task", "ensure_future"}:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"unreferenced background tasks: {offenders}"


# ── headings, escaping and the small things a card promises ────────────────
def test_a_heading_is_small_caps_whatever_case_the_caller_used():
    from vyron.ui import blocks as B

    assert "ɴᴏᴡ ꜱᴛʀᴇᴀᴍɪɴɢ" in B.soft_header("play", "Now Streaming")
    assert B.soft_header("play", "Now Streaming") == B.soft_header("play", "now streaming")


def test_progress_text_from_a_download_is_escaped():
    markup = cards.download_card(
        _track(), "audio", step="<script>alert(1)</script>", fraction=0.5
    )
    text = rich.to_html(markup)
    assert "alert(1)" in text
    assert "<script>" not in text


def test_a_queue_that_ends_says_so_and_offers_the_next_step():
    markup = cards.queue_finished_card(_track(), played=3, left=True)
    text = rich.to_plain_text(markup)
    assert "left the voice chat" in text
    assert 'data="v:replay"' in markup and 'data="v:radio"' in markup


@pytest.mark.parametrize("title", ["searching", "reading the link"])
def test_the_working_card_never_names_one_engine(title):
    text = rich.to_plain_text(cards.working_card(title, "", query="x", step="working"))
    assert "youtube" not in text.lower()
