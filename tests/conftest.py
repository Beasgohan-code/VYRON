"""Shared test bootstrap — keeps the suite offline and deterministic."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Fake-but-valid credentials so Settings.validate() and client builders work.
os.environ.setdefault("BOT_TOKEN", "123456789:TEST-TOKEN")
os.environ.setdefault("API_ID", "123456")
os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("OWNER_ID", "424242")
os.environ.setdefault("STRING_SESSION", "")
os.environ.setdefault("MONGO_URL", "")
os.environ.setdefault("PREMIUM_EMOJI", "false")
os.environ.setdefault("PORT", "0")
os.environ.setdefault("DATA_DIR", str(ROOT / "data_test"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _keep_an_event_loop():
    """Every test starts with an event loop installed.

    `asyncio.run()` closes the loop it created, and pytgcalls calls
    ``asyncio.get_event_loop()`` at import time — so a test that imported
    ``vyron.runtime`` after another test used ``asyncio.run`` used to fail
    depending on file order. Fixing it here means the suite no longer has an
    ordering rule nobody can remember.
    """
    import asyncio

    try:
        previous = asyncio.get_event_loop_policy().get_event_loop()
    except RuntimeError:
        previous = None
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(previous)


@pytest.fixture(autouse=True)
def _no_journal_mirror():
    """The journal mirrors warnings into storage on a 2 s debounce.

    Production wants that; a test that patches `asyncio.sleep` does not.
    The persistence tests opt back in explicitly.
    """
    from vyron.core.journal import journal

    previous = journal.persist
    journal.persist = False
    yield
    journal.persist = previous


@pytest.fixture(autouse=True)
def _clean_prefixes():
    """Prefix overrides are process-wide; every test starts from the defaults."""
    from vyron.utils import commands

    commands.override(None)
    yield
    commands.override(None)


@pytest.fixture(autouse=True)
def _clean_resolver_health():
    """Resolver cooldowns are process-wide; no test may inherit another's."""
    from vyron.core.resolvers import reset

    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def _clean_token_epochs():
    """Revocation epochs are cached process-wide; no test may inherit one.

    Without this, a test that revokes leaves the cache at epoch 1 and the next
    test's freshly minted token (epoch 0) looks revoked — a 401 that only
    appears when the test order changes.
    """
    from vyron.core import tokens

    tokens.reset_cache()
    yield
    tokens.reset_cache()
