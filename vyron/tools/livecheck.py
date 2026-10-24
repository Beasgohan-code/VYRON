#!/usr/bin/env python3
# ---------------------------------------------------------------------------
#  VYRON — live check
#
#      python -m vyron.tools.livecheck              # human readable
#      python -m vyron.tools.livecheck --json out.json
#
#  The test suite is deliberately offline: it must pass on a plane with no
#  credentials. But the parts most likely to break are the ones that talk to
#  somebody else's server — Invidious, Piped, Cobalt, song.link, saavn.dev,
#  LRCLIB, YouTube itself. No unit test can catch "the JSON shape changed".
#
#  This does the opposite: it makes real requests against real services and says
#  what happened. It is run nightly by .github/workflows/live.yml, and by hand
#  whenever `/doctor` looks healthy but nothing plays.
#
#  Exit code 0 = everything that must work, works. 1 = something to look at.
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field

# Importing the bot's core must not require Telegram credentials.
os.environ.setdefault("BOT_TOKEN", "0:livecheck")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "livecheck")
os.environ.setdefault("OWNER_ID", "1")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    ms: float = 0.0
    critical: bool = True
    extra: dict = field(default_factory=dict)


async def _timed(name: str, coro, *, critical: bool = True) -> Check:
    started = time.perf_counter()
    try:
        detail = await coro
        ok = True
    except Exception as exc:  # a failure here is the *point* of the tool
        detail = f"{type(exc).__name__}: {str(exc)[:160]}"
        ok = False
    return Check(
        name=name,
        ok=ok,
        detail=str(detail)[:200],
        ms=round((time.perf_counter() - started) * 1000, 1),
        critical=critical,
    )


# ── individual probes ───────────────────────────────────────────────────────
async def _search() -> str:
    """YouTube search still returns something playable."""
    from vyron.config import settings
    from vyron.core.search import YouTube

    youtube = YouTube(settings)
    results = await youtube.search("kesariya arijit singh", limit=3)
    if not results:
        raise RuntimeError("no results")
    first = results[0]
    return f"{len(results)} results · first: {first.title[:40]} ({first.duration}s)"


async def _stream() -> str:
    """A real audio URL can be resolved (this is the whole product)."""
    from vyron.config import settings
    from vyron.core.search import YouTube

    youtube = YouTube(settings)
    results = await youtube.search("believer imagine dragons", limit=1)
    if not results:
        raise RuntimeError("nothing to resolve")
    info = await youtube.stream_info(results[0])
    if not info.url.startswith("http"):
        raise RuntimeError(f"not a url: {info.url[:40]}")
    return f"{info.mime} · url host ok"


async def _resolvers() -> str:
    """The Invidious/Piped/Cobalt ladder — at least one tier must answer."""
    from vyron.core import sources

    rows = await sources.probe(query="kesariya")
    working = [
        row["name"]
        for row in rows
        if (row.get("probe") or {}).get("ok") and row.get("kind") in {"extract", "stream"}
    ]
    if not working:
        raise RuntimeError("no extractable source answered")
    return f"{len(working)} source(s): {', '.join(working[:5])}"


async def _odesli() -> str:
    """song.link still maps a catalogue link to a YouTube id."""
    from vyron.core import metasources

    metasources._MATCH_CACHE.clear()
    found = await metasources.match("https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b")
    if not found:
        raise RuntimeError("no YouTube id returned")
    return f"matched {found}"


async def _saavn() -> str:
    """JioSaavn's public API answers."""
    from vyron.core.jiosaavn import search as saavn_search

    results = await saavn_search("kesariya", limit=2)
    if not results:
        raise RuntimeError("no results")
    return f"{len(results)} results"


async def _lrclib() -> str:
    """Lyrics lookup."""
    from vyron.core.lyrics import LyricsClient

    client = LyricsClient()
    try:
        result = await client.find("Kesariya", "Arijit Singh")
    finally:
        await client.close()
    if result is None or not (result.plain or result.synced):
        raise RuntimeError("no lyrics")
    return "synced" if result.has_sync else "plain"


async def _audius() -> str:
    from vyron.core.audius import search as audius_search

    results = await audius_search("lofi", limit=2)
    if not results:
        raise RuntimeError("no results")
    return f"{len(results)} results"


# ── main ────────────────────────────────────────────────────────────────────
PROBES = [
    ("youtube search", _search, True),
    ("youtube stream", _stream, True),
    ("resolver ladder", _resolvers, False),
    ("song.link", _odesli, False),
    ("jiosaavn", _saavn, False),
    ("lrclib", _lrclib, False),
    ("audius", _audius, False),
]


async def run() -> list[Check]:
    checks: list[Check] = []
    for name, probe, critical in PROBES:
        checks.append(await _timed(name, probe(), critical=critical))
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Talk to the real services VYRON uses.")
    parser.add_argument("--json", dest="json_path", help="write a machine-readable report here")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on a degraded optional source too (default: only critical ones fail)",
    )
    args = parser.parse_args(argv)

    checks = asyncio.run(run())
    width = max(len(check.name) for check in checks)
    for check in checks:
        mark = "ok  " if check.ok else "FAIL"
        print(f"{mark}  {check.name:<{width}}  {check.ms:>7.1f} ms  {check.detail}")

    must_pass = [c for c in checks if c.critical or args.strict]
    failed = [c for c in must_pass if not c.ok]

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "ok": not failed,
                    "generated_at": time.time(),
                    "checks": [asdict(check) for check in checks],
                },
                handle,
                indent=2,
            )

    if failed:
        print(f"\n{len(failed)} critical check(s) failed: " + ", ".join(c.name for c in failed))
        return 1
    optional = [c for c in checks if not c.ok]
    if optional:
        print("\noptional sources unavailable: " + ", ".join(c.name for c in optional))
    print("\nall critical checks passed")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    sys.exit(main())
