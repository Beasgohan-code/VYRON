# ---------------------------------------------------------------------------
#  VYRON — cards
#
#  Two visual languages, one source of truth:
#    · rich cards   — headings, tables, dividers, collapsible sections and
#                     *coloured* in-message buttons (Bot API 10.3 / richgram)
#    · live cards   — classic HTML that is edited in place every few seconds
#
#  UI building blocks adapted from richgram by BadmundaXd
#  (https://github.com/Badmunda05/richgram, MIT) — credited in README.
# ---------------------------------------------------------------------------
from __future__ import annotations

import time

from typing import Iterable

from vyron.config import settings
from vyron.core.lyrics import LyricsResult
from vyron.core.queue import ChatState, Track
from vyron.ui import blocks as B
from vyron.ui.blocks import esc
from vyron.ui.progress import (
    fmt_duration,
    human_clock,
    human_size,
    length_label,
    human_time,
    percentage,
    progress_bar,
    truncate,
)
from vyron.ui.progress import compact_number
from vyron.ui.theme import BRAND, BRAND_DISPLAY, BULLET, DASH, E, SPARK, small_caps

DOT = "·"

# ── shared bits ─────────────────────────────────────────────────────────────
def _requester(track: Track) -> str:
    if not track.requested_name:
        return ""
    return f'<a href="tg://user?id={int(track.requested_by)}">{esc(truncate(track.requested_name, 28))}</a>'


def _source_badge(track: Track) -> str:
    return small_caps(track.source[:12] or "youtube")


def _watch_link(track: Track) -> str:
    url = track.watch_url
    return f'<a href="{esc(url)}">{esc(truncate(track.title, 68))}</a>' if url else esc(truncate(track.title, 68))


def progress_block(state: ChatState, track: Track) -> str:
    """Two monospace lines: the bar, then the clock. Same width every time."""
    elapsed = state.elapsed()
    total = track.duration or 0
    bar = progress_bar(elapsed, total, length=16)
    if not total:
        return f"<code>{bar}</code>\n<code>{fmt_duration(elapsed)} · live</code>"
    return (
        f"<code>{bar}</code>\n"
        f"<code>{fmt_duration(elapsed)}</code> · {percentage(elapsed, total)}% · "
        f"<code>{fmt_duration(total)}</code>"
    )


# ── start ───────────────────────────────────────────────────────────────────
def start_card(
    name: str,
    stats: dict,
    *,
    streaming: bool = True,
    live: dict | None = None,
    greeting: str | None = None,
    uptime: float | None = None,
) -> str:
    """The first card anyone sees: hello, status, what it does, how to start.

    The order is the order a person reads on a phone:

        1. who is talking to me        the masthead + "hello <name>"
        2. is it working               status · uptime · reach  (ONE block)
        3. what does it do for me      four features, one line each
        4. what do I tap               the buttons

    ``live`` is filled when this chat already has something playing, so a
    returning user gets the current track instead of the setup guide.
    ``greeting`` is computed by the caller from the server clock — the card
    never invents a local time it cannot know.
    """
    chats = int(stats.get("chats", 0) or 0)
    tracks = int(stats.get("tracks", 0) or 0)
    who = esc(truncate(name, 40))

    hello = small_caps(esc(greeting).lower()) if greeting else small_caps("hello")
    # Two short lines, not a paragraph: a wall of text is the first thing a new
    # user skips, and the four features below say the same thing better.
    intro = (
        f"{hello} <b>{who}</b> 𓂀\n"
        f"i'm <b>{BRAND_DISPLAY}</b> — your music player for Telegram. "
        "Play in a voice chat, listen in the app, keep the file."
    )

    status_rows = [
        (
            "live" if streaming else "warn",
            "status",
            f"{B.pill('online', 'ok')} · voice chat ready"
            if streaming
            else f"{B.pill('limited', 'warn')} · no <code>STRING_SESSION</code>",
        )
    ]
    if uptime:
        status_rows.append(("clock", "uptime", f"<b>{human_clock(uptime)}</b>"))
    status_rows.append(
        ("users", "reach", f"<b>{_compact(chats)}</b> chats · <b>{_compact(tracks)}</b> tracks")
    )
    status_rows.append(("spark", "version", f"v<b>{_version()}</b> · {small_caps('rich ui')}"))
    status_block = B.fields(status_rows)

    features = B.items(
        [
            ("play", "play", "streams into the voice chat, one tap to skip"),
            ("search", "find", "a title you half remember is enough"),
            ("download", "save", "MP3 320 or MP4 720p, cover art attached"),
            ("interface", "player", "the whole player, inside Telegram"),
        ]
    )

    guide = B.details(
        f"{E('rocket')} <b>Set it up in three steps</b>",
        B.bullets(
            [
                "Add the bot and its assistant account to the group",
                "Give them <b>manage voice chats</b> and <b>delete messages</b>",
                "Start a voice chat, then send <code>/play believer</code>",
            ],
            ordered=True,
        )
        + B.note(
            "In a private chat nothing else is needed — <code>/song</code> sends "
            "the file straight here."
        ),
        open=False,
    )

    buttons = (
        B.row(
            B.btn(f"{E('play')} Open the player", data="v:app", style="primary"),
            B.btn(f"{E('queue')} All commands", data="v:help:main"),
        )
        + B.row(
            B.btn(
                f"{E('rocket')} Add to a group",
                url=f"https://t.me/{settings.bot_username}?startgroup=true",
            ),
            B.btn(f"{E('info')} About", data="v:about"),
        )
        + B.row(
            B.btn(f"{E('chat')} Support", url=settings.support_chat, style="link"),
            B.btn(f"{E('star')} Updates", url=settings.updates_channel, style="link"),
        )
    )

    if live:
        title = esc(truncate(str(live.get("title") or "Unknown"), 48))
        state_word = "paused" if live.get("paused") else "playing"
        duration = int(live.get("duration") or 0)
        rows = [
            ("headphones", "in this chat", f"{B.pill(state_word, 'live')} <b>{title}</b>"),
            ("user", "artist", esc(truncate(str(live.get("artist") or "—"), 32))),
            ("clock", "length", f"<b>{fmt_duration(duration)}</b>"),
        ]
        position = int(live.get("position") or 0)
        if position and duration:
            rows.insert(
                2,
                (
                    "live",
                    "position",
                    f"<code>{progress_bar(position, duration, length=10)}</code> "
                    f"{fmt_duration(position)} / {fmt_duration(duration)}",
                ),
            )
        queued = int(live.get("queue") or 0)
        rows.append(
            (
                "queue",
                "up next",
                f"<b>{queued}</b> " + ("track" if queued == 1 else "tracks") + " queued"
                if queued
                else "<i>nothing queued — it will pick something</i>",
            )
        )
        # A returning listener asked for the music, not the manual.
        return (
            B.banner("welcome back", glyph="hello")
            + B.context(intro)
            + B.section_title("this chat")
            + B.fields(rows)
            + B.actions(
                B.row(
                    B.btn(
                        f"{E('resume')} Resume" if live.get("paused") else f"{E('pause')} Pause",
                        data="v:resume" if live.get("paused") else "v:pause",
                        style="primary",
                    ),
                    B.btn(f"{E('skip')} Skip", data="v:skip"),
                ),
                B.row(
                    B.btn(f"{E('queue')} Queue", data="v:queue"),
                    B.btn(f"{E('stop')} Stop", data="v:stop", style="danger"),
                ),
                B.row(
                    B.btn(f"{E('interface')} Open the player", data="v:app"),
                    B.btn(f"{E('queue')} All commands", data="v:help:main"),
                ),
            )
            + B.footer(_stamp(chats, tracks))
        )

    return (
        B.banner("welcome", glyph="hello")
        + B.context(intro)
        + status_block
        + B.section_title("what i can do")
        + features
        + B.section_title("getting started")
        + guide
        + B.actions(buttons)
        + B.footer(_stamp(chats, tracks))
    )


def _stamp(chats: int, tracks: int) -> str:
    """The one footer line every welcome/status card ends with."""
    return (
        f"{_compact(chats)} chats · {_compact(tracks)} tracks played · "
        f"v{_version()} · {small_caps('rich ui')}"
    )


def _compact(value: int) -> str:
    try:
        return compact_number(value)
    except Exception:  # pragma: no cover
        return str(value)


def _version() -> str:
    try:
        from vyron import __version__

        return __version__
    except Exception:  # pragma: no cover
        return "1.0"


