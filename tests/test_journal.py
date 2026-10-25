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


# ── warnings and errors survive a restart (#5) ──────────────────────────────
def test_the_journal_mirrors_only_problems_and_reloads_them(tmp_path):
    import asyncio
    import dataclasses

    from vyron.config import settings as base
    from vyron.core.journal import Journal
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    first = Journal(path=None)
    first.persist = True
    first.info("player", "started")           # not a problem: not mirrored
    first.warn("search", "resolver cooling down")
    first.error("database", "mongo unavailable", RuntimeError("no route to host"))
    assert len(first._persisted) == 2

    # what the debounced flush would write
    asyncio.run(storage.connect())
    asyncio.run(storage.set_meta(Journal.PERSIST_META, list(first._persisted)))

    second = Journal(path=None)
    second.persist = True
    loaded = asyncio.run(second.restore(storage))
    assert loaded == 2
    rows = second.events(limit=20)
    text = "\n".join(
        (row.get("message") if isinstance(row, dict) else getattr(row, "message", ""))
        for row in rows
    )
    assert "resolver cooling down" in text and "previous run" in text
    assert "started" not in text
    # The restored entries keep being mirrored — exactly once each — but the
    # journal's own note about having restored them is bookkeeping, not an
    # event, so it must not join the tail (it used to be restored by the next
    # boot, which is how the count climbed 3 → 10 → 29 across deploys).
    messages = [row["message"] for row in second._persisted]
    assert messages.count("resolver cooling down") == 1
    assert messages.count("mongo unavailable") == 1
    assert not any(message.startswith("restored ") for message in messages)
    assert len(second._persisted) == 2


def test_repeated_restores_do_not_inflate_the_tail(tmp_path):
    import asyncio
    import dataclasses

    from vyron.config import settings as base
    from vyron.core.journal import Journal
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    asyncio.run(storage.connect())

    first = Journal(path=None)
    first.persist = True
    first.warn("search", "resolver cooling down")
    asyncio.run(storage.set_meta(Journal.PERSIST_META, list(first._persisted)))

    sizes = []
    for _ in range(4):
        run = Journal(path=None)
        run.persist = True
        asyncio.run(run.restore(storage))
        sizes.append(len(run._persisted))
        asyncio.run(storage.set_meta(Journal.PERSIST_META, list(run._persisted)))

    # Stable, not growing: one real warning stays one row, forever.
    assert sizes == [1, 1, 1, 1], sizes


def test_a_summary_row_from_an_older_build_is_ignored(tmp_path):
    import asyncio
    import dataclasses

    from vyron.config import settings as base
    from vyron.core.journal import Journal
    from vyron.database import JsonStorage

    storage = JsonStorage(dataclasses.replace(base, data_dir=tmp_path))
    asyncio.run(storage.connect())
    # Exactly what older builds left behind in Mongo.
    asyncio.run(
        storage.set_meta(
            Journal.PERSIST_META,
            [
                {"level": "warn", "scope": "journal", "message": "restored 21 warning(s)/error(s) from the previous run", "ts": 1},
                {"level": "warn", "scope": "journal", "message": "restored 22 warning(s)/error(s) from the previous run", "ts": 2},
                {"level": "warn", "scope": "search", "message": "resolver cooling down", "ts": 3},
            ],
        )
    )

    run = Journal(path=None)
    run.persist = True
    assert asyncio.run(run.restore(storage)) == 1
    assert [row["message"] for row in run._persisted] == ["resolver cooling down"]


def test_restore_is_a_no_op_without_storage():
    import asyncio

    from vyron.core.journal import Journal

    fresh = Journal(path=None)
    assert asyncio.run(fresh.restore(None)) == 0
