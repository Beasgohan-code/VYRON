"""Streaming-first behaviour: session validation and the /voice console."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace


from vyron.clients import session_problem


class _Settings(SimpleNamespace):
    audio_quality = "high"
    video_quality = "720p"


# ── STRING_SESSION validation ───────────────────────────────────────────────
def test_empty_session_is_reported():
    assert "empty" in session_problem("")


def test_garbage_session_is_reported():
    problem = session_problem("not-a-real-session")
    assert "not a session this build understands" in problem or "could not be decoded" in problem


def _session(dc_id: int = 2, api_id: int = 12345, key: bytes | None = None) -> str:
    """Build a session string in the installed pyrogram's own format."""
    import base64
    import struct

    from pyrogram.storage.sqlite_storage import SQLiteStorage

    auth_key = key if key is not None else bytes(range(256))
    fmt = SQLiteStorage.SESSION_STRING_FORMAT
    payload = struct.pack(fmt, dc_id, api_id, False, auth_key, 777000, False)
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def test_a_well_formed_session_passes():
    assert session_problem(_session()) == ""


def test_a_placeholder_key_is_rejected():
    problem = session_problem(_session(key=b"\x00" * 256))
    assert "no login key" in problem


def test_a_pasted_assignment_is_rejected():
    problem = session_problem(f"STRING_SESSION={_session()}")
    assert "only the value" in problem


def test_a_truncated_session_is_rejected():
    problem = session_problem(_session()[:120])
    assert "cut short" in problem or "could not be decoded" in problem


def test_a_bad_data_centre_is_rejected():
    problem = session_problem(_session(dc_id=9))
    assert "data centre" in problem


# ── /voice card ─────────────────────────────────────────────────────────────
def test_engine_card_says_it_is_off_without_a_session(monkeypatch):
    from vyron import runtime as runtime_module
    from vyron.modules.assistant_tools import engine_card

    runtime = runtime_module.runtime
    monkeypatch.setattr(runtime, "calls", None)
    monkeypatch.setattr(runtime, "assistant", None)
    monkeypatch.setattr(runtime, "settings", _Settings())

    card = engine_card()

    assert "off" in card
    assert "STRING_SESSION" in card
    assert "voice only" in card


def test_engine_card_reports_a_ready_engine(monkeypatch):
    from vyron import runtime as runtime_module
    from vyron.modules.assistant_tools import engine_card

    class Player:
        def active_chats(self):
            return [-1001]

    runtime = runtime_module.runtime
    monkeypatch.setattr(runtime, "calls", object())
    monkeypatch.setattr(runtime, "assistant", SimpleNamespace(me=SimpleNamespace(username="vyron_assistant", first_name="V")))
    monkeypatch.setattr(runtime, "player", Player())
    monkeypatch.setattr(runtime, "settings", _Settings())

    card = engine_card()

    assert "<b>on</b>" in card
    assert "vyron_assistant" in card
    assert "-1001" in card


# ── /play never falls back to a file on a stream error ─────────────────────
def test_stream_error_is_reported_not_uploaded(monkeypatch):
    from vyron import runtime as runtime_module
    from vyron.core.player import StreamError
    from vyron.core.queue import Track
    from vyron.modules import play as play_module

    class Player:
        async def enqueue(self, *args, **kwargs):
            raise StreamError("the assistant could not join the voice chat")

    class Client:
        def __init__(self):
            self.sent: list = []

        async def send_audio(self, *args, **kwargs):  # pragma: no cover
            self.sent.append("audio")

        async def edit_message_text(self, chat_id, message_id, text, **kwargs):
            self.sent.append(text)

    runtime = runtime_module.runtime
    monkeypatch.setattr(runtime, "calls", object())
    monkeypatch.setattr(runtime, "player", Player())

    client = Client()
    track = Track(id="x", title="Song", duration=100)
    outcome = asyncio.run(play_module.begin(client, -100, track, status_id=3))

    assert outcome == "error"
    assert "audio" not in client.sent
    # The chat gets an explanation in words, not the engine's own sentence:
    # this one is the "the assistant could not join" case.
    assert any("Could not start the call" in str(item) for item in client.sent)
