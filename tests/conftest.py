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
def _clean_resolver_health():
    """Resolver cooldowns are process-wide; no test may inherit another's."""
    from vyron.core.resolvers import reset

    reset()
    yield
    reset()
