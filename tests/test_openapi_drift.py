"""The published spec and the running router must not drift apart.

The OpenAPI document is hand-maintained on purpose (it carries prose a
generator cannot invent), which means it can silently fall behind. This test
fails the moment a route exists that no client can discover.
"""
from __future__ import annotations

import asyncio
import re

import pytest

pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer

from vyron.utils.health import build_app


def _concrete(path: str) -> str:
    """`/tracks/{video_id}` → `/tracks/{}` so both sides compare equal."""
    return re.sub(r"\{[^}/]+\}", "{}", path)


def _routes(api_app) -> set[tuple[str, str]]:
    """Every method/path the /v1 router actually serves."""
    found: set[tuple[str, str]] = set()
    for route in api_app.router.routes():
        resource = getattr(route, "_resource", None)
        path = (
            getattr(route, "_path", "")
            or getattr(route, "path", "")
            or getattr(resource, "canonical", "")
            or getattr(resource, "_path", "")
        )
        method = getattr(route, "method", "") or ""
        if method:
            found.add((method, _concrete(path or "/")))
    return found


def _spec(spec: dict) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path, methods in spec["paths"].items():
        for method in methods:
            found.add((method.upper(), _concrete(path)))
    return found


def test_every_v1_route_is_documented():
    async def scenario():
        app = build_app(with_webapp=False)
        async with TestClient(TestServer(app)) as client:
            spec = await (await client.get("/v1/openapi.json")).json()

        from vyron.api.app import build_app as build_api

        api_app = build_api()
        verbs = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        return {item for item in _routes(api_app) if item[0] in verbs}, _spec(spec)

    routes, documented = asyncio.run(scenario())
    missing = sorted(routes - documented)
    stale = sorted(documented - routes)
    assert not missing, "routes with no OpenAPI entry: " + ", ".join(f"{m} {p}" for m, p in missing)
    assert not stale, "OpenAPI entries with no route: " + ", ".join(f"{m} {p}" for m, p in stale)