# ── help ────────────────────────────────────────────────────────────────────
_HELP: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "main": (
        "Basics",
        [
            ("/start", "open the home card"),
            ("/play <song|link>", "stream audio in the voice chat"),
            ("/song <song|link>", "send the MP3 here"),
            ("/search <text>", "browse results, then pick"),
            ("/lyrics [song]", "lyrics for the current track"),
            ("/ping", "latency + uptime"),
        ],
    ),
    "playback": (
        "Playback",
        [
            ("/pause · /resume", "hold or continue the stream"),
            ("/skip [n]", "jump forward n tracks"),
            ("/seek 1:30", "jump inside the track"),
            ("/volume 1-200", "set assistant volume"),
            ("/loop off|one|all", "cycle the repeat mode"),
            ("/shuffle", "shuffle what is queued"),
            ("/stop", "end the session and leave"),
            ("/np", "refresh the now-playing card"),
        ],
    ),
    "queue": (
        "Queue",
        [
            ("/queue [page]", "paginated queue view"),
            ("/remove <pos>", "drop one entry"),
            ("/move <from> <to>", "reorder the queue"),
            ("/jump <pos>", "play that entry right now"),
            ("/clearqueue", "empty the queue, keep playing"),
            ("/playlist <url>", "queue up to 50 tracks"),
        ],
    ),
    "tools": (
        "Tools",
        [
            ("/fav · /fav", "save and list favourites"),
            ("/history", "your recently played"),
            ("/settings", "per-chat defaults"),
            ("/language", "English · हिन्दी · മലയാളം · ਪੰਜਾਬੀ"),
            ("/voice", "voice engine: on/off, calls, quality"),
            ("/thumbnail", "your own artwork behind the poster"),
            ("/logger", "mirror warnings to a channel (owner)"),
            ("/247", "toggle 24/7 mode"),
            ("/app", "open the player web app"),
            ("/api", "the music API (keys, docs)"),
            ("/exportpl <name>", "playlist → JSON file"),
            ("/importpl", "reply to that file to restore it"),
        ],
    ),
    "social": (
        "Groups",
        [
            ("/voteskip set 3", "require votes before a skip"),
            ("/voteskip", "cast your vote"),
            ("/cplayset <id>", "stream into a specific channel"),
            ("/cplay · /cstop · /cseek", "drive the linked channel's stream"),
            ("/cvolume · /ceffects", "channel volume and audio effects"),
            ("/similar", "tracks like the one playing"),
            ("/skip <song>", "insert a track up front"),
            ("/savepl [name]", "save the queue to a playlist"),
            ("/playlists · /playlists <name>", "list and queue your playlists"),
            ("/song", "get the MP3 in the chat"),
            ("/locks · /antiflood", "content locks and flood control"),
            ("/gadmin", "the group manager panel"),
            ("/rules · /setrules", "read or set this chat's rules"),
            ("/chatinfo", "id, members, slow mode, invites"),
            ("/settitle · /setdesc", "rename the chat"),
            ("/setchatphoto · /delchatphoto", "chat picture from a reply"),
            ("/slowmode 30s|off", "space out messages"),
            ("/invitelink · /revokeinvite", "rotate the invite link"),
            ("/approve · /approved", "exempt trusted members"),
            ("/zombies [kick]", "clean up deleted accounts"),
            ("/report", "flag a message to the admins"),
            ("/mydata", "download everything the bot knows about you"),
            ("/forgetme", "delete your history, favourites and playlists"),
        ],
    ),
    "power": (
        "Owner",
        [
            ("/eval <code>", "run python in the bot process"),
            ("/vars", "configuration snapshot (masked)"),
            ("/dbstats", "storage size and counters"),
            ("/sudoers", "who can operate the bot"),
            ("/clearqueue", "wipe downloads and temp files"),
            ("/dbcleanup 30", "drop history older than N days"),
            ("/addsudo · /delsudo", "grant or revoke bot access"),
            ("/sudolist", "who can operate the bot"),
            ("/stats · /vc", "usage and live sessions"),
            ("/api", "music API card, docs and endpoints"),
            ("/getapi [label] [scopes=…]", "mint an API key (owner)"),
            ("/apikeys · /revoke · /rotatekey", "manage API keys (owner)"),
            ("/apiusage", "API traffic per key (owner)"),
            ("/apitoken", "owner token — mint, rotate, revoke"),
            ("/apitoken revoke", "kill every owner token, instantly"),
            ("/logs [errors|warn|info]", "owner journal: start, stop, errors"),
            ("/logs export · /logs clear", "download or empty the journal"),
            ("/assistant · /setname", "rebrand the voice-chat account"),
            ("/setbio · /setpfp", "bio and profile picture"),
        ],
    ),
}


def _prefix_line() -> str:
    """`/play !play .play ?play #play` — the configured set, as a hint."""
    from vyron.utils.commands import prefixes

    return "  ".join(f"{prefix}play" for prefix in prefixes())


def help_card(section: str = "main") -> str:
    section = section if section in _HELP else "main"
    title, rows = _HELP[section]
    body = B.table(
        None,
        [(B.code(cmd), esc(desc)) for cmd, desc in rows],
    )
    tips = B.details(
        f"{E('info')} <b>Good to know</b>",
        B.bullets(
            [
                f"Any of these prefixes works: <code>{esc(_prefix_line())}</code>",
                "A link, a playlist, a reply to a file or plain words all work",
                "In groups only admins can control playback",
                "Anything you played once replays instantly — it is cached",
            ]
        ),
    )
    tabs = ""
    for key, label in (
        ("main", "Basics"),
        ("playback", "Playback"),
        ("queue", "Queue"),
        ("tools", "Tools"),
        ("social", "Groups"),
        ("power", "Owner"),
    ):
        style = "primary" if key == section else None
        tabs += B.btn(("• " if key == section else "") + label, data=f"v:help:{key}", style=style)
    return (
        B.banner(f"commands · {title}", glyph="tools", meta=f"<i>{len(rows)}</i>")
        + B.context(
            "Everything the bot can do, by area. The tabs below switch this list "
            "in place — nothing to scroll back for."
        )
        + body
        + tips
        + B.actions(
            B.row(tabs),
            B.row(
                B.btn(f"{E('back')} Start", data="v:start"),
                B.btn(f"{E('close')} Close", data="v:close", style="danger"),
            ),
        )
        + B.footer(f"@{settings.bot_username} {BULLET} {BRAND} {BULLET} all prefixes supported")
    )

# ── now playing (live, editable) ────────────────────────────────────────────
def now_playing_card(state: ChatState, track: Track | None = None) -> str:
    """The live card — classic HTML only, because it is edited in place."""
    track = track or state.current
    if not track:
        return (
            f"{E('moon')} <b>Nothing is playing</b>\n"
            f"<blockquote>Send <code>/play</code> with a song name, a link or a reply.</blockquote>"
        )

    status = "paused" if state.paused else "streaming"
    glyph = E("pause") if state.paused else E("live")
    requester = _requester(track)
    meta = (
        f"{esc(truncate(track.uploader, 32) or 'unknown artist')}"
        f" · {fmt_duration(track.duration)} · {_source_badge(track)}"
    )
    if requester:
        meta += f" · {requester}"

    upcoming = state.queue[0] if state.queue else None
    next_line = ""
    if upcoming:
        next_line = (
            f"\n◈ {E('queue')} <b>{small_caps('up next')}</b>: "
            f"{esc(truncate(upcoming.title, 40))} · {fmt_duration(upcoming.duration)}"
        )

    flags = []
    if state.autoplay:
        flags.append("autoplay")
    if state.always_on:
        flags.append("24/7")
    tail = f"{state.volume}% volume · {state.loop.label} loop · {len(state.queue)} queued"
    if flags:
        tail += f" · {', '.join(flags)}"

    return (
        f"◈ {glyph} <b>{small_caps('now playing')}</b>: <b>{status}</b>\n"
        f"<blockquote><b>{_watch_link(track)}</b>\n{meta}</blockquote>\n"
        f"{progress_block(state, track)}{next_line}\n"
        f"<i>{tail}</i>"
    )

def now_playing_caption(state: ChatState, catalog=None) -> str:
    """Caption for the poster: the live clock, nothing the picture already says.

    ``catalog`` is an i18n catalog; without one the English labels are used.
    """
    track = state.current
    if not track:
        return ""

    def label(key: str, fallback: str, **values) -> str:
        return catalog.t(key, **values) if catalog is not None else fallback.format(**values)

    elapsed = state.elapsed()
    total = track.duration or 0
    bar = progress_bar(elapsed, total, length=18)
    clock_line = (
        f"<code>{fmt_duration(elapsed)}</code> · {percentage(elapsed, total)}% · "
        f"<code>{fmt_duration(total)}</code>"
        if total
        else f"<code>{fmt_duration(elapsed)}</code> · live"
    )
    status = (
        label("np.paused", "paused") if state.paused else label("np.streaming", "streaming")
    )
    lines = [f"<code>{bar}</code>", f"{E('live')} {status} · {clock_line}"]

    if state.queue:
        upcoming = state.queue[0]
        lines.append(
            f"{E('queue')} <i>{label('np.up_next', 'up next')}</i> "
            f"{esc(truncate(upcoming.title, 34))}"
        )
    requester = _requester(track)
    if requester:
        lines.append(f"{E('user')} {requester}")
    # A bare "100%" at the end of a caption reads like a download figure, so
    # every flag now says what it is, and mute gets a word instead of a zero.
    flags = [
        f"{E('volume')} {int(state.volume)}%" if state.volume else f"{E('mute')} muted",
        f"{E('loop')} {state.loop.label}" if getattr(state.loop, "value", "off") != "off" else "",
        f"{E('clock')} 24/7" if state.always_on else "",
        label("np.queued", "{count} queued", count=len(state.queue)) if state.queue else "",
    ]
    tail = " · ".join(flag for flag in flags if flag)
    if tail:
        lines.append(f"<i>{tail}</i>")
    return "\n".join(lines)


def now_playing_dm_caption(
    track: Track,
    *,
    chat_title: str = "",
    state: ChatState | None = None,
    catalog=None,
) -> str:
    """The "this just started from the app" note that lands in a DM."""
    where = f" in <b>{esc(truncate(chat_title, 40))}</b>" if chat_title else ""
    meta = " · ".join(
        part
        for part in (
            esc(truncate(track.uploader or "", 30)),
            fmt_duration(track.duration) if track.duration else "",
        )
        if part
    )
    body = (
        f"{E('play')} <b>Playing{where}</b>\n"
        f"<blockquote>{esc(truncate(track.title, 60))}"
        + (f"\n{meta}" if meta else "")
        + "</blockquote>"
    )
    if state is not None:
        body += "\n" + now_playing_caption(state, catalog)
    return body


def _track_fields(track: Track, *, extra: tuple[str, str, str] | None = None) -> str:
    """The three facts every "this track" card shows, in the same order."""
    rows: list[tuple[str, str, str]] = [
        ("note", "title", f"<b>{esc(truncate(track.title, 56))}</b>"),
        ("user", "artist", esc(truncate(track.uploader, 32) or "unknown artist")),
        ("clock", "length", f"<b>{length_label(track)}</b>"),
    ]
    if extra:
        rows.append(extra)
    return B.fields(rows)


