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
def start_card(
    name: str,
    stats: dict,
    *,
    streaming: bool = True,
    owner_token: str = "",
) -> str:
    served = stats.get("chats", 0)
    tracks = stats.get("tracks", 0)
    features = B.kv(
        [
            (f"{E('bolt')} Instant play", "links, replies &amp; plain text"),
            (f"{E('search')} Smart search", "top results, one tap to stream"),
            (f"{E('download')} Downloads", "MP3 &amp; MP4 with covers"),
            (f"{E('lyrics')} Lyrics", "synced via LRCLIB"),
            (f"{E('globe')} Web player", "queue, lyrics &amp; cast from a browser"),
            (f"{E('code')} Music API", "drop-in <code>/v1</code> API for other bots"),
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
    open_app = ""
    if settings.webapp_ready:
        open_app = B.row(
            B.btn(f"{E('globe')} Open the player", url=f"{settings.webapp_url}/app/", style="primary")
        )
    owner_row = ""
    if owner_token and settings.webapp_ready:
        owner_row = B.row(
            B.btn(
                f"{E('crown')} Owner console",
                url=_with_owner_token(_app_root(settings.webapp_url), owner_token),
                style="success",
            )
        )
    api_row = ""
    if settings.music_api and settings.api_base:
        api_row = B.row(
            B.btn(f"{E('code')} Music API docs", url=f"{settings.api_base}/v1/docs", style="link")
        )
    buttons = (
        B.row(B.btn(f"{E('rocket')} Add to group", url=f"https://t.me/{settings.bot_username}?startgroup=true", style="primary"))
        + open_app
        + owner_row
        + api_row
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
            ("/api", "the music API (keys, docs)"),
            ("/exportpl <name>", "playlist → JSON file"),
            ("/importpl", "reply to that file to restore it"),
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
            ("/api", "music API card, docs and endpoints"),
            ("/getapi [label] [scopes=…]", "mint an API key (owner)"),
            ("/listkey · /revoke · /rotatekey", "manage API keys (owner)"),
            ("/apiusage", "API traffic per key (owner)"),
            ("/apitoken", "owner token for web app + API"),
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
    api: dict | None = None,
    links: dict[str, str] | None = None,
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
    api_block = ""
    if api and api.get("enabled"):
        api_block = B.kv(
            [
                (f"{E('code')} API keys", f"<b>{int(api.get('keys') or 0)}</b> / {int(api.get('keys_total') or 0)}"),
                (f"{E('download')} API requests", f"<b>{int(api.get('requests') or 0)}</b>"),
                (f"{E('cloud')} API traffic", f"<b>{human_size(int(api.get('bytes') or 0))}</b>"),
                (f"{E('shield')} API scopes", ", ".join(api.get("scopes") or []) or "read, search, download"),
            ]
        )
    owner_row = ""
    if links:
        buttons = []
        if links.get("app"):
            buttons.append(B.btn(f"{E('crown')} Owner console", url=links["app"], style="primary"))
        if links.get("api"):
            buttons.append(B.btn(f"{E('code')} API docs", url=links["api"], style="success"))
        if links.get("token"):
            buttons.append(B.btn(f"{E('shield')} Owner token", url=links["token"], style="link"))
        if buttons:
            owner_row = B.row(*buttons[:3])
    return (
        B.heading(f"{E('stats')} {small_caps('statistics')}", 2)
        + body
        + api_block
        + B.row(
            B.btn(f"{E('live')} Active", data="v:admin:active", style="primary"),
            B.btn(f"{E('check')} Refresh", data="v:admin:stats", style="success"),
        )
        + owner_row
        + B.footer(f"{E('bolt')} VYRON v{version} {BULLET} Kurigram + PyTgCalls {BULLET} UI: richgram")
    )


def lyrics_card(track: Track, lyrics: LyricsResult | None) -> str:
    if not lyrics or not (lyrics.plain or lyrics.synced):
        return (
            f"{E('lyrics')} <b>No lyrics found</b>\n"
            f"<blockquote>{esc(truncate(getattr(track, 'title', ''), 60))}</blockquote>"
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
        B.heading(f"{E('lyrics')} {esc(truncate(lyrics.title, 48))}", 3)
        + B.note(f"{esc(truncate(lyrics.artist, 40))} {BULLET} {synced} {BULLET} LRCLIB")
        + preview
        + B.details(
            f"{E('note')} <b>Full lyrics</b>",
            f"<blockquote>{esc(lyrics.as_text(3000))}</blockquote>",
        )
        + B.footer(f"open /app for lyrics that scroll with the song {BULLET} {BRAND}")
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
    owner_link: str = "",
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
    body = B.kv(
        [
            (f"{E('globe')} Base URL", f"<code>{esc(root or 'set WEBAPP_URL')}</code>"),
            (f"{E('bolt')} Status", f"<b>{status}</b> {BULLET} {auth}"),
            (f"{E('clock')} Rate limit", f"<b>{int(stats.get('rate_limit') or 0)}</b> req/min per key"),
            (f"{E('key')} Active keys", f"<b>{int(stats.get('keys') or 0)}</b> of {int(stats.get('keys_total') or 0)}"),
            (f"{E('download')} Served", f"<b>{served}</b> requests {BULLET} {human_size(int(stats.get('bytes') or 0))}"),
            (f"{E('cloud')} Storage", f"<b>{esc(str(stats.get('storage') or 'json'))}</b> {BULLET} API v2.0"),
        ]
    )
    if metrics:
        body += B.kv(
            [
                (f"{E('stats')} Hits today", f"<b>{int(metrics.get('requests') or 0)}</b> {BULLET} "
                                            f"{int(metrics.get('downloads') or 0)} downloads"),
                (f"{E('clock')} Latency", f"p50 <b>{metrics.get('latency_ms', {}).get('p50', 0)}ms</b> {BULLET} "
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
                ("<b>GET</b>", "/v1/search?q=", "<code>srch</code>"),
                ("<b>GET</b>", "/v1/lyrics?title=", "<code>read</code>"),
                ("<b>GET</b>", "/v1/me", "<code>—</code>"),
                ("<b>GET</b>", "/v1/metrics", "<code>adm</code>"),
            ],
        ),
        open=not compact,
    )
    legacy = B.details(
        f"{E('shield')} <b>Eldian-compatible</b>",
        B.table(
            ["Method", "Path"],
            [
                ("<b>POST</b>", "/v1/track/by-video-id"),
                ("<b>POST</b>", "/v1/track/by-query"),
                ("<b>GET</b>", "/v1/info/by-video-id"),
                ("<b>GET</b>", "/v1/key"),
            ],
        )
        + B.note(f"{E('info')} Existing Eldian clients keep working — just swap the base URL."),
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
        B.heading(f"{E('globe')} {small_caps('music api')} {DASH} VYRON", 2)
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
                B.btn(f"{E('crown')} Owner console", url=owner_link, style="primary"),
                B.btn(f"{E('shield')} Owner help", data="v:help:power", style="link"),
            )
            if owner and owner_link
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
) -> str:
    """The one-and-only view of a freshly minted key."""
    root = (base or "").rstrip("/")
    expiry = (
        "never expires"
        if not expires_at
        else f"expires {time.strftime('%d %b %Y', time.gmtime(expires_at))}"
    )
    return (
        B.heading(f"{E('key')} {small_caps('api key')} {DASH} ready", 2)
        + B.note(
            f"{E('warn')} <b>Copy it now</b> {DASH} this is the only time the full key is shown. "
            f"It is stored hashed, so nobody (not even the bot) can show it again."
        )
        + B.note(f"{E('key')} <code>{esc(key)}</code>")
        + B.kv(
            [
                (f"{E('note')} Label", f"<b>{esc(label)}</b>"),
                (f"{E('shield')} Scopes", _scope_chips(scopes or ["read", "search", "download"])),
                (f"{E('clock')} Rate limit", f"<b>{rate}</b> req/min {BULLET} {expiry}"),
                (f"{E('globe')} Base URL", f"<code>{esc(root or 'set WEBAPP_URL')}</code>"),
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
            B.btn(f"{E('queue')} List keys", data="v:noop", style="link"),
        )
        + B.footer(
            f"{E('info')} revoke with <code>/revoke {key[:12]}…</code> {BULLET} "
            f"rotate with <code>/rotatekey {key[:12]}…</code>"
        )
    )


def api_keys_card(keys: list[dict], base: str) -> str:
    if not keys:
        return (
            B.heading(f"{E('key')} {small_caps('api keys')}", 2)
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
        B.heading(f"{E('key')} {small_caps('api keys')} {DASH} {active}/{len(keys)} active", 2)
        + B.table(["Label", "Key", "Scopes", "Uses", "State"], rows)
        + B.note(
            f"{E('shield')} Keys are stored as SHA-256 hashes. The full value is only shown "
            f"when it is minted {DASH} rotate anything you have lost."
        )
        + B.row(
            B.btn(f"{E('code')} Docs", url=f"{(base or '').rstrip('/')}/v1/docs", style="primary"),
            B.btn(f"{E('spark')} New key", data="v:noop", style="link"),
        )
        + B.footer(f"revoke <code>/revoke &lt;id|prefix&gt;</code> {BULLET} rotate <code>/rotatekey</code> {BULLET} {BRAND}")
    )


def api_usage_card(
    stats: dict,
    keys: list[dict],
    base: str,
    *,
    sudo: bool = False,
    metrics: dict | None = None,
) -> str:
    totals = B.kv(
        [
            (f"{E('key')} Active keys", f"<b>{int(stats.get('keys') or 0)}</b> / {int(stats.get('keys_total') or 0)}"),
            (f"{E('download')} Requests", f"<b>{int(stats.get('requests') or 0)}</b>"),
            (f"{E('cloud')} Bytes served", f"<b>{human_size(int(stats.get('bytes') or 0))}</b>"),
            (f"{E('clock')} Rate limit", f"<b>{int(stats.get('rate_limit') or 0)}</b> req/min"),
            (f"{E('globe')} Mode", "open" if stats.get("open") else "keyed"),
            (f"{E('cloud')} Storage", f"<b>{esc(str(stats.get('storage') or 'json'))}</b>"),
        ]
    )
    if metrics:
        totals += B.kv(
            [
                (f"{E('bolt')} This process", f"<b>{int(metrics.get('requests') or 0)}</b> hits "
                                              f"{BULLET} <b>{int(metrics.get('rate_limited') or 0)}</b> throttled"),
                (f"{E('clock')} Latency", f"p50 <b>{metrics.get('latency_ms', {}).get('p50', 0)}ms</b> "
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
        B.heading(f"{E('stats')} {small_caps('api usage')}", 2)
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
    body = B.kv(
        [
            (f"{E('code')} Stack", "Kurigram + PyTgCalls"),
            (f"{E('bolt')} UI", "Bot API 10.3 rich messages"),
            (f"{E('cloud')} Deploy", "Docker · Render · Koyeb · VPS"),
            (f"{E('spark')} Extras", "lyrics · downloads · web app"),
            (f"{E('code')} Music API", "Eldian-compatible <code>/v1</code>, same URL"),
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


def owner_access_card(
    token: str,
    base: str,
    app_url: str,
    *,
    owner_id: int = 0,
    ttl_days: int = 30,
) -> str:
    """One card that hands the owner browser + API access."""
    root = (base or "").rstrip("/")
    app_root = _app_root(app_url) or f"{root}/app/"
    link = _with_owner_token(app_root, token)
    return (
        B.heading(f"{E('crown')} {small_caps('owner access')}", 2)
        + B.note(
            f"{SPARK} One signed token unlocks the <b>web player</b> and the "
            f"<b>music API</b> from any browser — no Telegram session needed."
        )
        + B.note(f"{E('key')} <code>{esc(token)}</code>")
        + B.kv(
            [
                (f"{E('user')} Owner", f"<code>{owner_id or '—'}</code>"),
                (f"{E('clock')} Valid for", f"<b>{ttl_days} days</b> {BULLET} rotate with <code>/apitoken</code>"),
                (f"{E('globe')} Web app", f"<code>{esc(link)}</code>"),
                (f"{E('code')} API", f"<code>X-Owner-Token: …</code> on {esc(root or 'WEBAPP_URL')}/v1"),
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
            open=True,
        )
        + B.divider()
        + B.row(B.btn(f"{E('rocket')} Open owner console", url=link, style="primary"))
        + B.row(
            B.btn(f"{E('code')} API docs", url=f"{root}/v1/docs" if root else settings.git_repo, style="success"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
        + B.footer(
            f"{E('shield')} keep it private {DASH} it grants every API scope {BULLET} "
            f"expires automatically; changing <code>BOT_TOKEN</code> revokes it instantly"
        )
    )


def ping_card(latency_ms: float, uptime: float) -> str:
    return (
        f"{E('bolt')} <b>Pong!</b>\n"
        f"<blockquote>{E('clock')} latency <b>{latency_ms:.0f} ms</b>\n"
        f"{E('rocket')} uptime <b>{human_time(uptime)}</b></blockquote>"
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


def _with_owner_token(url: str, token: str) -> str:
    if not url or not token:
        return url
    joiner = "&" if "?" in url else "?"
    return f"{url}{joiner}ot={token}"


def webapp_card(url: str, chat_title: str = "", owner_token: str = "") -> str:
    root = _app_root(url)
    owner_row = (
        B.row(
            B.btn(
                f"{E('crown')} Owner console",
                url=_with_owner_token(root, owner_token),
                style="success",
            )
        )
        if owner_token
        else ""
    )
    return (
        B.heading(f"{E('globe')} {BRAND} {small_caps('player')}", 2)
        + B.note(
            f"{SPARK} A full player in your pocket — play on <b>this device</b> or "
            f"push the track into this chat's <b>voice chat</b>, from one screen."
        )
        + B.kv(
            [
                (f"{E('headphone')} Now playing", "live progress, seek, volume"),
                (f"{E('queue')} Queue", "device &amp; voice-chat tabs"),
                (f"{E('lyrics')} Lyrics", "synced, follows the song"),
                (f"{E('search')} Search", "play without leaving the app"),
                (f"{E('spark')} Extras", "shuffle, repeat, media keys"),
            ]
        )
        + B.details(
            f"{E('info')} <b>How it works</b>",
            B.bullets(
                [
                    "Tap the <b>▶</b> button on any row to play it in the browser",
                    "Tap <b>📻</b> to cast the same track into the voice chat",
                    "The dock keeps playing while you browse other views",
                ]
            ),
        )
        + B.divider()
        + B.row(B.btn(f"{E('rocket')} Open player", url=root, style="primary"))
        + owner_row
        + B.row(
            B.btn(f"{E('queue')} Commands", data="v:help:main", style="success"),
            B.btn(f"{E('chat')} Support", url=settings.support_chat, style="link"),
        )
        + B.footer(
            f"{esc(truncate(chat_title, 34) or 'VYRON')} {BULLET} works on mobile &amp; desktop"
            + (" · owner tools unlocked" if owner_token else "")
        )
    )


__all__ = [
    "about_card",
    "api_key_card",
    "api_keys_card",
    "api_usage_card",
    "music_api_card",
    "download_card",
    "download_choice_card",
    "error_card",
    "favorites_card",
    "help_card",
    "history_card",
    "lyrics_card",
    "now_playing_card",
    "owner_access_card",
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
