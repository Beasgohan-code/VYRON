# ---------------------------------------------------------------------------
#  VYRON — application bootstrap
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time

from pyrogram.types import BotCommand

from vyron import __version__, banner_text, setup_logging
from vyron.clients import build_assistant, build_bot
from vyron.config import settings
from vyron.modules import register_all
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.utils import health

logger = logging.getLogger("vyron")

COMMANDS = [
    ("start", "home screen"),
    ("play", "stream audio in voice chat"),
    ("vplay", "stream video"),
    ("song", "download an MP3"),
    ("video", "download an MP4"),
    ("search", "search and pick a result"),
    ("playlist", "queue a YouTube playlist"),
    ("pause", "pause playback"),
    ("resume", "resume playback"),
    ("skip", "next track"),
    ("stop", "end session & leave"),
    ("seek", "jump inside the track"),
    ("volume", "set assistant volume"),
    ("loop", "repeat mode"),
    ("shuffle", "shuffle the queue"),
    ("np", "now playing"),
    ("queue", "show the queue"),
    ("lyrics", "find lyrics"),
    ("settings", "per-chat settings"),
    ("app", "open the player web app"),
    ("effects", "audio effects panel"),
    ("locks", "content locks & anti-flood"),
    ("warn", "warn a member"),
    ("warns", "member warnings"),
    ("ban", "ban a member"),
    ("mute", "mute a member"),
    ("purge", "bulk delete messages"),
    ("setwelcome", "set the welcome message"),
    ("cplay", "play in the linked channel"),
    ("stats", "bot statistics"),
    ("help", "all commands"),
]


async def _set_commands(bot) -> None:
    try:
        await bot.set_bot_commands([BotCommand(command=name, description=desc) for name, desc in COMMANDS])
    except Exception as exc:  # pragma: no cover
        logger.debug("could not set bot commands: %s", exc)


async def _setup_menu_button(bot) -> None:
    """Point the bot's menu button at the Mini App when WEBAPP_URL is set."""
    url = settings.webapp_url
    if not (settings.webapp and url):
        return
    try:
        from pyrogram.types import MenuButtonWebApp, WebAppInfo

        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=settings.webapp_title[:14] or "Player",
                web_app=WebAppInfo(url=f"{url}/app/"),
            )
        )
        logger.info("menu button → %s/app/", url)
    except Exception as exc:
        logger.debug("could not set the menu button: %s", exc)


async def _notify_owner(bot) -> None:
    if not settings.owner_id:
        return
    try:
        await rich.send(
            bot,
            settings.owner_id,
            cards.start_card("owner", {"chats": 0, "tracks": 0}),
            markup_keyboard=None,
            silent=True,
        )
    except Exception:
        pass


async def _async_main() -> int:
    setup_logging(settings.log_level)
    print(banner_text())

    problems = settings.validate()
    if problems:
        for problem in problems:
            logger.error("config: %s", problem)
        logger.error("Copy .env.example to .env and fill it in — see README.md")
        return 1
    for note in settings.warnings():
        logger.warning("config: %s", note)

    settings.ensure_dirs()
    # open the HTTP port first: Render/Koyeb polls it while the bot dials Telegram
    runner = await health.start(settings.port)
    runtime.settings = settings
    runtime.version = __version__
    runtime.started_at = time.time()

    bot = build_bot(settings)
    assistant = build_assistant(settings)
    runtime.bot = bot
    runtime.assistant = assistant

    logger.info("starting bot client…")
    await bot.start()
    me = await bot.get_me()
    logger.info("connected as @%s", me.username)

    calls = None
    if assistant is not None:
        from pytgcalls import PyTgCalls

        logger.info("starting assistant (voice engine)…")
        await assistant.start()
        calls = PyTgCalls(assistant)
        runtime.calls = calls
        await calls.start()
        logger.info("voice engine ready")
    else:
        logger.warning("no STRING_SESSION — running in file-only mode (no voice chat)")

    await runtime.build_services()
    if runtime.player and calls is not None:
        runtime.player.calls = calls
        runtime.player.register_handlers()

    loaded = register_all(bot)
    runtime.handlers_loaded = loaded
    await _set_commands(bot)
    await _setup_menu_button(bot)

    await runtime.player.start_background()
    await _notify_owner(bot)

    logger.info(
        "VYRON is online — %d handler modules, streaming=%s, storage=%s",
        len(loaded),
        runtime.streaming_ready,
        runtime.storage.backend if runtime.storage else "none",
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover
            pass

    try:
        await stop.wait()
    finally:
        logger.info("shutting down…")
        await runtime.shutdown()
        if runner is not None:
            try:
                await runner.cleanup()
            except Exception:
                pass
        for client in (calls, assistant, bot):
            if client is None:
                continue
            try:
                await client.stop()
            except Exception:
                pass
    return 0


def run() -> None:
    try:
        import uvloop  # type: ignore

        uvloop.install()
    except Exception:
        pass
    try:
        sys.exit(asyncio.run(_async_main()))
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001 - last-resort deploy log
        logger.debug("startup traceback", exc_info=True)
        logger.error("startup failed: %s", exc)
        logger.error(
            "check BOT_TOKEN, that API_ID/API_HASH belong to the same app, "
            "and that this host can reach api.telegram.org"
        )
        sys.exit(1)


if __name__ == "__main__":
    run()
