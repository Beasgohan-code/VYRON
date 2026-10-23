#!/usr/bin/env python3
# ---------------------------------------------------------------------------
#  VYRON — web app preview server
#
#  Serves the Mini App (and the health endpoints) without needing Telegram
#  credentials, so you can iterate on the UI in a normal browser:
#
#      python -m vyron.tools.preview --port 8080
#
#  The page falls back to read-only demo data outside Telegram.
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
import asyncio
import logging
import os

# Must be set before vyron.config is imported anywhere.
os.environ.setdefault("WEBAPP_ALLOW_ANON", "true")
os.environ.setdefault("BOT_TOKEN", "0:preview")
os.environ.setdefault("API_ID", "1")
os.environ.setdefault("API_HASH", "preview")
os.environ.setdefault("OWNER_ID", "1")
os.environ.setdefault("MUSIC_API_OPEN", "true")  # docs + health are clickable in preview

from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("preview")


async def main() -> None:
    parser = argparse.ArgumentParser(description="VYRON web app preview")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    from vyron.utils.health import build_app

    app = build_app(with_webapp=True)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=args.host, port=args.port)
    await site.start()

    logger.info("web app  → http://%s:%s/app/", args.host, args.port)
    logger.info("health   → http://%s:%s/health", args.host, args.port)
    logger.info("preview data is read-only until opened inside Telegram")

    stop = asyncio.Event()
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
