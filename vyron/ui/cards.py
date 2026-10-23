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

from typing import Iterable

from vyron.config import settings
from vyron.core.lyrics import LyricsResult
from vyron.core.queue import ChatState, Track
from vyron.ui import blocks as B
from vyron.ui.blocks import esc
from vyron.ui.progress import (
    fmt_duration,
    human_size,
    human_time,
    percentage,
    progress_bar,
    truncate,
)
from vyron.ui.theme import BRAND, BULLET, DASH, E, SPARK, small_caps

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
    elapsed = state.elapsed()
    total = track.duration or 0
    bar = progress_bar(elapsed, total, length=14)
    if total:
        return (
            f"<code>{bar}</code>\n"
            f"<code>{fmt_duration(elapsed)}</code> {DASH} <code>{fmt_duration(total)}</code>"
            f"  ({percentage(elapsed, total)}%)"
        )
    return f"<code>{bar}</code>\n<code>live {DASH} {fmt_duration(elapsed)}</code>"


# ── start ───────────────────────────────────────────────────────────────────
def start_card(name: str, stats: dict, *, streaming: bool = True) -> str:
    served = stats.get("chats", 0)
    tracks = stats.get("tracks", 0)
    features = B.kv(
        [
            (f"{E('bolt')} Instant play", "links, replies &amp; plain text"),
            (f"{E('search')} Smart search", "top results, one tap to stream"),
            (f"{E('download')} Downloads", "MP3 &amp; MP4 with covers"),
            (f"{E('lyrics')} Lyrics", "synced via LRCLIB"),
            (f"{E('shield')} Admin-first", "only admins steer playback"),
        ]
    )
    guide = B.details(
        f"{E('rocket')} <b>Get started in 3 steps</b>",
        B.bullets(
            [
                "Add me to a group (and the assistant account)",
                "Give me <b>manage voice chats</b> + <b>delete messages</b>",
                "Start a voice chat, then send <code>/play believer</code>",
            ],
            ordered=True,
        ),
        open=True,
    )
    buttons = (
        B.row(B.btn(f"{E('rocket')} Add to group", url=f"https://t.me/{settings.bot_username}?startgroup=true", style="primary"))
        + B.row(
            B.btn(f"{E('queue')} Commands", data="v:help:main", style="success"),
            B.btn(f"{E('info')} About", data="v:about"),
        )
        + B.row(
            B.btn(f"{E('chat')} Support", url=settings.support_chat, style="link"),
            B.btn(f"{E('star')} Updates", url=settings.updates_channel, style="link"),
        )
    )
    return (
        B.heading(f"{E('brand')} {BRAND}", 2)
        + B.note(
            f"{SPARK} <b>High-fidelity voice-chat streaming</b> for Telegram — search, "
            f"queue, download and control everything from one clean panel."
        )
        + features
        + guide
        + (
            ""
            if streaming
            else B.note(
                f"{E('info')} <b>File mode</b> — no assistant session yet, so "
                "<code>/play</code> sends the track as a file. Add "
                "<code>STRING_SESSION</code> to stream into voice chats."
            )
        )
        + B.divider()
        + buttons
        + B.footer(
            f"Hi <b>{esc(truncate(name, 40))}</b> {BULLET} {served} chats {BULLET} {tracks} tracks played "
            f"{BULLET} v{_version()}"
        )
    )


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
            ("/vplay <song|link>", "stream video"),
            ("/song <song|link>", "send the MP3 here"),
            ("/video <song|link>", "send the MP4 here"),
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
            ("/clear", "empty the queue, keep playing"),
            ("/playlist <url>", "queue up to 50 tracks"),
        ],
    ),
    "tools": (
        "Tools",
        [
            ("/fav · /favs", "save and list favourites"),
            ("/history", "your recently played"),
            ("/settings", "per-chat defaults"),
            ("/247", "toggle 24/7 mode"),
            ("/emojis", "premium emoji pack status"),
            ("/app", "open the player web app"),
            ("/whoami", "your id, role and chat"),
        ],
    ),
    "social": (
        "Groups",
        [
            ("/voteskip set 3", "require votes before a skip"),
            ("/vskip", "cast your vote"),
            ("/cplayset <id>", "stream into a specific channel"),
            ("/suggest", "tracks like the one playing"),
            ("/next <song>", "insert a track up front"),
            ("/savepl [name]", "save the queue to a playlist"),
            ("/playlists · /pl <name>", "list and queue your playlists"),
            ("/song · /vsong", "get an MP3 or MP4 in the chat"),
            ("/locks · /antiflood", "content locks and flood control"),
        ],
    ),
    "power": (
        "Owner",
        [
            ("/eval <code>", "run python in the bot process"),
            ("/vars", "configuration snapshot (masked)"),
            ("/dbstats", "storage size and counters"),
            ("/speedtest", "latency, throughput, VC health"),
            ("/sudoers", "who can operate the bot"),
            ("/clearcache", "wipe downloads and temp files"),
            ("/dbcleanup 30", "drop history older than N days"),
            ("/addsudo · /delsudo", "grant or revoke bot access"),
            ("/sudolist", "who can operate the bot"),
            ("/stats · /activevc", "usage and live sessions"),
            ("/assistant · /setname", "rebrand the voice-chat account"),
            ("/setbio · /setpfp", "bio and profile picture"),
        ],
    ),
}


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
                "YouTube links, playlists, replies to audio files and plain text all work",
                "In groups only admins can control playback",
                "Everything is cached — replays start instantly",
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
        B.heading(f"{E('tools')} {small_caps('commands')} {DASH} {title}", 2)
        + body
        + tips
        + B.divider()
        + B.row(tabs)
        + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
        + B.footer(f"@{settings.bot_username} {BULLET} {BRAND}")
    )


