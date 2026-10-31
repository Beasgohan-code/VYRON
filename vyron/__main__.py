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

from vyron import __build__, __version__, banner_text, setup_logging
from vyron.clients import build_assistant, build_bot, session_problem
from vyron.config import settings
from vyron.modules import register_all
from vyron.core import keepalive, lease, maintenance, watchdog
from vyron.core.journal import attach, journal
from vyron.runtime import runtime
from vyron.ui import cards, rich
from vyron.utils import health
from vyron.utils.helpers import spawn

logger = logging.getLogger("vyron")

COMMANDS = [
    ("start", "home screen"),
    ("play", "stream in voice chat (audio or video)"),
    ("song", "download the file"),
    ("search", "search and pick a result"),
    ("playlist", "queue a YouTube playlist"),
    ("pause", "pause playback"),
    ("resume", "resume playback"),
    ("skip", "next track"),
    ("stop", "end session & leave"),
    ("seek", "jump inside the track"),
    ("volume", "set assistant volume"),
    ("loop", "repeat mode"),
    ("vplay", "play the video in the voice chat"),
    ("vsong", "send the video file"),
    ("shuffle", "shuffle the queue"),
    ("np", "now playing"),
    ("queue", "show the queue"),
    ("lyrics", "find lyrics"),
    ("settings", "per-chat settings"),
    ("language", "change VYRON's language"),
    ("uistyle", "switch rich / classic cards"),
    ("uicheck", "verify the UI renders here"),
    ("app", "open the player web app"),
    ("api", "music API for other bots"),
    ("getapi", "mint a music API key"),
    ("apitoken", "owner token for web app + API"),
    ("logs", "owner journal: starts, stops, errors"),
    ("doctor", "deployment self-check"),
    ("sources", "which resolvers work from this server"),
    ("logger", "mirror warnings to a channel"),
    ("effects", "audio effects panel"),
    ("voice", "voice engine status"),
    ("locks", "content locks & anti-flood"),
    ("warn", "warn a member"),
    ("warns", "member warnings"),
    ("ban", "ban a member"),
    ("dban", "ban and delete the message"),
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
    ("cpplay", "play a playlist in the linked channel"),
    ("cplayset", "bind a channel for playback"),
    ("voteskip", "enable group vote-skip"),
    ("fav", "save the current track"),
    ("savepl", "save the queue as a playlist"),
    ("similar", "tracks like this one"),
    ("mydata", "download everything I have here"),
    ("forgetme", "delete my history, favourites and playlists"),
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


async def _start_client(client, label: str, *, attempts: int = 8) -> None:
    """``client.start()`` that honours Telegram's own rate limit.

    A bot signed in by several deploys in a row gets ``FLOOD_WAIT`` on
    ``auth.ImportBotAuthorization``. Exiting there is the worst thing to do:
    Render restarts the container, which signs in again and pushes the wait
    further out. So wait exactly what Telegram asks for, then retry.
    """
    from pyrogram.errors import FloodWait

    for attempt in range(1, attempts + 1):
        try:
            await client.start()
            return
        except FloodWait as exc:
            wait = int(getattr(exc, "value", 60) or 60) + 5
            logger.warning(
                "%s: Telegram rate-limited the login — waiting %ss (attempt %d/%d)",
                label,
                wait,
                attempt,
                attempts,
            )
            journal.warn("boot", f"{label}: rate-limited, waiting {wait}s")
            if attempt == attempts:
                raise
            await asyncio.sleep(min(wait, 3600))


async def _hold_alive(reason: str) -> int:
    """Stay up (and keep the port open) instead of crash-looping on Render.

    An exit here is what turns one bad env var into a deploy that never
    finishes and a login attempt every few seconds. Logging the reason once
    and idling is the sane failure mode for a hosted bot.
    """
    logger.error("starting in degraded mode — %s", reason)
    logger.error("the process stays up so the platform keeps the logs; fix the")
    logger.error("reason above in the dashboard and redeploy when ready.")
    journal.error("boot", f"degraded: {reason}")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):  # pragma: no cover
            pass
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=1800)
        except asyncio.TimeoutError:
            logger.error("still degraded — %s", reason)
    return 0


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

    runtime.settings = settings
    runtime.version = __version__
    runtime.build = __build__
    runtime.started_at = time.time()

    # open the HTTP port before anything can fail: Render/Koyeb polls it while
    # the bot dials Telegram, and a port that never opens reads as "server
    # failure" even when the real problem is one missing env var.
    runner = await health.start(settings.port)

    problems = settings.validate()
    runtime.boot_problems = list(problems)
    for problem in problems:
        logger.error("config: %s", problem)
        journal.error("config", problem)
    for note in settings.warnings():
        logger.warning("config: %s", note)
        journal.warn("config", note)

    # A bot with no credentials cannot do anything at all — but exiting turns
    # that into a restart loop that hides the message. Hold the port instead.
    fatal = [p for p in problems if not p.startswith("STRING_SESSION")]
    if fatal:
        reason = "cannot log in to Telegram: " + "; ".join(fatal)[:300]
        logger.error("Copy .env.example to .env and fill it in — see README.md")
        await _hold_alive(reason)
        if runner is not None:
            await runner.cleanup()
        return 0

    # A *bad* session is not fatal any more: the bot runs, downloads work, and
    # /play explains what to fix. Validate it before dialling Telegram so the
    # log says "truncated paste", not "AuthKeyUnregistered" ten lines later.
    problem = session_problem(settings.session_string) if settings.session_string else ""
    if problem:
        logger.error("config: %s", problem)
        journal.error("config", problem)
        logger.error(
            "streaming will stay off until this is fixed — generate a fresh "
            "session with `python -m vyron.tools.session`"
        )
        runtime.boot_problems.append(problem)

    bot = build_bot(settings)
    assistant = None if problem else build_assistant(settings)
    runtime.bot = bot
    runtime.assistant = assistant

    logger.info("starting bot client…")
    try:
        await _start_client(bot, "bot")
        me = await bot.get_me()
    except Exception as exc:
        # Invalid token, blocked network, or a FloodWait longer than the retry
        # window. Either way: say it once, keep the port open, don't loop.
        reason = f"bot login failed ({type(exc).__name__}: {exc})"
        logger.exception(reason)
        journal.error("boot", reason)
        logger.error(
            "check BOT_TOKEN, and that API_ID/API_HASH belong to the same app as "
            "the bot. The deployment stays up; fix the variable and redeploy."
        )
        await _hold_alive(reason)
        if runner is not None:
            await runner.cleanup()
        return 0
    logger.info("connected as @%s", me.username)

    calls = None
    if assistant is not None:
        from pytgcalls import PyTgCalls

        logger.info("starting assistant (voice engine)…")
        try:
            await _start_client(assistant, "assistant")
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

    try:
        await runtime.build_services()
        runtime.mark_ready()
    except Exception as exc:
        reason = f"services failed to start ({type(exc).__name__}: {exc})"
        logger.exception(reason)
        journal.error("boot", reason)
        await _hold_alive(reason)
        if runner is not None:
            await runner.cleanup()
        return 0

    # the interface style is a deployment choice the owner can flip at runtime
    from vyron.modules import uistyle

    await uistyle.load()
    report = await uistyle.verify()
    logger.info(
        "interface: %s (rich api %s) · /start card %d chars, %d buttons → classic %d chars",
        report["style"],
        "yes" if report["rich_api"] else "no",
        report["rich_chars"],
        report["buttons"],
        report["classic_chars"],
    )
    if report.get("fell_back"):
        logger.warning("interface: fell back to the classic (old) UI")
    elif not report["ok"]:
        logger.error("interface: the start card does not render in either lane")

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
        if calls is not None and runtime.primary:
            resumed = await runtime.player.resume_always_on()
            if resumed:
                logger.info("resumed %d 24/7 chat(s)", resumed)

    from vyron.modules import extras as extras_module

    restored_blocks = await extras_module.load(runtime.storage)
    if restored_blocks:
        logger.info("restored %d blocked id(s)", restored_blocks)

    try:
        loaded = register_all(bot)
    except Exception as exc:
        reason = f"handler registration failed ({type(exc).__name__}: {exc})"
        logger.exception(reason)
        journal.error("boot", reason)
        await _hold_alive(reason)
        if runner is not None:
            await runner.cleanup()
        return 0
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

    try:
        await runtime.player.start_background()
    except Exception as exc:  # a broken player must not stop the bot
        logger.exception("player background tasks failed: %s", exc)
        journal.error("boot", "player background tasks failed", exc)
    try:
        # Warm Home in the background: the first Mini App open should not pay
        # for seven yt-dlp searches while the user stares at a spinner.
        runtime.charts.prime()
    except Exception as exc:  # pragma: no cover - never block boot
        logger.debug("chart warm-up skipped: %s", exc)
    from vyron.core import ytdlp_update

    ytdlp_update.start()
    maintenance.start()
    # One cookie refresh before the first search needs it. Backgrounded: a slow
    # COOKIES_URL host must never delay the bots coming online.
    from vyron.core import cookies as cookie_store

    spawn(cookie_store.refresh(settings), name="cookies:boot")

    # A standby is not a spectator for ever: when the old process stops
    # answering, this one takes the call back and resumes 24/7 playback.
    async def _resume_after_promotion() -> None:
        if runtime.player is None or calls is None:
            return
        runtime.player.calls = calls
        try:
            resumed = await runtime.player.resume_always_on()
        except Exception as exc:  # pragma: no cover - never break the beat
            logger.debug("resume after promotion failed: %s", exc)
            return
        if resumed:
            logger.info("resumed %d 24/7 chat(s) after taking over", resumed)

    lease.on_promote(_resume_after_promotion)
    lease.start()
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
        await lease.stop()
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

        # Last resort: keep the port (and the deployment) up with a JSON
        # explanation instead of exiting into a Render restart loop.
        try:
            from vyron.utils import health as health_module

            # bind the message now: `exc` is cleared when the except block ends
            reason = f"startup failed: {type(exc).__name__}: {exc}"

            async def _serve_degraded() -> None:
                runner = await health_module.start_degraded(settings.port, reason)
                if runner is None:
                    return
                # Park forever without burning a wake-up every hour.
                await asyncio.Event().wait()

            logger.error(
                "serving a degraded /health on port %s so the platform keeps the "
                "logs; fix the reason above and redeploy",
                settings.port,
            )
            asyncio.run(_serve_degraded())
        except Exception:  # pragma: no cover - the explanation above still holds
            pass
        sys.exit(1)


if __name__ == "__main__":
    run()
