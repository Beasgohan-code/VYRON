# ---------------------------------------------------------------------------
#  VYRON — power tools
#
#  Group polling      /voteskip [n]  ·  /vskip
#  Owner console      /eval  ·  /vars  ·  /dbstats  ·  /clearcache
#  Lifecycle          announcements when the bot is added to / removed from a chat
#
#  Everything routes through the same rich-card layer as the rest of the bot, so
#  these commands look identical on every client.
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import logging
import os
import shutil
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

from vyron.config import settings
from vyron.core import acl, chatcfg, maintenance
from vyron.core.votes import VoteBoard, clamp_votes
from vyron.runtime import runtime
from vyron.ui import blocks as B
from vyron.ui import rich
from vyron.ui.progress import human_size, human_time, truncate
from vyron.ui.theme import E
from vyron.utils.filters import owner
from vyron.utils.helpers import command_args, display_name, is_chat_admin

logger = logging.getLogger(__name__)

VOTES = VoteBoard()

VAR_KEYS: tuple[tuple[str, str], ...] = (
    ("BOT_USERNAME", "bot"),
    ("BOT_NAME", "name"),
    ("OWNER_ID", "owner"),
    ("SUDO_USERS", "sudoers"),
    ("MONGO_DB", "database"),
    ("DATA_DIR", "data dir"),
    ("DOWNLOADS_DIR", "downloads"),
    ("AUDIO_QUALITY", "audio"),
    ("VIDEO_QUALITY", "video"),
    ("DEFAULT_VOLUME", "volume"),
    ("MAX_QUEUE_SIZE", "queue cap"),
    ("MAX_TRACK_MINUTES", "track cap"),
    ("IDLE_LEAVE_SECONDS", "idle leave"),
    ("STREAM_CACHE_TTL", "stream cache"),
    ("DOWNLOAD_CACHE_HOURS", "file cache"),
    ("SEARCH_RESULTS", "search results"),
    ("PREMIUM_EMOJI", "premium emoji"),
    ("RICH_MESSAGES", "rich cards"),
    ("WEBAPP_URL", "web app"),
    ("PORT", "port"),
    ("LOG_LEVEL", "log level"),
)

_SECRET_HINTS = ("TOKEN", "HASH", "SESSION", "COOKIE", "PASSWORD", "SECRET", "KEY", "URL")


def mask(value: str) -> str:
    """`123456789:AAH…` → `123456789:AAH••••` — safe to paste in a chat."""
    if not value:
        return "—"
    text = str(value)
    if len(text) <= 8:
        return "•" * len(text)
    return text[:6] + "•" * min(8, len(text) - 6)


def _is_secret(key: str) -> bool:
    return any(hint in key.upper() for hint in _SECRET_HINTS)


def var_rows() -> list[tuple[str, str]]:
    """Config snapshot with secrets masked — pure, so it is unit-tested."""
    rows: list[tuple[str, str]] = []
    for key, label in VAR_KEYS:
        value = os.getenv(key)
        if value is None:
            continue
        shown = mask(value) if _is_secret(key) else value
        rows.append((f"<b>{label}</b>", f"<code>{rich.esc(shown or '—')}</code>"))
    return rows


async def run_eval(code: str, client: Client, message: Message) -> str:
    """Execute *code* in an async wrapper and return a human-readable result."""
    started = time.perf_counter()
    buffer = io.StringIO()
    scope: dict[str, object] = {
        "client": client,
        "message": message,
        "app": client,
        "runtime": runtime,
        "settings": settings,
        "asyncio": __import__("asyncio"),
    }
    try:
        body = "\n".join(f"    {line}" for line in code.splitlines()) or "    pass"
        program = f"async def __vyron_eval():\n{body}"
        exec(compile(program, "<vyron-eval>", "exec"), scope)  # noqa: S102 - owner only
        with redirect_stdout(buffer):
            result = await scope["__vyron_eval"]()  # type: ignore[operator]
        output = buffer.getvalue()
        if result is not None:
            output += f"\n{result!r}"
        elapsed = (time.perf_counter() - started) * 1000
        body_text = output.strip() or "<i>no output</i>"
        return (
            B.heading(f"{E('code')} eval", 3)
            + B.note(f"<code>{rich.esc(truncate(code, 300))}</code>")
            + f"<pre>{rich.esc(truncate(body_text, 2600))}</pre>"
            + B.footer(f"{E('clock')} {elapsed:.0f} ms")
        )
    except Exception:  # noqa: BLE001 - anything the snippet raises is the answer
        trace = traceback.format_exc()
        return (
            B.heading(f"{E('warn')} eval failed", 3)
            + B.note(f"<code>{rich.esc(truncate(code, 200))}</code>")
            + f"<pre>{rich.esc(truncate(trace, 2600))}</pre>"
        )