# ── now playing (live, editable) ────────────────────────────────────────────
def now_playing_card(state: ChatState, track: Track | None = None) -> str:
    track = track or state.current
    if not track:
        return f"{E('moon')} <b>Nothing is playing</b>\n<blockquote>Use /play to start the session.</blockquote>"

    requester = _requester(track)
    requested = f"\n{E('user')} {requester}" if requester else ""
    status = f"{E('pause')} Paused" if state.paused else f"{E('play')} Streaming"
    quality = small_caps(settings.audio_quality)

    extras = []
    if state.autoplay:
        extras.append("autoplay")
    if state.always_on:
        extras.append("24/7")

    muted = f"{E('volume')} {state.volume}%"
    footer_bits = [muted, f"{E('loop')} {state.loop.label}", f"{E('queue')} {len(state.queue)}"]
    if extras:
        footer_bits.append(f"{E('spark')} {', '.join(extras)}")

    return (
        f"{E('headphone')} <b>{small_caps('now playing')}</b>  {BULLET}  {status}\n\n"
        f"<blockquote>{E('note')} <b>{_watch_link(track)}</b>\n"
        f"{E('microphone')} {esc(truncate(track.uploader, 34) or 'unknown artist')}  {BULLET}  "
        f"{E('clock')} {fmt_duration(track.duration)}  {BULLET}  {_source_badge(track)}{requested}</blockquote>\n\n"
        f"{progress_block(state, track)}\n\n"
        f"<code>{'  '.join(footer_bits)}</code>  {BULLET}  <i>{quality} audio</i>"
    )


def queued_card(track: Track, position: int) -> str:
    return (
        f"{E('check')} <b>Added to queue</b>\n"
        f"<blockquote>{E('note')} {esc(truncate(track.title, 60))}\n"
        f"{E('clock')} {fmt_duration(track.duration)} {BULLET} position <b>#{position}</b></blockquote>"
    )


