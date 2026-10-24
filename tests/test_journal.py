"""Owner journal: ring buffer, filters, persistence, logging bridge."""
from __future__ import annotations

import logging

import pytest

from vyron.core.journal import Journal, journal


@pytest.fixture()
def book(tmp_path):
    return Journal(path=tmp_path / "journal.jsonl", capacity=50)


def test_record_and_read_orders_events(book):
    book.info("boot", "started", port=8080)
    book.warn("database", "json fallback")
    book.error("player", "stream died", ValueError("boom"))

    events = book.events(limit=10)
    assert [event["level"] for event in events] == ["info", "warn", "error"]
    assert events[0]["seq"] < events[1]["seq"] < events[2]["seq"]
    assert events[2]["meta"]["type"] == "ValueError"
    assert "ValueError: boom" in events[2]["meta"]["traceback"]


def test_since_cursor_returns_only_new_events(book):
    book.info("boot", "one")
    book.info("boot", "two")
    cursor = book.events(limit=1)[0]["seq"]
    book.info("boot", "three")
    fresh = book.events(since=cursor)
    assert [event["message"] for event in fresh] == ["three"]


def test_level_and_scope_filters(book):
    book.info("player", "play")
    book.warn("player", "buffer")
    book.error("database", "mongo down")

    assert [e["message"] for e in book.events(levels=["error"])] == ["mongo down"]
    assert {e["level"] for e in book.events(levels=["warn", "error"])} == {"warn", "error"}
    assert [e["message"] for e in book.events(scope="player")] == ["play", "buffer"]


def test_stats_and_clear(book):
    book.info("boot", "x")
    book.warn("boot", "y")
    book.error("boot", "z")
    stats = book.stats()
    assert stats["counts"] == {"info": 1, "warn": 1, "error": 1}
    assert stats["seq"] == 3
    assert book.clear() == 3
    # clearing is itself an event, so the buffer is not empty afterwards
    assert book.stats()["counts"]["info"] == 2


def test_writes_jsonl_and_rotates(tmp_path):
    path = tmp_path / "journal.jsonl"
    book = Journal(path=path, capacity=10)
    book.info("boot", "hello", note="world")
    line = path.read_text(encoding="utf-8").strip()
    assert '"message": "hello"' in line and '"note": "world"' in line

    # a small file is rotated once it grows past the limit
    path.write_text("x" * (4 * 1024 * 1024 + 10), encoding="utf-8")
    book.info("boot", "after rotation")
    assert path.read_text(encoding="utf-8").count("\n") == 1
    assert (tmp_path / "journal.jsonl.1").is_file()


def test_export_writes_a_snapshot(book):
    book.info("boot", "export me")
    target = book.export()
    assert target is not None and target.is_file()
    assert "export me" in target.read_text(encoding="utf-8")


def test_logging_bridge_captures_errors(book):
    book.install(level=logging.INFO)
    try:
        logging.getLogger("vyron.core.player").error("stream exploded")
        logging.getLogger("pyrogram").warning("flood wait")
    finally:
        book.uninstall()
    scopes = {event["scope"] for event in book.events(limit=10)}
    assert {"player", "telegram"} <= scopes
    assert any(event["level"] == "error" for event in book.events(limit=10))


def test_global_journal_is_the_process_singleton():
    assert journal is not None
    assert journal.stats()["buffered"] >= 0


def test_card_renders_events(book):
    from vyron.ui import cards

    book.info("player", "streaming something")
    book.error("database", "mongo down", OSError("refused"))
    markup = cards.logs_card(book.events(limit=10), book.stats(), level="all")
    assert "streaming something" in markup
    assert "mongo down" in markup
    assert "Export .jsonl" in markup


def test_clearing_records_itself_exactly_once(book):
    book.info("player", "play")
    book.info("player", "skip")
    removed = book.clear(reason="by the owner")
    assert removed == 2
    events = book.events(limit=5)
    assert len(events) == 1                      # one entry, not two
    assert "journal cleared" in events[0]["message"]
    assert "by the owner" in events[0]["message"]
