# ---------------------------------------------------------------------------
#  VYRON — application bootstrap
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
import traceback

from pyrogram.types import BotCommand

from vyron import __version__, banner_text, setup_logging
from vyron.clients import build_assistant, build_bot, session_problem
from vyron.config import settings
from vyron.modules import register_all
from vyron.core import keepalive, maintenance, watchdog
from vyron.core.journal import attach, journal
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.utils import health

logger = logging.getLogger("vyron")

COMMANDS = [
    ("start", "home screen"),
    ("play", "stream audio in voice chat"),
    ("vplay", "stream video"),
    ("playforce", "clear the queue and play now"),
    ("song", "download an MP3"),
    ("video", "download an MP4"),
    ("vsong", "download a video file"),
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
    ("language", "change VYRON's language"),
    ("app", "open the player web app"),
    ("api", "music API for other bots"),
    ("getapi", "mint a music API key"),
    ("apitoken", "owner token for web app + API"),
    ("logs", "owner journal: starts, stops, errors"),
    ("logger", "mirror warnings to a channel"),
    ("effects", "audio effects panel"),
    ("voice", "voice engine status"),
    ("thumbnail", "per-chat poster artwork"),
    ("locks", "content locks & anti-flood"),
    ("warn", "warn a member"),
    ("warns", "member warnings"),
    ("ban", "ban a member"),
    ("mute", "mute a member"),
    ("purge", "bulk delete messages"),
    ("gadmin", "group manager panel"),
    ("rules", "this chat's rules"),
    ("setrules", "set the rules (admins)"),
    ("chatinfo", "chat id, members, settings"),
    ("settitle", "rename this chat"),
    ("setdesc", "set the chat description"),
    ("slowmode", "message rate limit"),
    ("invitelink", "create an invite link"),
    ("approve", "exempt a member from locks"),
    ("zombies", "find deleted accounts"),
    ("report", "flag a message to admins"),
    ("tmute", "mute for a set time"),
    ("setwelcome", "set the welcome message"),
    ("cplay", "play in the linked channel"),
    ("cplayset", "bind a channel for playback"),
    ("voteskip", "enable group vote-skip"),
    ("fav", "save the current track"),
    ("savepl", "save the queue as a playlist"),
    ("suggest", "tracks like this one"),
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
    from vyron.ui.keyboards import app_url

    url = app_url()
    if not url:
        return
    try:
        from pyrogram.types import MenuButtonWebApp, WebAppInfo

        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text=settings.webapp_title[:14] or "Player",
                web_app=WebAppInfo(url=url),
            )
        )
        logger.info("menu button → the Mini App entry")
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
        logger.info("sent the boot card to the owner DM")
    except Exception as exc:
        # PEER_ID_INVALID simply means the owner has never opened a chat with
        # the bot — that is a user action, not a bot failure.
        text = str(exc)
        if "PEER_ID_INVALID" in text or "USER_IS_BLOCKED" in text or "CHAT_NOT_FOUND" in text:
            logger.info(
                "could not DM the owner yet (%s) — send /start to @%s once and "
                "future boot cards will arrive",
                text.split("]")[-1].strip() or "PEER_ID_INVALID",
                settings.bot_username,
            )
        else:
            logger.debug("owner boot card failed: %s", exc)


