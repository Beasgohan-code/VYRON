#!/usr/bin/env python3
# ---------------------------------------------------------------------------
#  VYRON — web app preview server
#
#  Serves the Mini App (and the health endpoints) without needing Telegram
#  credentials, so you can iterate on the UI in a normal browser:
#
#      python -m vyron.tools.preview --port 8080
#
#  Outside Telegram the page renders its locked state and waits for
#  initData, so nothing shown here is fabricated.
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
import asyncio
import contextlib
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


async def _warm_services(*, use_db: bool) -> None:
    """Attach the real resolver/downloader so preview search hits YouTube."""
    from vyron.config import settings
    from vyron.core.charts import Charts
    from vyron.core.downloader import Downloader
    from vyron.core.search import YouTube
    from vyron.runtime import runtime

    settings.ensure_dirs()
    runtime.youtube = YouTube(settings)
    runtime.charts = Charts(runtime.youtube)
    try:
        runtime.downloader = Downloader(settings)
    except OSError as exc:  # read-only filesystem
        logger.warning("download cache unavailable: %s", exc)

    if not use_db:
        return
    from vyron.database import make_storage

    try:
        runtime.storage = await asyncio.wait_for(make_storage(settings), timeout=12)
    except Exception as exc:  # no Mongo / no credentials — still previewable
        logger.warning("storage unavailable in preview (%s): favourites off", exc)
        return
    logger.info("storage ready: %s", getattr(runtime.storage, "backend", "?"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="VYRON web app preview")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument(
        "--no-owner",
        action="store_true",
        help="do not mint a local owner token for the console",
    )
    parser.add_argument(
        "--no-db",
        action="store_true",
        help="skip Mongo/JSON storage (favourites and playlists stay empty)",
    )
    args = parser.parse_args()

    await _warm_services(use_db=not args.no_db)

    # The preview records into the same journal as production, so the owner
    # console has real events to show while you iterate.
    from vyron.config import settings
    from vyron.core.journal import attach, journal

    settings.ensure_dirs()
    attach(settings.data_dir / "journal.jsonl")
    journal.info("boot", "preview server starting", port=args.port, host=args.host)

    from vyron.utils.health import build_app

    app = build_app(with_webapp=True)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host=args.host, port=args.port)
    await site.start()

    logger.info("web app  → http://%s:%s/app/", args.host, args.port)
    logger.info("health   → http://%s:%s/health", args.host, args.port)
    if not args.no_owner:
        from vyron.config import settings
        from vyron.web.auth import make_owner_token

        owner_id = next(iter(settings.owners), 1)
        token = make_owner_token(settings.bot_token, owner_id)
        # printed, not logged: the token must never end up in the journal
        print(f"owner console → http://{args.host}:{args.port}/app/?ot={token}")
        journal.info("preview", "owner console enabled (token printed to the terminal)")
    logger.info("outside Telegram the app shows a locked state — no placeholder data")

    stop = asyncio.Event()
    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        journal.shutdown("preview stop")
        await runner.cleanup()
        from vyron.runtime import runtime

        with contextlib.suppress(Exception):
            if runtime.storage is not None:
                await runtime.storage.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