def _directory_size(path: Path) -> tuple[int, int]:
    total = 0
    files = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
                files += 1
    except Exception:
        pass
    return total, files


async def _tally_for(chat_id: int):
    """Current vote tally, threshold and player state for a chat."""
    state = runtime.player.queues.get(chat_id) if runtime.player else None
    needed = clamp_votes(await chatcfg.get(chat_id, "voteskip", 0))
    tally = VOTES.get(chat_id)
    key = f"{state.current.source}:{state.current.id}" if state and state.current else "idle"
    tally.bind(key, needed)
    return tally, needed, state


async def cast_vote(chat_id: int, user_id: int):
    """Cast one vote — shared by `/vskip` and the inline button."""
    tally, needed, state = await _tally_for(chat_id)
    return tally.cast(user_id), tally, needed, state


def _target_user(message: Message) -> int | None:
    """Reply target or a raw id — the same rule for every admin command."""
    replied = message.reply_to_message
    if replied and replied.from_user:
        return int(replied.from_user.id)
    arg = command_args(message).strip().lstrip("@")
    if arg.lstrip("-").isdigit():
        return int(arg)
    return None


def register(client: Client) -> None:
    # ── vote skip ──────────────────────────────────────────────────────────
    @client.on_message(
        filters.command(["voteskip", "vskip", "vs", "skipvotes", "setvoteskip"]) & filters.group
    )
    async def _voteskip(_: Client, message: Message) -> None:
        chat_id = message.chat.id
        user = message.from_user
        arg = command_args(message).strip()

        # `/setvoteskip` alone → what is the threshold right now?
        if message.command[0].lower() == "setvoteskip" and not arg:
            current = clamp_votes(await chatcfg.get(chat_id, "voteskip", 0))
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('shield')} Vote-skip needs <b>{current}</b> votes here."
                    if current
                    else f"{E('info')} Vote-skip is off — <code>/setvoteskip 3</code> to enable."
                ),
                reply_to=message.id,
            )
            return

        # `/voteskip set 5` (admins) changes the threshold
        if arg.lower().startswith(("set", "=")) or arg.isdigit():
            if not user or not await is_chat_admin(client, chat_id, user.id):
                await rich.send(
                    client,
                    chat_id,
                    B.row(B.btn(f"{E('shield')} Only admins can change this", data="v:noop", style="danger")),
                    reply_to=message.id,
                )
                return
            raw = arg.split(maxsplit=1)[-1].lstrip("=")
            needed = clamp_votes(raw)
            await chatcfg.set(chat_id, "voteskip", needed)
            state = runtime.player.queues.get(chat_id) if runtime.player else None
            if state and state.current:
                VOTES.get(chat_id).bind(f"{state.current.source}:{state.current.id}", needed)
            await rich.send(
                client,
                chat_id,
                B.heading(f"{E('check')} vote-skip updated", 3)
                + B.kv(
                    [
                        (f"{E('shield')} votes needed", f"<b>{needed or 'disabled'}</b>"),
                        (f"{E('info')} who", "<i>admins can always skip directly</i>"),
                    ]
                )
                + B.note("Everyone else votes with <code>/vskip</code>."),
                reply_to=message.id,
            )
            return

        if not runtime.player:
            return
        state = runtime.player.queues.get(chat_id)
        if not state or not state.current:
            await rich.send(
                client, chat_id, B.note(f"{E('moon')} Nothing is playing."), reply_to=message.id
            )
            return

        needed = clamp_votes(await chatcfg.get(chat_id, "voteskip", 0))
        tally = VOTES.get(chat_id)
        tally.bind(f"{state.current.source}:{state.current.id}", needed)

        if user and await is_chat_admin(client, chat_id, user.id):
            await runtime.player.skip(chat_id, count=1)
            return

        if not tally.enabled:
            await rich.send(
                client,
                chat_id,
                B.note(
                    f"{E('info')} Vote-skip is off here. "
                    "Admins can enable it with <code>/voteskip set 3</code>."
                ),
                reply_to=message.id,
            )
            return

        outcome = tally.cast(user.id if user else 0)
        if outcome == "duplicate":
            await rich.send(
                client,
                chat_id,
                B.note(f"{E('info')} You already voted — {tally.remaining} more needed."),
                reply_to=message.id,
            )
            return
        if outcome == "passed":
            tally.reset()
            skipped = await runtime.player.skip(chat_id, count=1)
            await rich.send(
                client,
                chat_id,
                B.heading(f"{E('skip')} skipped by vote", 3)
                + B.kv(
                    [
                        ("votes", f"<b>{needed}/{needed}</b>"),
                        ("now", rich.esc(truncate(skipped.title, 42)) if skipped else "<i>queue empty</i>"),
                    ]
                ),
                reply_to=message.id,
            )
            return

        await rich.send(
            client,
            chat_id,
            B.note(
                f"{E('check')} <b>Vote counted</b> — {tally.count}/{needed}\n"
                f"{E('clock')} {tally.remaining} more to skip "
                f"<b>{rich.esc(truncate(state.current.title, 34))}</b>"
            )
            + B.row(B.btn(f"{E('skip')} Vote to skip", data="v:vote", style="danger")),
            reply_to=message.id,
        )

    # ── /eval ──────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["eval", "exec"]) & owner)
    async def _eval(_: Client, message: Message) -> None:
        code = command_args(message)
        if code.startswith("```"):
            code = code.strip("`")
            if code.startswith("python"):
                code = code[6:]
        if not code.strip():
            await rich.send(
                client,
                message.chat.id,
                B.note(
                    f"{E('code')} Usage: <code>/eval await message.reply('hi')</code>\n"
                    "Only the owner can run this."
                ),
                reply_to=message.id,
            )
            return
        card = await run_eval(code.strip(), client, message)
        await rich.send(client, message.chat.id, card, reply_to=message.id)

    # ── /vars ──────────────────────────────────────────────────────────────
    @client.on_message(filters.command(["vars", "variables", "config"]) & owner)
    async def _vars(_: Client, message: Message) -> None:
        rows = var_rows()
        card = (
            B.heading(f"{E('settings')} configuration", 3)
            + B.table(None, rows)
            + B.note(
                f"{E('warn')} secrets are masked — full values are never sent to a chat."
            )
        )
        if message.chat.type != "private":
            try:
                await rich.send(client, settings.owner_id or message.from_user.id, card)
                await rich.send(
                    client,
                    message.chat.id,
                    B.note(f"{E('check')} Sent to your DM."),
                    reply_to=message.id,
                )
                return
            except Exception:
                pass
        await rich.send(client, message.chat.id, card, reply_to=message.id)

    # ── /dbstats ───────────────────────────────────────────────────────────
    @client.on_message(filters.command(["dbstats", "dbb", "storage"]) & owner)
    async def _dbstats(_: Client, message: Message) -> None:
        storage = runtime.storage
        if storage is None:
            await rich.send(client, message.chat.id, B.note(f"{E('warn')} storage is not ready"))
            return
        chats = await storage.all_chat_ids()
        counters = await storage.counters()
        rows = [
            (f"{E('cloud')} backend", f"<b>{storage.backend}</b>"),
            (f"{E('users')} chats", f"<b>{len(chats)}</b>"),
            (f"{E('note')} tracks played", f"<b>{counters.get('tracks', 0)}</b>"),
            (f"{E('download')} downloads", f"<b>{counters.get('downloads', 0)}</b>"),
        ]
        data_dir = Path(settings.data_dir)
        if storage.backend == "json":
            path = data_dir / "vyron.json"
            size = path.stat().st_size if path.is_file() else 0
            rows.append((f"{E('id')} file", f"<code>{rich.esc(str(path))}</code> · {human_size(size)}"))
        else:
            rows.append((f"{E('id')} database", f"<code>{rich.esc(settings.mongo_db)}</code>"))
        cache_bytes = runtime.downloader.cache_size() if runtime.downloader else 0
        files = 0
        if runtime.downloader:
            cache_dir = Path(settings.downloads_dir)
            cache_bytes, files = _directory_size(cache_dir)
        rows.append((f"{E('cloud')} cache", f"<b>{human_size(cache_bytes)}</b> · {files} files"))
        rows.append((f"{E('clock')} uptime", f"<b>{human_time(runtime.uptime)}</b>"))
        sweep = maintenance.status()
        if sweep.get("last"):
            rows.append(
                (
                    f"{E('spark')} last sweep",
                    f"{human_time(max(0.0, time.time() - float(sweep['last'])))} ago · "
                    f"{sweep['files']} files · {sweep['rows']} rows",
                )
            )
        else:
            rows.append(
                (
                    f"{E('spark')} housekeeping",
                    f"every <b>{sweep['every_hours']}h</b>"
                    if int(sweep["every_hours"]) > 0
                    else "<i>disabled</i>",
                )
            )
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('stats')} storage", 3) + B.kv(rows),
            reply_to=message.id,
        )

    # ── /dbcleanup ─────────────────────────────────────────────────────────
    @client.on_message(filters.command(["dbcleanup", "cleanupdb", "prune"]) & owner)
    async def _dbcleanup(_: Client, message: Message) -> None:
        storage = runtime.storage
        if storage is None:
            await rich.send(client, message.chat.id, B.note(f"{E('warn')} storage is not ready"))
            return
        arg = command_args(message).strip()
        days = int(arg) if arg.isdigit() else 30
        status = await rich.send(
            client,
            message.chat.id,
            f"{E('clock')} {B.think()} <b>Pruning rows older than {days} days…</b>",
            reply_to=message.id,
            editable=True,
        )
        try:
            removed = await storage.prune(days)
        except Exception as exc:
            logger.warning("prune failed: %s", exc)
            markup = B.note(f"{E('warn')} Cleanup failed: {rich.esc(truncate(str(exc), 140))}")
        else:
            total = sum(int(v) for v in removed.values())
            markup = (
                B.heading(f"{E('check')} database pruned", 3)
                + B.kv(
                    [
                        (f"{E('clock')} older than", f"<b>{days} days</b>"),
                        ("history rows", f"<b>{removed.get('history', 0)}</b>"),
                        ("favourite rows", f"<b>{removed.get('favorites', 0)}</b>"),
                        (f"{E('cloud')} backend", f"<b>{storage.backend}</b>"),
                    ]
                )
                + B.note(
                    "Nothing to remove — the database is already tidy."
                    if not total
                    else f"{E('spark')} {total} row{'s' if total != 1 else ''} removed."
                )
            )
        if status:
            await rich.edit(client, message.chat.id, status.id, markup)
        else:
            await rich.send(client, message.chat.id, markup)

    # ── /clearcache ────────────────────────────────────────────────────────
    @client.on_message(filters.command(["clearcache", "rmdownloads", "purgefiles", "cleanup"]) & owner)
    async def _clearcache(_: Client, message: Message) -> None:
        target = Path(settings.downloads_dir)
        removed = 0
        freed = 0
        if target.is_dir():
            for entry in target.glob("*"):
                try:
                    if entry.is_file():
                        freed += entry.stat().st_size
                        entry.unlink()
                        removed += 1
                    elif entry.is_dir():
                        freed += _directory_size(entry)[0]
                        shutil.rmtree(entry, ignore_errors=True)
                        removed += 1
                except Exception:
                    continue
        if runtime.downloader and hasattr(runtime.downloader, "clear"):
            try:
                runtime.downloader.clear()
            except Exception:
                pass
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('check')} cache cleared", 3)
            + B.kv(
                [
                    ("files removed", f"<b>{removed}</b>"),
                    ("space freed", f"<b>{human_size(freed)}</b>"),
                ]
            ),
            reply_to=message.id,
        )

    # ── runtime sudoers ────────────────────────────────────────────────────
    @client.on_message(filters.command(["addsudo", "sudoit"]) & owner)
    async def _addsudo(_: Client, message: Message) -> None:
        target = _target_user(message)
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Reply to someone or send <code>/addsudo 123456789</code>."),
                reply_to=message.id,
            )
            return
        added = await acl.add(runtime.storage, target)
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('check')} <code>{target}</code> can now operate the bot."
                if added
                else f"{E('info')} <code>{target}</code> already had access."
            ),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["delsudo", "rmsudo", "removesudo"]) & owner)
    async def _delsudo(_: Client, message: Message) -> None:
        target = _target_user(message)
        if target is None:
            await rich.send(
                client,
                message.chat.id,
                B.note(f"{E('info')} Reply to someone or send <code>/delsudo 123456789</code>."),
                reply_to=message.id,
            )
            return
        if target == int(settings.owner_id or 0):
            await rich.send(
                client, message.chat.id, B.note(f"{E('shield')} The owner cannot be demoted."),
                reply_to=message.id,
            )
            return
        removed = await acl.remove(runtime.storage, target)
        await rich.send(
            client,
            message.chat.id,
            B.note(
                f"{E('cross')} <code>{target}</code> lost bot access."
                if removed
                else f"{E('info')} <code>{target}</code> isn't a runtime sudoer "
                "(env SUDO_USERS can only change in .env)."
            ),
            reply_to=message.id,
        )

    @client.on_message(filters.command(["sudolist", "sudos"]) & owner)
    async def _sudolist(_: Client, message: Message) -> None:
        env_ids = {int(i) for i in settings.sudo_users}
        runtime_ids = acl.extra_ids()
        rows = []
        for user_id in acl.roster():
            if user_id == int(settings.owner_id or 0):
                role = "owner"
            elif user_id in env_ids:
                role = "env"
            else:
                role = "granted"
            name = ""
            try:
                user = await client.get_users(user_id)
                name = f" · {rich.esc(display_name(user))}"
            except Exception:
                pass
            rows.append((f"<code>{user_id}</code>", f"{role}{name}"))
        markup = (
            B.heading(f"{E('shield')} who can operate", 3)
            + B.kv(rows or [("—", "nobody")])
            + B.note(
                f"{E('bolt')} {len(runtime_ids)} granted from Telegram · "
                "manage with <code>/addsudo</code> and <code>/delsudo</code>."
            )
        )
        await rich.send(client, message.chat.id, markup, reply_to=message.id)

    # ── lifecycle announcements ────────────────────────────────────────────
    @client.on_message(filters.new_chat_members, group=-9)
    async def _added(_: Client, message: Message) -> None:
        me = client.me if hasattr(client, "me") else None
        added = message.new_chat_members or []
        if not any(member.id == getattr(me, "id", None) for member in added):
            return
        try:
            await runtime.storage.set_chat_setting(message.chat.id, "served_at", int(time.time()))
        except Exception:
            pass
        by = display_name(message.from_user) if message.from_user else "someone"
        await rich.send(
            client,
            message.chat.id,
            B.heading(f"{E('rocket')} thanks for adding me", 3)
            + B.note(
                f"Added by <b>{rich.esc(by)}</b>.\n"
                "Start a voice chat, then <code>/play your song</code>."
            )
            + B.grid(
                [
                    B.btn(f"{E('play')} Play", data="v:play:lofi", style="primary"),
                    B.btn(f"{E('web')} Web app", data="v:app"),
                    B.btn(f"{E('tools')} Help", data="v:help:main"),
                    B.btn(f"{E('settings')} Settings", data="v:settings"),
                ],
                columns=2,
            ),
        )

    @client.on_message(filters.left_chat_member, group=-9)
    async def _left(_: Client, message: Message) -> None:
        me = client.me if hasattr(client, "me") else None
        left = message.left_chat_member
        if not left or left.id != getattr(me, "id", None):
            return
        VOTES.drop(message.chat.id)
        if settings.logger_id:
            try:
                await rich.send(
                    client,
                    settings.logger_id,
                    B.note(
                        f"{E('info')} removed from <b>{rich.esc(truncate(message.chat.title or 'chat', 40))}</b> "
                        f"(<code>{message.chat.id}</code>)"
                    ),
                )
            except Exception:
                pass


__all__ = ["VOTES", "mask", "register", "run_eval", "var_rows"]
