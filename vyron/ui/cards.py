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
from vyron.ui.progress import compact_number
from vyron.ui.theme import BRAND, BULLET, DASH, E, SPARK, small_caps

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
) -> str:
    """The first card anyone sees: what this bot does, and how to start."""
    served = stats.get("chats", 0)
    tracks = stats.get("tracks", 0)
    mode = "Streaming ready" if streaming else "File mode"
    detail = (
        "voice chats and files"
        if streaming
        else "no assistant session yet — <code>/play</code> sends the file"
    )
    features = B.bullets(
        [
            "<b>Play</b> — a link, a reply, or <code>/play believer</code>",
            "<b>Search</b> — the best match first, pick it with one tap",
            "<b>Download</b> — MP3 320 or MP4 720p with cover art",
            "<b>API</b> — drop-in <code>/v1</code> for other bots",
        ]
    )
    guide = B.details(
        f"{E('rocket')} <b>Set up in three steps</b>",
        B.bullets(
            [
                "Add the bot and the assistant account to a group",
                "Give it <b>manage voice chats</b> and <b>delete messages</b>",
                "Start a voice chat, then send <code>/play believer</code>",
            ],
            ordered=True,
        ),
        open=False,
    )
    buttons = (
        B.row(
            B.btn(f"{E('play')} Player", data="v:app", style="primary"),
            B.btn(f"{E('queue')} Commands", data="v:help:main"),
        )
        + B.row(
            B.btn(f"{E('rocket')} Add to group", url=f"https://t.me/{settings.bot_username}?startgroup=true"),
            B.btn(f"{E('info')} About", data="v:about"),
        )
        + B.row(
            B.btn(f"{E('chat')} Support", url=settings.support_chat, style="link"),
            B.btn(f"{E('star')} Updates", url=settings.updates_channel, style="link"),
        )
    )
    return (
        B.heading(f"{E('brand')} {esc(BRAND)}", 2)
        + B.note(
            f"<b>{esc(truncate(name, 40))}</b> · {mode}\n{detail}"
        )
        + features
        + guide
        + B.divider()
        + buttons
        + B.footer(
            f"{served} chats · {tracks} tracks played · v{_version()}"
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
            ("/gadmin", "the group manager panel"),
            ("/rules · /setrules", "read or set this chat's rules"),
            ("/chatinfo", "id, members, slow mode, invites"),
            ("/settitle · /setdesc", "rename the chat"),
            ("/setgphoto · /delgphoto", "chat picture from a reply"),
            ("/slowmode 30s|off", "space out messages"),
            ("/invitelink · /revokeinvite", "rotate the invite link"),
            ("/approve · /approved", "exempt trusted members"),
            ("/zombies [kick]", "clean up deleted accounts"),
            ("/report", "flag a message to the admins"),
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
            ("/logs [errors|warn|info]", "owner journal: start, stop, errors"),
            ("/logs export · /logs clear", "download or empty the journal"),
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
    """The live card — classic HTML only, because it is edited in place."""
    track = track or state.current
    if not track:
        return (
            f"{E('moon')} <b>Nothing is playing</b>\n"
            "<blockquote>Send <code>/play</code> with a song name, a link or a reply.</blockquote>"
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
            f"\n<i>up next</i>  {esc(truncate(upcoming.title, 40))}"
            f" · {fmt_duration(upcoming.duration)}"
        )

    flags = []
    if state.autoplay:
        flags.append("autoplay")
    if state.always_on:
        flags.append("24/7")
    footer = f"{state.volume}% volume · {state.loop.label} loop · {len(state.queue)} queued"
    if flags:
        footer += f" · {', '.join(flags)}"

    return (
        f"{glyph} <b>NOW PLAYING</b> · {status}\n\n"
        f"<blockquote><b>{_watch_link(track)}</b>\n{meta}</blockquote>\n"
        f"{progress_block(state, track)}{next_line}\n"
        f"<i>{footer}</i>"
    )


def queued_card(track: Track, position: int) -> str:
    return (
        f"{E('check')} <b>Added to queue</b>\n"
        f"<blockquote>{esc(truncate(track.title, 60))}\n"
        f"#{position} · {fmt_duration(track.duration)} · {esc(truncate(track.uploader, 30) or 'unknown')}"
        f"</blockquote>"
    )


def started_card(track: Track) -> str:
    return (
        f"{E('play')} <b>Now streaming</b>\n"
        f"<blockquote>{esc(truncate(track.title, 60))}\n"
        f"{fmt_duration(track.duration)} · {esc(truncate(track.uploader, 30) or 'unknown')}</blockquote>"
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
        now = B.note(
            f"{E('live')} <b>playing</b> · {esc(truncate(state.current.title, 44))}"
        )

    nav = ""
    if page > 0:
        nav += B.btn("‹ prev", data=f"v:queue:{page - 1}")
    nav += B.btn(f"{page + 1} / {pages}", data="v:noop", style="primary")
    if page + 1 < pages:
        nav += B.btn("next ›", data=f"v:queue:{page + 1}")

    return (
        B.heading(
            f"{E('queue')} queue · {len(tracks)} tracks · "
            f"{fmt_duration(sum(t.duration for t in tracks))}",
            2,
        )
        + now
        + body
        + B.divider()
        + B.row(
            B.btn(f"{E('shuffle')} Shuffle", data="v:shuffle", style="success"),
            B.btn(f"{E('now')} Playing", data="v:np"),
            B.btn(f"{E('stop')} Clear", data="v:clearqueue", style="danger"),
        )
        + B.row(nav)
        + B.footer(
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
    bits.append(f"<code>{fmt_duration(track.duration)}</code>")
    if getattr(track, "views", 0):
        bits.append(f"{compact_number(track.views)} plays")
    return f" {DOT} ".join(bits)


def search_card(query: str, tracks: Iterable[Track], *, mode: str = "play") -> str:
    """Results as a ranked list: the top hit is marked and carries the artwork."""
    tracks = list(tracks)
    verb = "play" if mode == "play" else "download"
    if not tracks:
        return (
            f"{E('search')} <b>No results</b>\n"
            f"<blockquote>Nothing came back for <b>{esc(truncate(query, 48))}</b>.\n"
            f"Try the artist name, or paste a link.</blockquote>"
        )

    items: list[str] = []
    for index, track in enumerate(tracks):
        title = _watch_link(track)
        if index == 0:
            title = f"<mark>{title}</mark>"
        items.append(f"{title}\n<i>{_meta_line(track)}</i>")

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
        B.heading(f"{E('search')} results · {esc(truncate(query, 40))}", 2)
        + B.image(tracks[0].thumbnail)
        + B.bullets(items, ordered=True)
        + B.divider()
        + buttons
        + actions
        + B.footer(f"{len(tracks)} matches · ranked by relevance, length and reach")
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
            ("volume", f"<b>{volume}%</b>"),
            ("loop", f"<b>{loop}</b>"),
            ("autoplay", f"<b>{'on' if autoplay else 'off'}</b>"),
            ("24/7 mode", f"<b>{'on' if always else 'off'}</b>"),
        ]
    )
    return (
        B.heading(f"{E('settings')} settings", 2)
        + body
        + B.divider()
        + B.row(
            B.btn(f"{E('loop')} Loop", data="v:set:loop", style="primary"),
            B.btn(f"{E('spark')} Autoplay", data="v:set:autoplay", style="success"),
            B.btn(f"{E('clock')} 24/7", data="v:set:always"),
        )
        + B.footer(f"{esc(truncate(chat_title, 40) or 'this chat')} · changes apply instantly")
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
        if links.get("player"):
            buttons.append(B.btn(f"{E('crown')} Owner console", data="v:app", style="primary"))
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
                B.btn(f"{E('crown')} Owner console", data="v:app", style="primary"),
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
            B.btn(f"{E('close')} Close", data="v:close", style="link"),
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
            B.btn(f"{E('close')} Close", data="v:close", style="link"),
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
    *,
    owner_id: int = 0,
    ttl_days: int = 30,
) -> str:
    """The owner's API credential — the Mini App needs no token at all."""
    root = (base or "").rstrip("/") or "WEBAPP_URL"
    return (
        B.heading(f"{E('crown')} {small_caps('owner token')}", 2)
        + B.note(
            f"{SPARK} For the <b>API</b> and for scripts. The Mini App already knows "
            f"you from Telegram — just tap <b>Player</b>."
        )
        + B.note(f"{E('key')} <code>{esc(token)}</code>")
        + B.kv(
            [
                (f"{E('user')} Owner", f"<code>{owner_id or '—'}</code>"),
                (f"{E('clock')} Valid for", f"<b>{ttl_days} days</b> {BULLET} rotate with <code>/apitoken</code>"),
                (f"{E('globe')} Header", "<code>X-Owner-Token: …</code>"),
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
        + B.row(
            B.btn(f"{E('play')} Open player", data="v:app", style="primary"),
            B.btn(f"{E('code')} API docs", url=f"{root}/v1/docs", style="success"),
        )
        + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
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
        B.heading(f"{E('play')} player", 2)
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
    head = B.kv(
        [
            (f"{_E('clock')} Uptime", f"<b>{uptime}</b>"),
            (f"{_E('note')} Buffered", f"<b>{int(stats.get('buffered') or 0)}</b> / {int(stats.get('seq') or 0)}"),
            (f"{_E('warn')} Warnings", f"<b>{int(stats.get('warnings') or 0)}</b>"),
            (f"{_E('close')} Errors", f"<b>{int(stats.get('errors') or 0)}</b>"),
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
        B.heading(f"{_E('code')} {small_caps(title)}", 2)
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
    glyph = E(icon or glyph_name)
    body = f"{glyph} <b>{title}</b>"
    if detail:
        body += "\n" + detail
    markup = B.heading(f"{glyph} {small_caps(title)}", 2)
    if detail:
        markup += B.note(detail)
    pairs = [(f"{E('info')} {key}", value) for key, value in extra]
    if pairs:
        markup += B.kv(pairs)
    if actions:
        markup += B.divider() + actions
    if footer:
        markup += B.footer(footer)
    return markup


def rules_card(title: str, rules: str, *, admins: int = 0, can_edit: bool = False) -> str:
    """``/rules`` — the chat's own rulebook, readable by everyone."""
    body = (
        B.heading(f"{E('note')} {small_caps('rules')} {DASH} {esc(truncate(title, 34))}", 2)
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
    pairs = [
        (f"{E('chat')} Title", f"<b>{esc(truncate(str(info.get('title') or 'this chat'), 40))}</b>"),
        (f"{E('code')} ID", f"<code>{info.get('id')}</code>"),
        (f"{E('link')} Username", f"@{esc(info['username'])}" if info.get("username") else "<i>private</i>"),
        (f"{E('user')} Members", f"<b>{compact_number(int(info.get('members') or 0))}</b>"
                                + (f" {BULLET} {compact_number(int(info.get('online') or 0))} online"
                                   if info.get("online") else "")),
        (f"{E('crown')} Admins", f"<b>{int(info.get('admins') or 0)}</b>"),
        (f"{E('clock')} Slow mode", f"<b>{slow_label(int(info.get('slowmode') or 0))}</b>"),
        (f"{E('bolt')} Created", f"<b>{esc(str(info.get('created') or '—'))}</b>"),
        (f"{E('shield')} Protected", "on" if info.get("protected") else "off"),
        (f"{E('chat')} Forum", "on" if info.get("forum") else "off"),
        (f"{E('cloud')} Data centre", f"DC{info.get('dc')}" if info.get("dc") else "—"),
    ]
    if info.get("linked"):
        pairs.append((f"{E('link')} Linked channel", esc(str(info["linked"]))))
    if info.get("pinned"):
        pairs.append((f"{E('star')} Pinned", esc(truncate(str(info["pinned"]), 44))))
    body = (
        B.heading(f"{E('info')} {small_caps('chat info')}", 2)
        + B.kv(pairs)
    )
    if info.get("description"):
        body += B.note(f"<b>About</b>\n{esc(truncate(str(info['description']), 220))}")
    if info.get("invite"):
        body += B.row(
            B.btn(f"{E('link')} Open invite", url=str(info["invite"]), style="primary"),
            B.btn(f"{E('close')} Close", data="v:close", style="danger"),
        )
    else:
        body += B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
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
    state = B.kv(
        [
            (f"{E('note')} Rules", "<b>set</b>" if rules else "<i>not set</i>"),
            (f"{E('clock')} Slow mode", f"<b>{slow_label(slowmode)}</b>"),
            (f"{E('shield')} Locks on", f"<b>{locked}</b>"),
            (f"{E('user')} Approved", f"<b>{approved}</b>"),
            (f"{E('warn')} Warn limit", f"<b>{warn_limit}</b>"),
            (f"{E('shield')} Captcha", "<b>on</b>" if captcha else "<i>off</i>"),
            (f"{E('bolt')} Bot rights", health),
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
                "<code>/settitle</code> · <code>/setdesc</code> · <code>/setgphoto</code> — chat identity",
                "<code>/slowmode 30</code> · <code>/slowmode off</code>",
                "<code>/setrules …</code> · <code>/rules</code> · <code>/clearrules</code>",
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
        B.heading(f"{E('crown')} {small_caps('group manager')}", 2)
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
    body = B.heading(f"{E('bolt')} {small_caps('zombies')}", 2) + B.note(headline)
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
            B.heading(f"{E('user')} {small_caps('approved users')}", 2)
            + B.note("Nobody yet. <code>/approve</code> on a reply adds someone.")
            + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
        )
    rows = "".join(
        f"<tr><td>{esc(name)}</td><td><code>{uid}</code></td></tr>" for name, uid in entries[:limit]
    )
    return (
        B.heading(f"{E('user')} {small_caps('approved users')}", 2)
        + B.note(f"{len(entries)} exempt from locks and anti-flood")
        + f"<table><tr><th>user</th><th>id</th></tr>{rows}</table>"
        + B.row(B.btn(f"{E('close')} Close", data="v:close", style="danger"))
        + B.footer(f"{E('info')} /unapprove on a reply or id removes one")
    )


def captcha_card(mention: str, *, seconds: int = 120, user_id: int = 0) -> str:
    """New-member gate: one tap proves there is a human behind the account."""
    return (
        B.heading(f"{E('shield')} {small_caps('verify to speak')}", 2)
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
