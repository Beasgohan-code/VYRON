"""Six connections instead of one — the part of "faster" that is measurable.

A CDN throttles a connection, not an account: the same signed URL that gives
200 KB/s gives roughly that per connection, so a 4 MB song arrives in twenty
seconds over one socket and in three over six. Everything here runs against a
real local HTTP server, so the numbers are the code's, not a mock's.
"""
from __future__ import annotations

import asyncio
import hashlib
import os

from aiohttp import web
from aiohttp.test_utils import TestServer

from vyron.core import accelerator

PAYLOAD = os.urandom(3 * 1024 * 1024)  # 3 MB: over the split threshold
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()


def _range_handler(state: dict):
    async def handler(request: web.Request) -> web.StreamResponse:
        state["requests"].append(request.headers.get("Range"))
        raw = request.headers.get("Range")
        if state.get("ignore_ranges") or not raw:
            return web.Response(body=PAYLOAD, headers={"Accept-Ranges": "bytes"})
        first, last = raw.split("=", 1)[1].split("-", 1)
        start = int(first)
        end = int(last) if last else len(PAYLOAD) - 1
        end = min(end, len(PAYLOAD) - 1)
        body = PAYLOAD[start : end + 1]
        return web.Response(
            body=body,
            status=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{len(PAYLOAD)}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(body)),
            },
        )

    return handler


async def _serve(state: dict) -> TestServer:
    app = web.Application()
    app.router.add_get("/song.m4a", _range_handler(state))
    server = TestServer(app)
    await server.start_server()
    return server


def test_the_ranges_cover_every_byte_exactly_once():
    for size in (1_500_000, 3_000_001, 40_000_000):
        ranges = accelerator.plan_ranges(size)
        assert ranges[0][0] == 0
        assert ranges[-1][1] == size - 1
        for (_, end), (start, _) in zip(ranges[:-1], ranges[1:], strict=True):
            assert start == end + 1, f"gap or overlap at {start} for {size}"
        assert all(end >= start for start, end in ranges)


def test_a_file_is_pulled_over_several_connections(tmp_path):
    async def go():
        state: dict = {"requests": []}
        server = await _serve(state)
        try:
            target = tmp_path / "song.m4a"
            size = await accelerator.ranged_fetch(server.make_url("/song.m4a"), target)
            assert size == len(PAYLOAD)
            assert hashlib.sha256(target.read_bytes()).hexdigest() == DIGEST
            ranged = [r for r in state["requests"] if r and r != "bytes=0-0"]
            assert len(ranged) > 1, state["requests"]
            assert not list(tmp_path.glob("*.part*")), "the slices were left behind"
        finally:
            await server.close()

    asyncio.run(go())


def test_a_server_that_ignores_ranges_is_not_a_failure(tmp_path):
    """Some signed URLs answer 200 to a Range. That is a slow path, not an error."""

    async def go():
        state: dict = {"requests": [], "ignore_ranges": True}
        server = await _serve(state)
        try:
            target = tmp_path / "song.m4a"
            tool = await accelerator.fetch(server.make_url("/song.m4a"), target)
            assert tool  # ranged → single connection, whichever it settled on
            assert hashlib.sha256(target.read_bytes()).hexdigest() == DIGEST
        finally:
            await server.close()

    asyncio.run(go())


def test_progress_is_reported_while_the_ranges_arrive(tmp_path):
    async def go():
        state: dict = {"requests": []}
        server = await _serve(state)
        try:
            seen: list[int] = []
            await accelerator.ranged_fetch(
                server.make_url("/song.m4a"),
                tmp_path / "song.m4a",
                on_progress=lambda done, total: seen.append(done),
            )
            assert seen and max(seen) == len(PAYLOAD)
        finally:
            await server.close()

    asyncio.run(go())


def test_an_oversized_file_is_refused_before_the_bytes_arrive(tmp_path):
    async def go():
        state: dict = {"requests": []}
        server = await _serve(state)
        try:
            try:
                await accelerator.ranged_fetch(
                    server.make_url("/song.m4a"), tmp_path / "song.m4a", cap=1024
                )
            except RuntimeError as exc:
                assert "allowed size" in str(exc)
            else:  # pragma: no cover
                raise AssertionError("the cap was ignored")
        finally:
            await server.close()

    asyncio.run(go())