def queued_card(track: Track, position: int) -> str:
    """`/play` → it is in the queue. Say where, and give the next action."""
    return (
        B.banner("added to queue", glyph="check", meta=f"<i>#{position}</i>")
        + B.context(
            "It plays after what is already queued — nothing was interrupted."
        )
        + _track_fields(track, extra=("queue", "position", f"<b>#{position}</b> in the queue"))
        + B.actions(
            B.row(
                B.btn(f"{E('queue')} Queue", data="v:queue", style="primary"),
                B.btn(f"{E('now')} Now playing", data="v:np"),
            ),
            B.row(
                B.btn(f"{E('now')} Playing", data="v:np"),
                B.btn(f"{E('close')} Close", data="v:close"),
            ),
        )
        + B.footer(f"{E('download')} the same track is never queued twice")
    )


def started_card(track: Track) -> str:
    """`/play` → it started right away."""
    return (
        B.banner("now streaming", glyph="play")
        + B.context("The assistant joined the voice chat and started this track.")
        + _track_fields(track)
        + B.actions(
            B.row(
                B.btn(f"{E('pause')} Pause", data="v:pause", style="primary"),
                B.btn(f"{E('skip')} Skip", data="v:skip"),
                B.btn(f"{E('stop')} Stop", data="v:stop", style="danger"),
            ),
            B.row(
                B.btn(f"{E('queue')} Queue", data="v:queue"),
                B.btn(f"{E('now')} Now playing", data="v:np"),
            ),
        )
        + B.footer(f"{E('spark')} {BRAND} {BULLET} /song sends the MP3 here")
    )


