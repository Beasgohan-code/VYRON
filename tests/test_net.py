"""The shared HTTP session — one connection, not one per lookup.

Every catalogue call used to build its own `ClientSession`: on a cold host that
is a TCP+TLS handshake per lane per keystroke, which is most of the seven
seconds the Mini App's search was showing. These tests pin the session (one,
reused), the timeout (never unbounded) and the "a fetch never raises" contract.
"""
from __future__ import annotations

import asyncio

from vyron.utils import net


def test_the_session_is_created_once_and_reused():
    async def go():
        first = await net.session()
        second = await net.session()
        assert first is second
        assert not first.closed
        await net.close()
        assert first.closed
        third = await net.session()
        assert third is not first
        await net.close()

    asyncio.run(go())


def test_get_json_never_raises_and_treats_a_bad_url_as_empty():
    async def go():
        assert await net.get_json("") is None
        assert await net.get_json("not-a-url") is None
        assert await net.get_json(None) is None
        await net.close()

    asyncio.run(go())


def test_close_is_idempotent():
    async def go():
        await net.close()
        await net.close()

    asyncio.run(go())


def test_a_request_keeps_its_own_timeout():
    """A per-call timeout must not be replaced by the session default."""
    timeout = net._timeout(2.0)
    assert timeout.total == 2.0
    assert timeout.connect is not None and timeout.connect <= 2.0