async def _async_main() -> int:
    setup_logging(settings.log_level)
    print(banner_text())
    settings.ensure_dirs()
    attach(settings.data_dir / "journal.jsonl")
    journal.info(
        "boot",
        "process starting",
        version=__version__,
        port=settings.port,
        music_api=settings.music_api,
        webapp=settings.webapp,
    )

    problems = settings.validate()
    if problems:
        for problem in problems:
            logger.error("config: %s", problem)
            journal.error("config", problem)
        logger.error("Copy .env.example to .env and fill it in — see README.md")
        return 1
    for note in settings.warnings():
        logger.warning("config: %s", note)
        journal.warn("config", note)

    # validate the session *before* dialling Telegram: a truncated paste is the
    # most common deploy mistake and should fail here, with the reason.
    problem = session_problem(settings.session_string)
    if problem:
        logger.error("config: %s", problem)
        journal.error("config", problem)
        logger.error(
            "generate a fresh session with `python -m vyron.tools.session` "
            "(README → Create the assistant session)"
        )
        return 1

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
        try:
            await assistant.start()
            calls = PyTgCalls(assistant)
            runtime.calls = calls
            await calls.start()
        except Exception as exc:
            logger.error(
                "the assistant session could not start (%s: %s). Streaming is off — "
                "regenerate STRING_SESSION with `python -m vyron.tools.session`.",
                type(exc).__name__,
                exc,
            )
            journal.error("boot", "assistant session failed to start", exc)
            calls = None
            runtime.calls = None
            runtime.assistant = None
        else:
            logger.info("voice engine ready")
            journal.ok("voice", "voice engine ready")

    if calls is None:
        logger.warning(
            "no voice engine — /play will refuse until STRING_SESSION is set and valid"
        )

    await runtime.build_services()
    from vyron.core import logsink

    logsink.install(bot)
    if await logsink.load(runtime.storage):
        logger.info("log channel is on")
    if runtime.player and calls is not None:
        runtime.player.calls = calls
        runtime.player.register_handlers()

    if runtime.player:
        # A restart should not lose what people queued, and 24/7 chats should
        # pick up where they left off once the voice engine is running.
        restored = await runtime.player.restore_queues()
        if restored:
            logger.info("restored %d queue(s)", restored)
        if calls is not None:
            resumed = await runtime.player.resume_always_on()
            if resumed:
                logger.info("resumed %d 24/7 chat(s)", resumed)

    loaded = register_all(bot)
    runtime.handlers_loaded = loaded
    await _set_commands(bot)
    await _setup_menu_button(bot)
    from vyron.core import botprofile

    await botprofile.install(bot)
    if settings.music_api:
        base = settings.api_base or f"http://0.0.0.0:{settings.port}"
        logger.info(
            "music api → %s/v1/docs  (keys: /getapi · owner login: /apitoken)", base
        )

    await runtime.player.start_background()
    maintenance.start()
    watchdog.start()
    keepalive.start()
    await _notify_owner(bot)

    storage_backend = runtime.storage.backend if runtime.storage else "none"
    logger.info(
        "VYRON is online — %d handler modules, streaming=%s, storage=%s",
        len(loaded),
        runtime.streaming_ready,
        storage_backend,
    )
    journal.boot(
        version=__version__,
        storage=storage_backend,
        streaming=runtime.streaming_ready,
        handlers=len(loaded),
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
        journal.shutdown("signal")
        await maintenance.stop()
        await watchdog.stop()
        await keepalive.stop()
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
        logger.error("startup failed: %s: %s", type(exc).__name__, exc)
        logger.error("traceback:\n%s", traceback.format_exc())
        journal.error("boot", "startup failed", exc)
        # Point at the real cause instead of blaming the token every time.
        text = f"{type(exc).__name__}: {exc}".lower()
        if any(word in text for word in ("auth_key", "api_id", "api_hash", "unauthorized", "token")):
            logger.error(
                "check BOT_TOKEN, and that API_ID/API_HASH belong to the same app "
                "as that bot"
            )
        elif any(word in text for word in ("timeout", "connection", "network", "resolve", "dns")):
            logger.error(
                "this host could not reach api.telegram.org — check outbound network "
                "access (some hosts block it on the free tier)"
            )
        elif any(word in text for word in ("session", "dc_id", "sign_in")):
            logger.error(
                "STRING_SESSION looks wrong for this API_ID — regenerate it with "
                "`python -m vyron.tools.session` using the same API_ID/API_HASH"
            )
        else:
            logger.error("the traceback above is the exact failure; nothing was masked")
        sys.exit(1)


if __name__ == "__main__":
    run()