def started_card(track: Track) -> str:
    return (
        f"{E('play')} <b>Now streaming</b>\n"
        f"<blockquote>{E('note')} {esc(truncate(track.title, 60))}\n"
        f"{E('clock')} {fmt_duration(track.duration)} {BULLET} {esc(truncate(track.uploader, 30))}</blockquote>"
    )


# ── queue ───────────────────────────────────────────────────────────────────
def queue_card(state: ChatState, page: int = 0, per_page: int = 8) -> tuple[str, int]:
    tracks = state.queue
    pages = max(1, (len(tracks) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    window = tracks[page * per_page : (page + 1) * per_page]

    header = (
        f"{E('queue')} {small_caps('queue')} {DASH} {len(tracks)} tracks "
        f"{BULLET} {fmt_duration(sum(t.duration for t in tracks))}"
    )

    if tracks:
        body = B.table(
            ["#", "Title", "Time"],
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
        now = B.note(
            f"{E('headphone')} <b>Playing</b> {BULLET} {esc(truncate(state.current.title, 44))}"
        )

    nav = ""
    if page > 0:
        nav += B.btn("‹ Prev", data=f"v:queue:{page - 1}")
    nav += B.btn(f"{page + 1} / {pages}", data="v:noop", style="primary")
    if page + 1 < pages:
        nav += B.btn("Next ›", data=f"v:queue:{page + 1}")

    actions = B.row(
        B.btn(f"{E('shuffle')} Shuffle", data="v:shuffle", style="success"),
        B.btn(f"{E('stop')} Clear", data="v:clearqueue", style="danger"),
        B.btn(f"{E('now')} Playing", data="v:np"),
    )
    footer = B.footer(
        f"page {page + 1}/{pages} {BULLET} {state.loop.label} loop {BULLET} {state.volume}% "
        f"{BULLET} autoplay {'on' if state.autoplay else 'off'}"
    )
    markup = (
        B.heading(header, 2)
        + now
        + body
        + B.divider()
        + actions
        + B.row(nav)
        + footer
    )
    return markup, pages


# ── search & downloads ──────────────────────────────────────────────────────
def search_card(query: str, tracks: Iterable[Track], *, mode: str = "play") -> str:
    tracks = list(tracks)
    rows = [
        (
            f"<b>{index + 1}</b>",
            esc(truncate(track.title, 44)),
            fmt_duration(track.duration),
        )
        for index, track in enumerate(tracks)
    ]
    body = B.table(["#", "Result", "Time"], rows)
    buttons = B.grid(
        [
            B.btn(
                f"{index + 1}. {truncate(track.title, 18)}",
                data=f"v:{'pick' if mode == 'play' else 'dl'}:{index}",
                style="primary" if index == 0 else None,
            )
            for index, track in enumerate(tracks)
        ],
        columns=2,
    )
    return (
        B.heading(f"{E('search')} {small_caps('search')} {DASH} {esc(truncate(query, 40))}", 2)
        + body
        + B.divider()
        + buttons
        + B.row(B.btn(f"{E('close')} Cancel", data="v:close", style="danger"))
        + B.footer(
            f"{E('info')} Tap a result to {'stream it' if mode == 'play' else 'download it'} "
            f"{BULLET} {len(tracks)} found"
        )
    )


def download_choice_card(track: Track) -> str:
    return (
        B.heading(f"{E('download')} {small_caps('choose a format')}", 2)
        + B.note(
            f"{E('note')} <b>{esc(truncate(track.title, 56))}</b>\n"
            f"{E('clock')} {fmt_duration(track.duration)} {BULLET} {esc(truncate(track.uploader, 28))}"
        )
        + B.row(
            B.btn(f"{E('song')} Audio · MP3", data="v:get:audio:0", style="success"),
            B.btn(f"{E('video')} Video · MP4", data="v:get:video:0", style="primary"),
        )
        + B.row(B.btn(f"{E('close')} Cancel", data="v:close", style="danger"))
        + B.footer(f"{E('cloud')} files are cached — repeats are instant")
    )


def download_card(track: Track, kind: str = "audio") -> str:
    icon = E("song") if kind == "audio" else E("video")
    return (
        f"{E('download')} <b>Preparing {kind}</b>\n"
        f"<blockquote>{icon} {esc(truncate(track.title, 56))}\n"
        f"{E('clock')} {fmt_duration(track.duration)} {BULLET} {esc(truncate(track.uploader, 28))}</blockquote>\n"
        f"<i>Fetching the best available quality…</i>"
    )


def favorites_card(items: list[dict]) -> str:
    if not items:
        return (
            f"{E('favorite')} <b>No favourites yet</b>\n"
            f"<blockquote>Save a track with /fav while it plays.</blockquote>"
        )
    body = B.table(
        ["#", "Title", "Time"],
        [
            (
                f"<b>{index + 1}</b>",
                esc(truncate(str(item.get("title", "?")), 40)),
                fmt_duration(int(item.get("duration") or 0)),
            )
            for index, item in enumerate(items[:10])
        ],
    )
    return B.heading(f"{E('favorite')} {small_caps('favourites')}", 2) + body


def history_card(items: list[dict]) -> str:
    if not items:
        return (
            f"{E('clock')} <b>Nothing played yet</b>\n"
            f"<blockquote>Your history will appear here.</blockquote>"
        )
    body = B.table(
        ["#", "Title"],
        [
            (f"<b>{index + 1}</b>", esc(truncate(str(item.get("title", "?")), 44)))
            for index, item in enumerate(items[:10])
        ],
    )
    return B.heading(f"{E('clock')} {small_caps('recently played')}", 2) + body


# ── settings / stats / lyrics / about ───────────────────────────────────────
def settings_card(cfg: dict, chat_title: str = "") -> str:
    volume = int(cfg.get("volume", settings.default_volume))
    loop = str(cfg.get("loop", "off")).title()
    autoplay = cfg.get("autoplay", True)
    always = cfg.get("always_on", False)
    body = B.kv(
        [
            (f"{E('volume')} Volume", f"<b>{volume}%</b>"),
            (f"{E('loop')} Loop", f"<b>{loop}</b>"),
            (f"{E('spark')} Autoplay", f"<b>{'On' if autoplay else 'Off'}</b>"),
            (f"{E('clock')} 24/7 mode", f"<b>{'On' if always else 'Off'}</b>"),
        ]
    )
    buttons = (
        B.row(
            B.btn(f"{E('loop')} Loop", data="v:set:loop", style="primary"),
            B.btn(f"{E('spark')} Autoplay", data="v:set:autoplay", style="success"),
        )
        + B.row(
            B.btn(f"{E('clock')} 24/7", data="v:set:always", style="primary"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
    )
    return (
        B.heading(f"{E('settings')} {small_caps('settings')}", 2)
        + body
        + B.divider()
        + buttons
        + B.footer(f"{esc(truncate(chat_title, 40) or 'this chat')} {BULLET} changes apply instantly")
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
) -> str:
    body = B.kv(
        [
            (f"{E('clock')} Uptime", f"<b>{human_time(uptime)}</b>"),
            (f"{E('chat')} Known chats", f"<b>{chats}</b>"),
            (f"{E('live')} Active players", f"<b>{active}</b>"),
            (f"{E('note')} Tracks played", f"<b>{tracks}</b>"),
            (f"{E('download')} Downloads", f"<b>{downloads}</b>"),
            (f"{E('cloud')} Cache", f"<b>{human_size(cache_bytes)}</b>"),
            (f"{E('code')} Storage", f"<b>{backend}</b>"),
        ]
    )
    return (
        B.heading(f"{E('stats')} {small_caps('statistics')}", 2)
        + body
        + B.row(
            B.btn(f"{E('live')} Active", data="v:admin:active", style="primary"),
            B.btn(f"{E('check')} Refresh", data="v:admin:stats", style="success"),
        )
        + B.footer(f"{E('bolt')} VYRON v{version} {BULLET} Kurigram + PyTgCalls {BULLET} UI: richgram")
    )


def lyrics_card(track: Track, lyrics: LyricsResult | None) -> str:
    if not lyrics or not (lyrics.plain or lyrics.synced):
        return (
            f"{E('lyrics')} <b>No lyrics found</b>\n"
            f"<blockquote>{esc(truncate(getattr(track, 'title', ''), 60))}</blockquote>"
        )
    body = esc(lyrics.as_text(3000))
    synced = "synced" if lyrics.has_sync else "plain"
    return (
        B.heading(f"{E('lyrics')} {esc(truncate(lyrics.title, 48))}", 3)
        + B.note(f"{esc(truncate(lyrics.artist, 40))} {BULLET} {synced}")
        + B.note(body, expandable=True)
        + B.footer("lyrics by LRCLIB")
    )


def about_card() -> str:
    body = B.kv(
        [
            (f"{E('code')} Stack", "Kurigram + PyTgCalls"),
            (f"{E('bolt')} UI", "Bot API 10.3 rich messages"),
            (f"{E('cloud')} Deploy", "Docker · Render · Koyeb · VPS"),
            (f"{E('spark')} Extras", "lyrics · downloads · web app"),
        ]
    )
    return (
        B.heading(f"{E('brand')} {BRAND} {DASH} about", 2)
        + B.note(
            f"{SPARK} A modern Telegram voice-chat music bot: rich cards, premium emoji, "
            f"yt-dlp search, MP3/MP4 downloads, persistent queues and a companion web app."
        )
        + body
        + B.divider()
        + B.row(
            B.btn(f"{E('code')} Source", url=settings.git_repo, style="link"),
            B.btn(f"{E('chat')} Support", url=settings.support_chat, style="link"),
        )
        + B.row(B.btn(f"{E('back')} Back", data="v:help:main", style="primary"))
        + B.footer(
            "Powered by Kurigram · PyTgCalls · yt-dlp · richgram"
        )
    )


# ── small status cards ──────────────────────────────────────────────────────
def ok_card(text: str) -> str:
    return f"{E('check')} {text}"


def warn_card(text: str) -> str:
    return f"{E('warn')} {text}"


def error_card(text: str) -> str:
    return f"{E('cross')} {text}"


def ping_card(latency_ms: float, uptime: float) -> str:
    return (
        f"{E('bolt')} <b>Pong!</b>\n"
        f"<blockquote>{E('clock')} latency <b>{latency_ms:.0f} ms</b>\n"
        f"{E('rocket')} uptime <b>{human_time(uptime)}</b></blockquote>"
    )


def webapp_card(url: str, chat_title: str = "") -> str:
    return (
        B.heading(f"{E('globe')} {BRAND} {small_caps('player')}", 2)
        + B.note(
            f"{SPARK} A full player in your pocket — now playing, queue, search, "
            f"volume and settings, all in one screen."
        )
        + B.kv(
            [
                (f"{E('headphone')} Now playing", "live progress"),
                (f"{E('queue')} Queue", "reorder, jump, clear"),
                (f"{E('search')} Search", "stream without leaving the app"),
            ]
        )
        + B.divider()
        + B.row(B.btn(f"{E('rocket')} Open player", url=url, style="primary"))
        + B.footer(f"{esc(truncate(chat_title, 34) or 'VYRON')} {BULLET} works on mobile &amp; desktop")
    )


__all__ = [
    "about_card",
    "download_card",
    "download_choice_card",
    "error_card",
    "favorites_card",
    "help_card",
    "history_card",
    "lyrics_card",
    "now_playing_card",
    "ok_card",
    "ping_card",
    "queue_card",
    "queued_card",
    "search_card",
    "settings_card",
    "start_card",
    "started_card",
    "stats_card",
    "warn_card",
    "webapp_card",
]
