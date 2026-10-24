# ---------------------------------------------------------------------------
#  /block — users *and* chats, persisted and restored at boot
#  (the chat half is the part ShizuMusic's block module does that we did not).
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio

from vyron.modules import extras


class _Storage:
    def __init__(self, data=None):
        self.data = data or {}

    async def chat_settings(self, chat_id):
        return dict(self.data)


def test_load_restores_users_and_chats():
    extras.BLOCKED_USERS.clear()
    extras.BLOCKED_CHATS.clear()
    storage = _Storage({"blocked_users": [1, "2", "nope"], "blocked_chats": [-100, "-200", "x"]})
    loaded = asyncio.run(extras.load(storage))
    assert loaded == 4
    assert extras.BLOCKED_USERS == {1, 2}
    assert extras.BLOCKED_CHATS == {-100, -200}
    extras.BLOCKED_USERS.clear()
    extras.BLOCKED_CHATS.clear()


def test_load_without_storage_is_a_no_op():
    assert asyncio.run(extras.load(None)) == 0


def test_load_survives_a_broken_store():
    class _Broken:
        async def chat_settings(self, chat_id):
            raise RuntimeError("mongo down")

    assert asyncio.run(extras.load(_Broken())) == 0