# ── queue ───────────────────────────────────────────────────────────────────
def queue_card(state: ChatState, page: int = 0, per_page: int = 8) -> tuple[str, int]:
    tracks = state.queue
    pages = max(1, (len(tracks) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    window = tracks[page * per_page : (page + 1) * per_page]

    if tracks:
        body = B.table(
            ["#", "title", "time"],
            [
                (
                    f"<b>{page * per_page + index + 1}</b>",
                    esc(truncate(track.title, 44)),
                    fmt_duration(track.duration),
                )
                for index, track in enumerate(window)
            ],
        )
    else:
        body = B.note(f"{E('moon')} The queue is empty — add something with <code>/play</code>.")

    now = ""
    if state.current:
        now = B.fields(
            [
                (
                    "live",
                    "playing",
                    f"{esc(truncate(state.current.title, 44))} · "
                    f"{fmt_duration(state.elapsed())} / {fmt_duration(state.current.duration)}",
                )
            ]
        )

    nav = ""
    if page > 0:
        nav += B.btn("‹ prev", data=f"v:queue:{page - 1}")
    nav += B.btn(f"{page + 1} / {pages}", data="v:noop", style="primary")
    if page + 1 < pages:
        nav += B.btn("next ›", data=f"v:queue:{page + 1}")

    return (
        B.banner("queue", glyph="queue", meta=f"<i>{len(tracks)}</i>")
        + now
        + body
        + B.actions(
            B.row(
                B.btn(f"{E('shuffle')} Shuffle", data="v:shuffle", style="success"),
                B.btn(f"{E('now')} Playing", data="v:np"),
                B.btn(f"{E('stop')} Clear", data="v:clearqueue", style="danger"),
            ),
            B.row(nav) if nav else "",
        )
        + B.footer(
            f"{fmt_duration(sum(t.duration for t in tracks))} of music · "
            f"{state.loop.label} loop · {state.volume}% volume · "
            f"autoplay {'on' if state.autoplay else 'off'}"
        ),
        pages,
    )

# ── search & downloads ──────────────────────────────────────────────────────
def _meta_line(track: Track) -> str:
    """`channel · 3:45 · 2.4M plays` — only the parts we actually know."""
    bits: list[str] = []
    if track.uploader:
        bits.append(esc(truncate(track.uploader, 28)))
    bits.append(f"<code>{length_label(track)}</code>")
    if getattr(track, "views", 0):
        bits.append(f"{compact_number(track.views)} plays")
    return f" {DOT} ".join(bits)


def search_card(query: str, tracks: Iterable[Track], *, mode: str = "play") -> str:
    """Results as a ranked list: the top hit is marked and carries the artwork."""
    tracks = list(tracks)
    verb = "play" if mode == "play" else "download"
    if not tracks:
        return (
            B.banner("no results", glyph="search")
            + B.context(
                f"Nothing came back for <b>{esc(truncate(query, 48))}</b>.\n"
                "Try the artist name, or paste a link."
            )
            + B.actions(
                B.row(
                    B.btn(f"{E('play')} Try /play", data="v:help:playback", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close", style="danger"),
                )
            )
        )

    rows: list[str] = []
    for index, track in enumerate(tracks):
        title = _watch_link(track)
        if index == 0:
            title = f"<mark>{title}</mark>"
        rows.append(f"{title}\n<i>{_meta_line(track)}</i>")

    buttons = B.grid(
        [
            B.btn(
                f"{index + 1} · {fmt_duration(track.duration)}",
                data=f"v:{'pick' if mode == 'play' else 'dl'}:{index}",
                style="primary" if index == 0 else None,
            )
            for index, track in enumerate(tracks[:6])
        ],
        columns=3,
    )
    actions = B.row(
        B.btn(f"{E('play')} {verb} top result", data=f"v:{'pick' if mode == 'play' else 'dl'}:0", style="success"),
        B.btn(f"{E('close')} Cancel", data="v:close", style="danger"),
    )
    return (
        B.banner(f"results · {esc(truncate(query, 30))}", glyph="search", meta=f"<i>{len(tracks)}</i>")
        + B.image(tracks[0].thumbnail)
        + B.bullets(rows, ordered=True)
        + B.actions(buttons, actions)
        + B.footer("ranked by relevance, length and reach")
    )

def download_choice_card(track: Track) -> str:
    return (
        B.banner("choose a format", glyph="download")
        + B.context(
            f"{E('note')} <b>{esc(truncate(track.title, 56))}</b>\n"
            f"{E('clock')} {fmt_duration(track.duration)} {BULLET} "
            f"{esc(truncate(track.uploader, 28))}"
        )
        + B.actions(
            B.row(
                B.btn(f"{E('song')} Audio · MP3", data="v:get:audio:0", style="success"),
                B.btn(f"{E('video')} Video · MP4", data="v:get:video:0", style="primary"),
            ),
            B.row(B.btn(f"{E('close')} Cancel", data="v:close", style="danger")),
        )
        + B.footer(f"{E('cloud')} files are cached — repeats are instant")
    )


def download_card(track: Track, kind: str = "audio") -> str:
    """Shown the moment a download starts, then edited into the file itself."""
    icon = E("song") if kind == "audio" else E("video")
    quality = "MP3 320" if kind == "audio" else "MP4 720p"
    return (
        B.banner(f"preparing {kind}", glyph="download", meta=f"<i>{quality}</i>")
        + B.context(
            f"{icon} <b>{esc(truncate(track.title, 52))}</b>\n"
            f"{E('clock')} {fmt_duration(track.duration)} {BULLET} "
            f"{esc(truncate(track.uploader, 28) or 'unknown artist')}"
        )
        + B.fields([("download", "status", f"{B.think()} <i>fetching the best quality…</i>")])
        + B.footer(f"{E('cloud')} the file is cached — asking again is instant")
    )

def favorites_card(items: list[dict]) -> str:
    if not items:
        return (
            B.banner("favourites", glyph="favorite")
            + B.context("Nothing saved yet. Send <code>/fav</code> while a track is playing.")
            + B.actions(
                B.row(
                    B.btn(f"{E('play')} Play something", data="v:help:playback", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                )
            )
        )
    body = B.table(
        ["#", "title", "time"],
        [
            (
                f"<b>{index + 1}</b>",
                esc(truncate(str(item.get("title", "?")), 40)),
                fmt_duration(int(item.get("duration") or 0)),
            )
            for index, item in enumerate(items[:10])
        ],
    )
    return (
        B.banner("favourites", glyph="favorite", meta=f"<i>{len(items)}</i>")
        + B.context("Saved tracks, newest first. They never expire.")
        + body
        + B.actions(
            B.row(
                B.btn(f"{E('play')} Play the first", data="v:fav:play", style="primary"),
                B.btn(f"{E('close')} Close", data="v:close"),
            )
        )
        + B.footer(f"{E('heart')} /fav saves what is playing {BULLET} /unfav removes it")
    )


def history_card(items: list[dict]) -> str:
    if not items:
        return (
            B.banner("recently played", glyph="clock")
            + B.context("Your history will appear here after the first track.")
            + B.actions(B.row(B.btn(f"{E('close')} Close", data="v:close")))
        )
    body = B.table(
        ["#", "title"],
        [
            (f"<b>{index + 1}</b>", esc(truncate(str(item.get("title", "?")), 44)))
            for index, item in enumerate(items[:10])
        ],
    )
    return (
        B.banner("recently played", glyph="clock", meta=f"<i>{len(items)}</i>")
        + B.context("Everything this account has streamed, most recent first.")
        + body
        + B.actions(
            B.row(
                B.btn(f"{E('play')} Play the first", data="v:hist:play", style="primary"),
                B.btn(f"{E('close')} Close", data="v:close"),
            )
        )
        + B.footer(f"{E('clock')} kept for you only {BULLET} /forgetme deletes it")
    )

# ── settings / stats / lyrics / about ───────────────────────────────────────
def _lang_name(code) -> str:
    try:
        from vyron.core import i18n

        return i18n.name(str(code or ""))
    except Exception:  # pragma: no cover - never break a card
        return "English"


def settings_card(cfg: dict, chat_title: str = "") -> str:
    volume = int(cfg.get("volume", settings.default_volume))
    loop = str(cfg.get("loop", "off")).title()
    autoplay = cfg.get("autoplay", True)
    always = cfg.get("always_on", False)

    def flag(value: bool) -> str:
        return f"{B.pill('on', 'ok')}" if value else f"{B.pill('off', 'off')}"

    rows = [
        ("volume", "volume", f"<b>{volume}%</b>  <code>{B.meter(volume, 200, width=10)}</code>"),
        ("loop", "loop", f"<b>{loop}</b>"),
        ("spark", "autoplay", flag(autoplay)),
        ("clock", "24/7", flag(always)),
        ("image", "poster", flag(cfg.get("poster", True))),
        ("shield", "who can play", "<b>Admins</b>" if cfg.get("admins_only") else "<b>Everyone</b>"),
    ]
    if "thumbnail" in cfg:  # only shown when the caller looked it up
        rows.append(("disc", "artwork", "<b>Custom</b>" if cfg["thumbnail"] else "<b>Cover art</b>"))
    rows.append(("globe", "language", f"<b>{_lang_name(cfg.get('lang'))}</b>"))

    return (
        B.banner("settings", glyph="settings", meta=f"<i>{esc(truncate(chat_title, 26) or 'this chat')}</i>")
        + B.context("Changes apply immediately — nothing here needs a restart.")
        + B.fields(rows)
        + B.actions(
            B.row(
                B.btn(f"{E('loop')} Loop", data="v:set:loop", style="primary"),
                B.btn(f"{E('spark')} Autoplay", data="v:set:autoplay", style="success"),
                B.btn(f"{E('clock')} 24/7", data="v:set:always"),
            ),
            B.row(
                B.btn(f"{E('image')} Poster", data="v:set:poster"),
                B.btn(
                    f"{E('shield')} " + ("Admins" if cfg.get("admins_only") else "Everyone"),
                    data="v:set:playmode",
                    style="danger" if cfg.get("admins_only") else "success",
                ),
                B.btn(f"{E('globe')} Language", data="v:lang:menu"),
            ),
            B.row(
                B.btn(f"{E('stats')} Stats", data="v:admin:stats"),
                B.btn(f"{E('close')} Close", data="v:close", style="danger"),
            ),
        )
        + B.footer("volume · loop · autoplay · 24/7 are per chat")
    )

def stats_card(
    *,
    uptime: float,
    chats: int,
    active: int,
    tracks: int,
    downloads: int,
    cache_bytes: int,
    backend: str,
    version: str,
    api: dict | None = None,
    links: dict[str, str] | None = None,
    system: dict | None = None,
) -> str:
    body = B.fields(
        [
            ("clock", "uptime", f"<b>{human_clock(uptime)}</b>"),
            ("chat", "known chats", f"<b>{chats}</b>"),
            ("live", "active players", f"<b>{active}</b>"),
            ("note", "tracks played", f"<b>{tracks}</b>"),
            ("download", "downloads", f"<b>{downloads}</b>"),
            ("cloud", "cache", f"<b>{human_size(cache_bytes)}</b>"),
            ("code", "storage", f"<b>{backend}</b>"),
        ]
    )
    api_block = ""
    if api and api.get("enabled"):
        api_block = B.section_title("music api") + B.fields(
            [
                ("key", "keys", f"<b>{int(api.get('keys') or 0)}</b> / {int(api.get('keys_total') or 0)}"),
                ("download", "requests", f"<b>{int(api.get('requests') or 0)}</b>"),
                ("cloud", "traffic", f"<b>{human_size(int(api.get('bytes') or 0))}</b>"),
                ("shield", "scopes", ", ".join(api.get("scopes") or []) or "read, search, download"),
            ]
        )
    system_block = ""
    if system:
        rows: list[tuple[str, str, str]] = []
        if system.get("cpu_percent") is not None:
            cores = system.get("cores_logical") or system.get("cores_physical")
            tail = f" · {int(cores)}c" if cores else ""
            rows.append(("bolt", "cpu", f"<b>{system['cpu_percent']}%</b>{tail}"))
        if system.get("ram_percent") is not None:
            rows.append(
                (
                    "cloud",
                    "ram",
                    f"<b>{system['ram_used_gb']} / {system['ram_total_gb']} GB</b>"
                    f" · {system['ram_percent']}%",
                )
            )
        if system.get("disk_percent") is not None:
            rows.append(
                (
                    "download",
                    "disk",
                    f"<b>{system['disk_used_gb']} / {system['disk_total_gb']} GB</b>"
                    f" · {system['disk_percent']}%",
                )
            )
        if system.get("os"):
            host = f"{system['os']} {system.get('release') or ''}".strip()
            py = system.get("python")
            rows.append(("code", "host", f"<b>{esc(host)}</b>" + (f" · py {py}" if py else "")))
        if system.get("loadavg") is not None:
            rows.append(("stats", "load", f"<b>{system['loadavg']}</b>"))
        if rows:
            system_block = B.section_title("host") + B.fields(rows)

    owner_row = ""
    if links:
        buttons = []
        if links.get("player"):
            buttons.append(B.btn(f"{E('crown')} Owner console", data="v:app", style="primary"))
        if links.get("api"):
            buttons.append(B.btn(f"{E('code')} API docs", url=links["api"], style="success"))
        if links.get("token"):
            buttons.append(B.btn(f"{E('shield')} Owner token", url=links["token"], style="link"))
        if buttons:
            owner_row = B.row(*buttons[:3])
    return (
        B.banner("statistics", glyph="stats", meta=f"<i>v{version}</i>")
        + B.context("Live numbers from this instance — the same ones /health reports.")
        + body
        + system_block
        + api_block
        + B.actions(
            B.row(
                B.btn(f"{E('live')} Active", data="v:admin:active", style="primary"),
                B.btn(f"{E('check')} Refresh", data="v:admin:stats", style="success"),
            ),
            B.row(
                B.btn(f"{E('logs')} Journal", data="v:admin:logs"),
                B.btn(f"{E('close')} Close", data="v:close"),
            ),
            owner_row,
        )
        + B.footer(f"{E('bolt')} VYRON v{version} {BULLET} Kurigram + PyTgCalls {BULLET} UI: richgram")
    )


def lyrics_card(track: Track, lyrics: LyricsResult | None) -> str:
    if not lyrics or not (lyrics.plain or lyrics.synced):
        return (
            B.banner("lyrics", glyph="lyrics")
            + B.context(
                f"No lyrics for <b>{esc(truncate(getattr(track, 'title', ''), 52))}</b>.\n"
                "LRCLIB does not have this one — try another track or another spelling."
            )
            + B.actions(
                B.row(
                    B.btn(f"{E('now')} Now playing", data="v:np", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                )
            )
            + B.footer(f"{E('lyrics')} source: LRCLIB {BULLET} no key required")
        )
    synced = "synced" if lyrics.has_sync else "plain"
    preview = ""
    if lyrics.has_sync:
        from vyron.core.lyrics import parse_lrc

        lines = parse_lrc(lyrics.synced)[:8]
        if lines:
            preview = B.table(
                [f"{E('clock')} Time", "Line"],
                [
                    (f"<code>{int(line['time']) // 60}:{int(line['time']) % 60:02d}</code>",
                     esc(truncate(line["text"], 48)))
                    for line in lines
                ],
            )
    return (
        B.banner(truncate(lyrics.title, 30), glyph="lyrics", meta=f"<i>{synced}</i>")
        + B.context(
            f"{esc(truncate(lyrics.artist, 40))} {BULLET} {small_caps(synced)} {BULLET} LRCLIB"
        )
        + preview
        + B.details(
            f"{E('note')} <b>Full lyrics</b>",
            f"<blockquote>{esc(lyrics.as_text(3000))}</blockquote>",
        )
        + B.actions(
            B.row(
                B.btn(f"{E('now')} Now playing", data="v:np", style="primary"),
                B.btn(f"{E('interface')} Open the player", data="v:app"),
                B.btn(f"{E('close')} Close", data="v:close"),
            )
        )
        + B.footer(f"{E('interface')} in the app the lyrics scroll with the song")
    )


# ── music API ───────────────────────────────────────────────────────────────
def _ago(stamp: float | int | None) -> str:
    import time as _time

    if not stamp:
        return "never"
    delta = max(0, int(_time.time() - float(stamp)))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _scope_chips(scopes) -> str:
    """`read · search · download` — compact, monospace, no emoji spam."""
    values = [str(item) for item in (scopes or [])]
    if not values:
        return "<i>default</i>"
    return " ".join(f"<code>{esc(scope[:4])}</code>" for scope in values)


def _expiry_state(item: dict) -> str:
    if not item.get("active", True):
        return f"{E('cross')} revoked"
    expires_at = item.get("expires_at")
    if not expires_at:
        return f"{E('infinity')} never"
    if item.get("expired"):
        return f"{E('cross')} expired"
    return f"<b>{_ago(expires_at).replace(' ago', '')}</b>"


def music_api_card(
    base: str,
    stats: dict,
    *,
    compact: bool = False,
    metrics: dict | None = None,
    owner: bool = False,
) -> str:
    """Card for /api — the professional music API served by this deployment."""
    root = (base or "").rstrip("/")
    docs = f"{root}/v1/docs" if root else "/v1/docs"
    openapi = f"{root}/v1/openapi.json" if root else "/v1/openapi.json"
    enabled = bool(stats.get("enabled", True))
    status = f"{E('check')} live" if enabled else f"{E('cross')} disabled"
    auth = (
        f"{E('warn')} open — no key needed"
        if stats.get("open")
        else f"{E('shield')} <code>X-API-Key</code> required"
    )
    served = int(stats.get("requests") or 0)
    body = B.fields(
        [
            ("globe", "base url", f"<code>{esc(root or 'set WEBAPP_URL')}</code>"),
            ("bolt", "status", f"<b>{status}</b> {BULLET} {auth}"),
            ("clock", "rate limit", f"<b>{int(stats.get('rate_limit') or 0)}</b> req/min per key"),
            ("key", "active keys",
             f"<b>{int(stats.get('keys') or 0)}</b> of {int(stats.get('keys_total') or 0)}"),
            ("download", "served",
             f"<b>{served}</b> requests {BULLET} {human_size(int(stats.get('bytes') or 0))}"),
            ("cloud", "storage",
             f"<b>{esc(str(stats.get('storage') or 'json'))}</b> {BULLET} API v2.0"),
        ]
    )
    if metrics:
        body += B.fields(
            [
                ("stats", "hits today",
                 f"<b>{int(metrics.get('requests') or 0)}</b> {BULLET} "
                 f"{int(metrics.get('downloads') or 0)} downloads"),
                ("clock", "latency",
                 f"p50 <b>{metrics.get('latency_ms', {}).get('p50', 0)}ms</b> {BULLET} "
                 f"p95 <b>{metrics.get('latency_ms', {}).get('p95', 0)}ms</b>"),
            ]
        )
    endpoints = B.details(
        f"{E('code')} <b>Endpoints</b> {DASH} canonical",
        B.table(
            ["Method", "Path", "Scope"],
            [
                ("<b>POST</b>", "/v1/tracks", "<code>down</code>"),
                ("<b>GET</b>", "/v1/tracks/{id}", "<code>read</code>"),
                ("<b>GET</b>", "/v1/tracks/{id}/stream", "<code>down</code>"),
                ("<b>POST</b>", "/v1/downloads", "<code>down</code>"),
                ("<b>GET</b>", "/v1/downloads/{id}", "<code>down</code>"),
                ("<b>GET</b>", "/v1/downloads/{id}/file", "<code>down</code>"),
                ("<b>GET</b>", "/v1/search?q=", "<code>srch</code>"),
                ("<b>GET</b>", "/v1/lyrics?title=", "<code>read</code>"),
                ("<b>GET</b>", "/v1/me", "<code>—</code>"),
                ("<b>GET</b>", "/v1/metrics", "<code>adm</code>"),
            ],
        ),
        open=not compact,
    )
    legacy = B.details(
        f"{E('shield')} <b>Drop-in API</b>",
        B.table(
            ["Method", "Path"],
            [
                ("<b>POST</b>", "/v1/track/by-video-id"),
                ("<b>POST</b>", "/v1/track/by-query"),
                ("<b>GET</b>", "/v1/info/by-video-id"),
                ("<b>GET</b>", "/v1/key"),
            ],
        )
        + B.note(f"{E('info')} Old integrations keep working — just swap the base URL."),
        open=False,
    )
    snippet = (
        f"curl -X POST {root}/v1/tracks \\\n"
        f'  -H "X-API-Key: vyrn_..." -H "Content-Type: application/json" \\\n'
        f"  -d '{{\\\"video_id\\\":\\\"dQw4w9WgXcQ\\\"}}' --output track.mp3"
    )
    usage = (
        B.note(f"{E('code')} <b>Quick start</b>\n<pre>{esc(snippet)}</pre>")
        if not compact
        else ""
    )
    scopes_line = B.note(
        f"{E('shield')} scopes: <code>read</code> {BULLET} <code>search</code> {BULLET} "
        f"<code>download</code> {BULLET} <code>admin</code> — mint with "
        f"<code>/getapi label scopes=read,search days=30</code>"
    )
    return (
        B.banner(f"music api {DASH} VYRON", glyph="globe")
        + B.note(
            f"{SPARK} A music API for other bots and apps {DASH} same URL as this bot "
            f"and its Mini App. No second deployment, no extra port."
        )
        + body
        + scopes_line
        + endpoints
        + legacy
        + usage
        + B.divider()
        + B.row(
            B.btn(f"{E('code')} Docs", url=docs, style="primary"),
            B.btn(f"{E('globe')} Open API", url=f"{root}/v1/" if root else settings.git_repo, style="link"),
        )
        + B.row(
            B.btn(f"{E('spark')} Spec", url=openapi, style="success"),
            B.btn(f"{E('queue')} Commands", data="v:help:main", style="link"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
        + (
            B.row(
                B.btn(f"{E('crown')} Owner console", data="v:app", style="primary"),
                B.btn(f"{E('key')} Owner token", data="v:token:rotate"),
                B.btn(f"{E('shield')} Owner help", data="v:help:power", style="link"),
            )
            if owner
            else ""
        )
        + B.footer(
            f"{E('info')} keys: <code>/getapi</code> {BULLET} Mini App → Music API "
            f"{BULLET} docs at <code>/v1/docs</code>"
        )
    )


def api_key_card(
    key: str,
    label: str,
    base: str,
    rate: int,
    *,
    scopes=None,
    expires_at: float | None = None,
    owner_id: int | None = None,
    key_id: str = "",
) -> str:
    """The one-and-only view of a freshly minted key."""
    root = (base or "").rstrip("/")
    expiry = (
        "never expires"
        if not expires_at
        else f"expires {time.strftime('%d %b %Y', time.gmtime(expires_at))}"
    )
    return (
        B.banner(f"api key {DASH} ready", glyph="key")
        + B.note(
            f"{E('warn')} <b>Copy it now</b> {DASH} this is the only time the full key is shown. "
            f"It is stored hashed, so nobody (not even the bot) can show it again."
        )
        + B.note(f"{E('key')} <code>{esc(key)}</code>")
        + B.fields(
            [
                ("note", "label", f"<b>{esc(label)}</b>"),
                ("shield", "scopes", _scope_chips(scopes or ["read", "search", "download"])),
                ("clock", "rate limit", f"<b>{rate}</b> req/min {BULLET} {expiry}"),
                ("globe", "base url", f"<code>{esc(root or 'set WEBAPP_URL')}</code>"),
            ]
        )
        + B.details(
            f"{E('code')} <b>Try it</b>",
            "<pre>"
            + esc(
                f'curl {root}/v1/me -H "X-API-Key: {key}"\n'
                f'curl -X POST {root}/v1/tracks -H "X-API-Key: {key}" \\\n'
                f'  -H "Content-Type: application/json" -d \'{{"video_id":"dQw4w9WgXcQ"}}\' -o track.mp3'
            )
            + "</pre>",
            open=True,
        )
        + B.divider()
        + B.row(
            B.btn(f"{E('code')} Docs", url=f"{root}/v1/docs" if root else settings.git_repo, style="primary"),
            (
                B.btn(f"{E('cross')} Revoke", data=f"v:key:revoke:{key_id}", style="danger")
                if key_id
                else B.btn(f"{E('close')} Close", data="v:close", style="link")
            ),
            B.btn(f"{E('key')} All keys", data="v:token:keys", style="link"),
        )
        + B.footer(
            f"{E('info')} revoke with <code>/revoke {key[:12]}…</code> {BULLET} "
            f"rotate with <code>/rotatekey {key[:12]}…</code>"
        )
    )


def _key_action_rows(keys: list[dict], *, limit: int = 8) -> str:
    """One revoke button per live key — deleting a credential should be a tap."""
    live = [item for item in keys if item.get("active", True)][:limit]
    buttons = [
        B.btn(
            f"{E('cross')} {esc(truncate(str(item.get('label') or item.get('prefix') or 'key'), 14))}",
            data=f"v:key:revoke:{str(item.get('id') or '')}",
            style="danger",
        )
        for item in live
    ]
    if not buttons:
        return ""
    return B.grid(buttons, columns=2)


def api_keys_card(keys: list[dict], base: str) -> str:
    if not keys:
        return (
            B.banner("api keys", glyph="key")
            + B.note(f"{E('moon')} No keys yet {DASH} mint one with <code>/getapi label</code>.")
            + B.row(B.btn(f"{E('code')} Docs", url=f"{(base or '').rstrip('/')}/v1/docs", style="primary"))
        )
    active = sum(1 for item in keys if item.get("active", True))
    rows = [
        (
            f"<b>{esc(str(item.get('label') or 'key'))[:16]}</b>",
            f"<code>{esc(str(item.get('masked') or mask_ish(item)))}</code>",
            _scope_chips(item.get("scopes")),
            f"{int(item.get('uses') or 0)}",
            _expiry_state(item),
        )
        for item in keys
    ]
    return (
        B.banner("api keys", glyph="key", meta=f"<i>{active}/{len(keys)} active</i>")
        + B.table(["Label", "Key", "Scopes", "Uses", "State"], rows)
        + B.note(
            f"{E('shield')} Keys are stored as SHA-256 hashes. The full value is only shown "
            f"when it is minted {DASH} rotate anything you have lost."
        )
        + _key_action_rows(keys)
        + B.row(
            B.btn(f"{E('code')} Docs", url=f"{(base or '').rstrip('/')}/v1/docs", style="primary"),
            B.btn(f"{E('close')} Close", data="v:close", style="link"),
        )
        + B.footer(f"revoke <code>/revoke &lt;id|prefix&gt;</code> {BULLET} rotate <code>/rotatekey</code> {BULLET} {BRAND}")
    )


def token_card(
    token: str,
    *,
    base: str = "",
    owner_id: int = 0,
    ttl_days: int = 30,
    epoch: int = 0,
    active_keys: int = 0,
) -> str:
    """``/apitoken`` — one screen for the owner's credentials and how to kill them."""
    root = (base or "").rstrip("/") or "WEBAPP_URL"
    return (
        B.banner("owner access", glyph="crown")
        + B.note(
            f"{SPARK} This token is your key to the <b>music API</b> and to scripts.\n"
            f"The Mini App never needs it — Telegram already proves who you are."
        )
        + B.note(f"{E('key')} <code>{esc(token)}</code>")
        + B.fields(
            [
                ("user", "owner", f"<code>{owner_id or '—'}</code>"),
                ("clock", "expires", f"<b>{ttl_days} days</b> from the last rotate"),
                (
                    "shield",
                    "generation",
                    f"<b>{int(epoch) + 1}</b> {BULLET} revoking kills every older token",
                ),
                ("code", "header", "<code>X-Owner-Token: …</code>"),
                ("key", "api keys", f"<b>{int(active_keys)}</b> active"),
            ]
        )
        + B.details(
            f"{E('code')} <b>Try it</b>",
            "<pre>"
            + esc(
                f'curl -s "{root}/v1/me" -H "X-Owner-Token: {token}"\n'
                f'curl -s "{root}/v1/admin/keys" -H "X-Owner-Token: {token}"'
            )
            + "</pre>",
            open=False,
        )
        + B.divider()
        + B.row(
            B.btn(f"{E('play')} Open player", data="v:app", style="primary"),
            B.btn(f"{E('code')} API docs", url=f"{root}/v1/docs", style="success"),
        )
        + B.row(
            B.btn(f"{E('rocket')} Rotate", data="v:token:rotate"),
            B.btn(f"{E('cross')} Revoke all", data="v:token:revoke", style="danger"),
            B.btn(f"{E('key')} API keys", data="v:token:keys", style="link"),
        )
        + B.footer(
            f"{E('shield')} a token lasts 30 days; <b>Revoke all</b> invalidates every one "
            f"instantly — including any you already shared"
        )
    )


def token_revoked_card(*, epoch: int = 0, keys_revoked: int = 0) -> str:
    """Confirmation after a revocation — says plainly what still works."""
    return (
        B.banner("tokens revoked", glyph="shield")
        + B.note(
            "Every owner token minted before now is <b>dead</b>. "
            "The Mini App keeps working — it authenticates with Telegram, not this token."
        )
        + B.fields(
            [
                ("bolt", "generation", f"<b>{int(epoch) + 1}</b>"),
                ("key", "api keys revoked", f"<b>{int(keys_revoked)}</b>"),
                ("info", "next step", "mint a fresh one with <code>/apitoken</code>"),
            ]
        )
        + B.actions(B.row(B.btn(f"{E('check')} Got it", data="v:close", style="success")))
        + B.footer(f"{E('crown')} you can also rotate only the API keys, from the API keys screen")
    )


def api_usage_card(
    stats: dict,
    keys: list[dict],
    base: str,
    *,
    sudo: bool = False,
    metrics: dict | None = None,
) -> str:
    totals = B.fields(
        [
            ("key", "active keys",
             f"<b>{int(stats.get('keys') or 0)}</b> / {int(stats.get('keys_total') or 0)}"),
            ("download", "requests", f"<b>{int(stats.get('requests') or 0)}</b>"),
            ("cloud", "bytes served", f"<b>{human_size(int(stats.get('bytes') or 0))}</b>"),
            ("clock", "rate limit", f"<b>{int(stats.get('rate_limit') or 0)}</b> req/min"),
            ("globe", "mode", "open" if stats.get("open") else "keyed"),
            ("cloud", "storage", f"<b>{esc(str(stats.get('storage') or 'json'))}</b>"),
        ]
    )
    if metrics:
        totals += B.fields(
            [
                ("bolt", "this process",
                 f"<b>{int(metrics.get('requests') or 0)}</b> hits "
                 f"{BULLET} <b>{int(metrics.get('rate_limited') or 0)}</b> throttled"),
                ("clock", "latency",
                 f"p50 <b>{metrics.get('latency_ms', {}).get('p50', 0)}ms</b> "
                 f"{BULLET} p95 <b>{metrics.get('latency_ms', {}).get('p95', 0)}ms</b> "
                 f"{BULLET} p99 <b>{metrics.get('latency_ms', {}).get('p99', 0)}ms</b>"),
            ]
        )
    by_key = ""
    if keys and sudo:
        by_key = B.table(
            ["Label", "Scopes", "Uses", "Bytes", "Last used"],
            [
                (
                    f"<b>{esc(str(item.get('label') or 'key'))[:16]}</b>",
                    _scope_chips(item.get("scopes")),
                    str(int(item.get("uses") or 0)),
                    human_size(int(item.get("bytes") or 0)),
                    _ago(item.get("last_used_at")),
                )
                for item in keys[:12]
            ],
        )
    return (
        B.banner("api usage", glyph="stats")
        + totals
        + by_key
        + B.row(
            B.btn(f"{E('code')} Docs", url=f"{(base or '').rstrip('/')}/v1/docs", style="primary"),
            B.btn(f"{E('spark')} Metrics", url=f"{(base or '').rstrip('/')}/v1/metrics", style="link"),
        )
        + B.footer(f"{E('spark')} every request is metered per key {BULLET} {BRAND}")
    )


def mask_ish(item: dict) -> str:
    key = str(item.get("key") or item.get("prefix") or "")
    return f"{key[:8]}…{key[-4:]}" if len(key) > 12 else key


def about_card() -> str:
    """What VYRON is, in one screen — no marketing, no credits list."""
    body = B.fields(
        [
            ("code", "stack", "Kurigram + PyTgCalls + yt-dlp"),
            ("bolt", "interface", "rich cards · premium emoji · Mini App"),
            ("cloud", "deploy", "Docker · Render · Koyeb · any VPS"),
            ("download", "media", "voice chat · MP3 320 · MP4 720p · synced lyrics"),
            ("code", "music api", "<code>/v1</code> + <code>/vyron</code> on this same URL"),
            (
                "users",
                "sources",
                "YouTube · YT Music · JioSaavn · Audius · SoundCloud — if YouTube "
                "blocks the server, the same song plays from a catalogue",
            ),
        ]
    )
    return (
        B.banner("about", glyph="brand")
        + B.context(
            f"<b>{esc(BRAND_DISPLAY)}</b> streams music into a Telegram voice chat, "
            "finds what you mean even when you half-remember the title, and hands you "
            "the file when you would rather keep it."
        )
        + body
        + B.actions(
            B.row(
                B.btn(f"{E('code')} Source", url=settings.git_repo, style="link"),
                B.btn(f"{E('chat')} Support", url=settings.support_chat, style="link"),
            ),
            B.row(
                B.btn(f"{E('back')} Back to commands", data="v:help:main", style="primary"),
                B.btn(f"{E('close')} Close", data="v:close", style="danger"),
            ),
        )
        + B.footer(f"v{_version()} · Kurigram · PyTgCalls · yt-dlp · richgram")
    )

# ── small status cards ──────────────────────────────────────────────────────
# ── saved playlists ─────────────────────────────────────────────────────────
def playlists_card(items: list[dict]) -> str:
    """`/playlists` — what you have saved, and one tap to play the first."""
    if not items:
        return (
            B.banner("playlists", glyph="playlist")
            + B.context(
                "Nothing saved yet.\n"
                "<code>/savepl chill nights</code> banks the queue; "
                "<code>/pcreate</code> starts an empty one."
            )
            + B.actions(
                B.row(
                    B.btn(f"{E('play')} What is playing", data="v:np", style="primary"),
                    B.btn(f"{E('close')} Close", data="v:close"),
                )
            )
            + B.footer(f"{E('playlist')} playlists follow your account, not the chat")
        )
    rows = B.table(
        ["name", "tracks", "length"],
        [
            (
                f"<b>{rich_name(item.get('name'))}</b>",
                f"{len(item.get('tracks', []))}",
                fmt_duration(sum(int(t.get("duration") or 0) for t in item.get("tracks", []))),
            )
            for item in items[:12]
        ],
    )
    return (
        B.banner("playlists", glyph="playlist", meta=f"<i>{len(items)}</i>")
        + B.context("Saved on your account. <code>/pplay &lt;name&gt;</code> queues one.")
        + rows
        + B.actions(
            B.row(
                B.btn(f"{E('play')} Queue the first", data=f"v:pl:{items[0]['id']}", style="primary"),
                B.btn(f"{E('close')} Close", data="v:close"),
            )
        )
        + B.footer(f"{E('playlist')} the same lists appear in the app's Library")
    )


def rich_name(value) -> str:
    """A playlist name, escaped and shortened — never trust user text."""
    return esc(truncate(str(value or "untitled"), 30))


def playlist_card(playlist: dict) -> str:
    """`/pview` — one playlist, its tracks, and what to do with them."""
    tracks = playlist.get("tracks", [])
    name = str(playlist.get("name") or "playlist")
    total = sum(int(item.get("duration") or 0) for item in tracks)
    if tracks:
        body = B.table(
            ["#", "title", "time"],
            [
                (
                    f"<b>{index}</b>",
                    esc(truncate(str(item.get("title") or "—"), 40)),
                    fmt_duration(int(item.get("duration") or 0)),
                )
                for index, item in enumerate(tracks[:20], start=1)
            ],
        )
        if len(tracks) > 20:
            body += B.note(
                f"{E('info')} first 20 of {len(tracks)} shown — the whole list is in the app"
            )
        actions = B.row(
            B.btn(f"{E('play')} Queue it", data=f"v:pl:{playlist['id']}", style="primary"),
            B.btn(f"{E('queue')} The queue", data="v:queue"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
        footer = (
            f"{E('note')} <code>/pplay {esc(truncate(name, 20))}</code> queues it · "
            "<code>/premove</code> drops a track"
        )
    else:
        body = B.context(
            f"Empty for now — play a track and send "
            f"<code>/padd {esc(truncate(name, 20))}</code> to drop it in."
        )
        actions = B.row(
            B.btn(f"{E('now')} What is playing", data="v:np", style="primary"),
            B.btn(f"{E('playlist')} My playlists", data="v:help:tools"),
            B.btn(f"{E('close')} Close", data="v:close"),
        )
        footer = f"{E('note')} nothing to queue until it has at least one track"
    return (
        B.banner(truncate(name, 30), glyph="playlist")
        + B.context(f"<b>{len(tracks)}</b> tracks · <b>{fmt_duration(total)}</b> of music")
        + body
        + B.actions(actions)
        + B.footer(footer)
    )


def change_card(
    title: str,
    *,
    glyph: str = "check",
    label: str = "",
    value: str = "",
    note: str = "",
    extra: Iterable[tuple[str, str, str]] = (),
    actions: str = "",
) -> str:
    """A setting that just changed: one fact, one line of context, one way out.

    `/volume 40`, `/loop one`, `/shuffle`, a prompt saved, an effect toggled —
    they all used to be a single bold line glued to the chat. They are the same
    *shape* every time, so they are the same card every time:

        ━━ 🎚️ ᴠᴏʟᴜᴍᴇ ━━
        ◈ 🔊 ʟᴇᴠᴇʟ: 40%
        <blockquote>the assistant speaks at this level…</blockquote>
        [ Now playing ] [ Close ]
    """
    rows: list[tuple[str, str, str]] = []
    if label:
        rows.append((glyph, label, value))
    rows.extend(extra)
    body = B.fields(rows) if rows else ""
    return (
        B.banner(title, glyph=glyph)
        + body
        + (B.context(note) if note else "")
        + B.actions(
            actions
            or B.row(
                B.btn(f"{E('now')} Now playing", data="v:np", style="primary"),
                B.btn(f"{E('settings')} Settings", data="v:settings"),
                B.btn(f"{E('close')} Close", data="v:close"),
            )
        )
        + B.footer(f"{E('spark')} {BRAND} {BULLET} v{_version()}")
    )


def working_card(title: str, text: str, *, glyph: str = "spinner") -> str:
    """A placeholder that is edited into the real answer a moment later.

    It still gets the masthead, so the chat does not flicker between "a bold
    line" and "a card" while a search or a download runs.
    """
    return (
        B.banner(title, glyph=glyph)
        + B.context(f"{B.think()} {text}")
        + B.footer(f"{E('spark')} {BRAND} {BULLET} this card updates itself")
    )


def _status_card(glyph: str, headline: str, text: str, *, style: str = "primary") -> str:
    """The short answers: /pause, /resume, a save, a failure.

    Short in content, never in *shape*: they carry the same masthead as every
    other screen, so a reply to /pause looks like it came from the same bot as
    /start — and they still offer a way forward (the player, or close), because
    a card that only reports is a card you have to delete yourself afterwards.
    """
    body = B.context(text) if text else ""
    return (
        B.banner(headline, glyph=glyph)
        + body
        + B.actions(
            B.row(
                B.btn(f"{E('now')} Playing", data="v:np", style=style),
                B.btn(f"{E('close')} Close", data="v:close"),
            )
        )
        + B.footer(f"{E('spark')} {BRAND} {BULLET} {_version()}")
    )


def ok_card(text: str, *, headline: str = "done") -> str:
    return _status_card("check", headline, text)


def warn_card(text: str, *, headline: str = "heads up") -> str:
    return _status_card("warn", headline, text, style="danger")


def error_card(text: str, *, headline: str = "that did not work") -> str:
    return _status_card("cross", headline, text, style="danger")


def info_card(text: str, *, headline: str = "fyi", glyph: str = "info") -> str:
    """A neutral answer — a usage hint, a readout, a "nothing is playing"."""
    return _status_card(glyph, headline, text)


def locked_card(text: str, *, headline: str = "not allowed") -> str:
    return _status_card("shield", headline, text, style="danger")


def ping_card(latency_ms: float, uptime: float) -> str:
    """Latency with an honest verdict, not just a number."""
    if latency_ms < 120:
        verdict, tone = "instant", "ok"
    elif latency_ms < 400:
        verdict, tone = "healthy", "ok"
    elif latency_ms < 900:
        verdict, tone = "a little slow", "warn"
    else:
        verdict, tone = "slow — check the host region", "warn"
    return (
        B.banner("ping", glyph="bolt")
        + B.context("One round trip: your message in, this card out.")
        + B.fields(
            [
                ("bolt", "latency", f"<b>{latency_ms:.0f} ms</b> · {B.pill(verdict, tone)}"),
                ("rocket", "uptime", f"<b>{human_time(uptime)}</b>"),
            ]
        )
        + B.actions(
            B.row(
                B.btn(f"{E('check')} Again", data="v:ping", style="primary"),
                B.btn(f"{E('stats')} Stats", data="v:admin:stats"),
            )
        )
    )

def _app_root(url: str) -> str:
    """Normalise a WEBAPP_URL into the Mini App entry point (keeps query)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    if not path.endswith("/app"):
        path = f"{path}/app" if path else "/app"
    return urlunsplit((parts.scheme, parts.netloc, f"{path}/", parts.query, parts.fragment))


def app_entry_url(url: str | None = None, *, owner_token: str = "") -> str:
    """Public helper: Mini App URL (optionally with an owner token)."""
    entry = _app_root(url or settings.webapp_url)
    return _with_owner_token(entry, owner_token) if owner_token else entry


def _with_owner_token(url: str, token: str) -> str:
    if not url or not token:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}ot={token}"


def webapp_card(url: str, chat_title: str = "", owner_token: str = "") -> str:
    """Shown in DM: the keyboard around this card carries the web_app button."""
    return (
        B.banner("player", glyph="play")
        + B.note(
            "<b>Opens inside Telegram.</b>\n"
            "No browser tab, no login — the same chat, the same queue."
        )
        + B.bullets(
            [
                "<b>Play here</b> or <b>cast</b> the same track into the voice chat",
                "Queue, lyrics, shuffle and repeat on one screen",
                "Works on mobile and desktop Telegram",
            ]
        )
        + B.footer("tap the button below · or long-press the menu button")
    )


def webapp_group_card(bot_username: str) -> str:
    """Groups cannot host a Mini App button, so point at the DM instead."""
    return (
        B.heading(f"{E('play')} player", 2)
        + B.note(
            "<b>Telegram only opens the player in a private chat.</b>\n"
            f"Open <a href=\"https://t.me/{esc(bot_username)}\">@{esc(bot_username)}</a>, "
            "tap <b>Player</b>, and it opens inside Telegram."
        )
        + B.footer("the voice chat here keeps playing while you browse")
    )


# ── owner journal ───────────────────────────────────────────────────────────
_LOG_GLYPH = {
    "debug": "·",
    "info": "›",
    "ok": "✓",
    "warn": "!",
    "error": "×",
}


def logs_card(
    events: list[dict],
    stats: dict,
    *,
    level: str = "all",
    scope: str = "",
) -> str:
    """The owner journal as a card: newest last, plain enough to scan fast."""
    import time as _time

    from vyron.ui.theme import E as _E

    uptime = human_time(float(stats.get("uptime") or 0))
    head = B.fields(
        [
            ("clock", "uptime", f"<b>{uptime}</b>"),
            ("note", "buffered",
             f"<b>{int(stats.get('buffered') or 0)}</b> / {int(stats.get('seq') or 0)}"),
            ("warn", "warnings", f"<b>{int(stats.get('warnings') or 0)}</b>"),
            ("close", "errors", f"<b>{int(stats.get('errors') or 0)}</b>"),
        ]
    )

    lines: list[str] = []
    for event in events[-14:]:
        stamp = _time.strftime("%H:%M:%S", _time.localtime(float(event.get("ts") or 0)))
        glyph = _LOG_GLYPH.get(str(event.get("level")), "·")
        scope_name = esc(str(event.get("scope") or "app"))
        message = esc(truncate(str(event.get("message") or ""), 110))
        line = f"<code>{stamp}</code> {glyph} <b>{scope_name}</b> {message}"
        if event.get("meta", {}).get("type"):
            line += f" <i>({esc(str(event['meta']['type']))})</i>"
        lines.append(line)

    body = B.bullets(lines) if lines else "<i>Nothing recorded yet — the journal fills as the bot works.</i>"
    filters = B.row(
        B.btn("All", data="v:logs:all", style="primary" if level == "all" else None),
        B.btn("Info", data="v:logs:info", style="primary" if level == "info" else None),
        B.btn("Warn", data="v:logs:warn", style="primary" if level == "warn" else None),
        B.btn("Errors", data="v:logs:error", style="primary" if level == "error" else None),
        B.btn(f"{_E('check')} Refresh", data=f"v:logs:{level}", style="success"),
    )
    title = "journal" + (f" · {scope}" if scope else "") + ("" if level == "all" else f" · {level}")
    return (
        B.banner(title, glyph="code")
        + head
        + B.divider()
        + body
        + filters
        + B.row(
            B.btn(f"{_E('download')} Export .jsonl", data="v:logs:export", style="link"),
            B.btn(f"{_E('close')} Clear", data="v:logs:clear", style="danger"),
        )
        + B.footer(
            f"{_E('info')} Newest last {BULLET} warnings and errors include the traceback type "
            f"{BULLET} also at /app → Owner → Logs"
        )
    )


# ── group management ────────────────────────────────────────────────────────
_TONES = {
    "ok": ("check", "success"),
    "warn": ("warn", "danger"),
    "error": ("cross", "danger"),
    "info": ("info", "primary"),
}


def thumbnail_card(has_custom: bool, *, can_edit: bool = True) -> str:
    """``/thumbnail`` — what the now-playing poster uses as its backdrop."""
    mode = "your artwork" if has_custom else "the song cover"
    hint = (
        f"{E('image')} Reply to a photo with <code>/thumbnail</code> to use it here — "
        "the cover and colours still come from the track."
        if can_edit
        else f"{E('shield')} A group admin can set this — reply to a photo with "
        "<code>/thumbnail</code>."
    )
    body = (
        B.banner("chat artwork", glyph="image")
        + B.fields(
            [
                ("image", "backdrop", f"<b>{mode}</b>"),
                ("spark", "accent", "<i>from the song</i>"),
                ("chat", "scope", "<i>this chat only</i>"),
            ]
        )
        + B.note(hint)
    )
    if has_custom and can_edit:
        body += B.row(
            B.btn(f"{E('close')} Remove artwork", data="v:thumb:off", style="danger"),
            B.btn(f"{E('back')} Close", data="v:close"),
        )
    else:
        body += B.row(B.btn(f"{E('close')} Close", data="v:close"))
    return body + B.footer(f"{E('info')} every new track re-renders the poster")


def thumbnail_set_card() -> str:
    return (
        B.banner("artwork saved", glyph="check")
        + B.note(
            "New posters in this chat will use it as the backdrop. The cover, the "
            "vinyl and the colours stay tied to the track."
        )
        + B.footer(f"{E('info')} /thumbnail off reverts to the song cover")
    )


def thumbnail_cleared_card() -> str:
    return (
        B.banner("back to the cover", glyph="image")
        + B.note("The next poster in this chat uses the track's own artwork again.")
    )


def notice_card(
    title: str,
    detail: str = "",
    *,
    tone: str = "ok",
    icon: str | None = None,
    extra: Iterable[tuple[str, str]] = (),
    footer: str = "",
    actions: str = "",
) -> str:
    """One-line confirmation with context — the shape every group action uses."""
    glyph_name, style = _TONES.get(tone, _TONES["ok"])
    markup = B.banner(title, glyph=(icon or glyph_name))
    if detail:
        markup += B.context(detail)
    pairs = [("info", key, value) for key, value in extra]
    if pairs:
        markup += B.fields(pairs)
    if actions:
        markup += B.actions(actions)
    if footer:
        markup += B.footer(footer)
    return markup


def rules_card(title: str, rules: str, *, admins: int = 0, can_edit: bool = False) -> str:
    """``/rules`` — the chat's own rulebook, readable by everyone."""
    body = (
        B.banner(f"rules {DASH} {esc(truncate(title, 34))}", glyph="note")
        + B.note(esc(rules) if rules else (
            "<b>No rules yet.</b>\nAn admin can set them with "
            "<code>/setrules 1. Be kind 2. No spam</code>."
        ))
    )
    if can_edit:
        body += B.row(
            B.btn(f"{E('note')} read the rules", data="v:grp:rules", style="link"),
            B.btn(f"{E('check')} Got it", data="v:close", style="success"),
        )
    else:
        body += B.row(B.btn(f"{E('check')} Got it", data="v:close", style="success"))
    return body + B.footer(
        f"{E('shield')} {admins} admins enforce these {BULLET} /report to flag a message"
    )


def chat_info_card(info: dict) -> str:
    """``/chatinfo`` — everything about this group on one screen."""
    rows = [
        ("chat", "title", f"<b>{esc(truncate(str(info.get('title') or 'this chat'), 40))}</b>"),
        ("code", "id", f"<code>{info.get('id')}</code>"),
        ("link", "username", f"@{esc(info['username'])}" if info.get("username") else "<i>private</i>"),
        ("user", "members", f"<b>{compact_number(int(info.get('members') or 0))}</b>"
                            + (f" {BULLET} {compact_number(int(info.get('online') or 0))} online"
                               if info.get("online") else "")),
        ("crown", "admins", f"<b>{int(info.get('admins') or 0)}</b>"),
        ("clock", "slow mode", f"<b>{slow_label(int(info.get('slowmode') or 0))}</b>"),
        ("bolt", "created", f"<b>{esc(str(info.get('created') or '—'))}</b>"),
        ("shield", "protected", "on" if info.get("protected") else "off"),
        ("chat", "forum", "on" if info.get("forum") else "off"),
        ("cloud", "data centre", f"DC{info.get('dc')}" if info.get("dc") else "—"),
    ]
    if info.get("linked"):
        rows.append(("link", "linked channel", esc(str(info["linked"]))))
    if info.get("pinned"):
        rows.append(("star", "pinned", esc(truncate(str(info["pinned"]), 44))))
    body = B.banner("chat info", glyph="info") + B.fields(rows)
    if info.get("description"):
        body += B.context(f"<b>About</b>\n{esc(truncate(str(info['description']), 220))}")
    if info.get("invite"):
        body += B.actions(
            B.row(
                B.btn(f"{E('link')} Open invite", url=str(info["invite"]), style="primary"),
                B.btn(f"{E('close')} Close", data="v:close", style="danger"),
            )
        )
    else:
        body += B.actions(B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger")))
    return body + B.footer(f"{E('shield')} /gadmin for every management command")


def slow_label(seconds: int) -> str:
    if seconds <= 0:
        return "off"
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def group_admin_card(
    *,
    rules: str = "",
    slowmode: int = 0,
    captcha: bool = False,
    approved: int = 0,
    locked: int = 0,
    warn_limit: int = 3,
    bot_admin: bool = True,
) -> str:
    """``/gadmin`` — the map of every group tool this bot ships."""
    health = (
        f"{E('check')} admin rights ok" if bot_admin else f"{E('warn')} promote me to admin"
    )
    state = B.fields(
        [
            ("note", "rules", "<b>set</b>" if rules else "<i>not set</i>"),
            ("clock", "slow mode", f"<b>{slow_label(slowmode)}</b>"),
            ("shield", "locks on", f"<b>{locked}</b>"),
            ("user", "approved", f"<b>{approved}</b>"),
            ("warn", "warn limit", f"<b>{warn_limit}</b>"),
            ("shield", "captcha", "<b>on</b>" if captcha else "<i>off</i>"),
            ("bolt", "bot rights", health),
        ]
    )
    sections = B.details(
        f"{E('shield')} <b>Moderation</b>",
        B.bullets(
            [
                "<code>/ban</code> · <code>/unban</code> · <code>/kick</code> — reply or pass an id",
                "<code>/mute</code> · <code>/unmute</code> · <code>/tmute 10m</code>",
                "<code>/warn</code> · <code>/warns</code> · <code>/resetwarns</code> · <code>/setwarnlimit 3</code>",
                "<code>/purge</code> · <code>/del</code> · <code>/cleanup</code>",
            ]
        ),
        open=True,
    )
    sections += B.details(
        f"{E('tools')} <b>Group settings</b>",
        B.bullets(
            [
                "<code>/settitle</code> · <code>/setdesc</code> · <code>/setchatphoto</code> — chat identity",
                "<code>/slowmode 30</code> · <code>/slowmode off</code>",
                "<code>/setrules …</code> · <code>/rules</code> · <code>/clearqueuerules</code>",
                "<code>/invitelink</code> · <code>/revokeinvite</code>",
                "<code>/pin</code> · <code>/unpin</code> · <code>/unpinall</code> · <code>/pinned</code>",
            ]
        ),
    )
    sections += B.details(
        f"{E('wave')} <b>Protection</b>",
        B.bullets(
            [
                "<code>/locks</code> — media, links, forwards, stickers, bots, commands, NSFW",
                "<code>/antiflood 7</code> — rate limit with automatic mute",
                "<code>/approve</code> — exempt a trusted user from locks and flood",
                "<code>/zombies</code> — find (and kick) deleted accounts",
                "<code>/report</code> — ping the admins about a message",
                "<code>/captcha</code> — one-tap human check for new members",
            ]
        ),
    )
    sections += B.details(
        f"{E('play')} <b>Playback control</b>",
        B.bullets(
            [
                "<code>/settings</code> — volume, loop, autoplay, 24/7",
                "<code>/effecton bass</code> — audio effects for the call",
                "<code>/voteskip</code> — let members skip with votes",
                "<code>/247</code> · <code>/always</code> — keep the stream alive",
            ]
        ),
    )
    return (
        B.banner("group manager", glyph="crown")
        + B.note("Every tool below works on a reply or a user id.")
        + state
        + B.divider()
        + sections
        + B.row(
            B.btn(f"{E('shield')} Locks", data="v:grp:locks", style="primary"),
            B.btn(f"{E('wave')} Anti-flood", data="v:grp:flood", style="success"),
        )
        + B.row(
            B.btn(f"{E('note')} Rules", data="v:grp:rules"),
            B.btn(f"{E('user')} Approved", data="v:grp:approved"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
        + B.footer(f"{E('info')} admins only {BULLET} owners bypass every check")
    )


def zombies_card(found: list[tuple[str, str]], *, scanned: int, kicked: int = 0, capped: bool = False) -> str:
    """``/zombies`` — deleted accounts still sitting in the member list."""
    rows = "".join(
        f"<tr><td>{esc(name)}</td><td><code>{uid}</code></td></tr>" for name, uid in found[:20]
    )
    table = f"<table><tr><th>account</th><th>id</th></tr>{rows}</table>" if rows else ""
    headline = (
        f"{E('check')} All clean — no deleted accounts in {scanned} members"
        if not found
        else f"{E('bolt')} {len(found)} deleted account{'s' if len(found) != 1 else ''} of {scanned} scanned"
    )
    body = B.banner("zombies", glyph="bolt") + B.note(headline)
    if table:
        body += table
    if kicked:
        body += B.note(f"{E('shield')} kicked <b>{kicked}</b> of them")
    if found:
        body += B.row(B.btn(f"{E('check')} Keep them", data="v:close", style="success"))
        body += B.footer(
            f"{E('info')} run <code>/zombies kick</code> to remove them in one pass"
        )
    if capped:
        body += B.footer(f"{E('info')} scanned the first {scanned} members — Telegram caps the listing")
    return body


def approved_card(entries: list[tuple[str, str]], *, limit: int = 30) -> str:
    """``/approved`` — users exempt from locks and anti-flood."""
    if not entries:
        return (
            B.banner("approved users", glyph="user")
            + B.note("Nobody yet. <code>/approve</code> on a reply adds someone.")
            + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
        )
    rows = "".join(
        f"<tr><td>{esc(name)}</td><td><code>{uid}</code></td></tr>" for name, uid in entries[:limit]
    )
    return (
        B.banner("approved users", glyph="user")
        + B.note(f"{len(entries)} exempt from locks and anti-flood")
        + f"<table><tr><th>user</th><th>id</th></tr>{rows}</table>"
        + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
        + B.footer(f"{E('info')} /unapprove on a reply or id removes one")
    )


def captcha_card(mention: str, *, seconds: int = 120, user_id: int = 0) -> str:
    """New-member gate: one tap proves there is a human behind the account."""
    return (
        B.banner("verify to speak", glyph="shield")
        + B.note(
            f"Welcome {mention}! Tap the button below within "
            f"<b>{slow_label(seconds)}</b> to unlock the chat."
        )
        + B.row(
            B.btn(
                f"{E('check')} I am human",
                data=f"v:captcha:{user_id or 'self'}",
                style="success",
            )
        )
        + B.footer(
            f"{E('info')} still muted? the button stays live {BULLET} ask an admin if it fails"
        )
    )


def confirm_card(
    title: str,
    detail: str,
    *,
    confirm: str,
    cancel: str = "v:close",
    danger: bool = False,
    confirm_label: str = "Yes, do it",
) -> str:
    """A two-step confirmation — destructive actions never fire on one tap."""
    return (
        B.banner(title, glyph=("warn" if danger else "info"))
        + B.context(detail)
        + B.actions(
            B.row(
                B.btn(
                    f"{E('check')} {confirm_label}",
                    data=confirm,
                    style="danger" if danger else "success",
                ),
                B.btn(f"{E('back')} Cancel", data=cancel),
            )
        )
        + B.footer(f"{E('shield')} nothing happens until you confirm")
    )
