# ---------------------------------------------------------------------------
#  VYRON — card builders
#
#  Cards that are *live* (now-playing, queue) are written in classic HTML so
#  they can be edited in place.  Static cards use the rich-message vocabulary
#  (headings, tables, collapsible sections) for a much more premium look — the
#  delivery layer down-converts them automatically when rich messages are not
#  available.
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Iterable

from vyron.config import settings
from vyron.core.queue import ChatState, Track
from vyron.core.lyrics import LyricsResult
from vyron.ui.progress import (
    fmt_duration,
    human_size,
    human_time,
    percentage,
    progress_bar,
    truncate,
)
from vyron.ui.rich import esc
from vyron.ui.theme import BRAND, BULLET, DASH, E, SPARK, small_caps


# ── shared bits ─────────────────────────────────────────────────────────────
def _requester(track: Track) -> str:
    if not track.requested_name:
        return ""
    return f'<a href="tg://user?id={int(track.requested_by)}">{esc(truncate(track.requested_name, 28))}</a>'


def _source_badge(track: Track) -> str:
    return small_caps(track.source[:12] or "youtube")


def progress_block(state: ChatState, track: Track) -> str:
    elapsed = state.elapsed()
    total = track.duration or 0
    bar = progress_bar(elapsed, total, length=14)
    if total:
        return (
            f"<code>{bar}</code>\n"
            f"<code>{fmt_duration(elapsed)}</code> {DASH} "
            f"<code>{fmt_duration(total)}</code>  "
            f"({percentage(elapsed, total)}%)"
        )
    return f"<code>{bar}</code>\n<code>live {DASH} {fmt_duration(elapsed)}</code>"


# ── start / help ────────────────────────────────────────────────────────────
def start_card(name: str, stats: dict) -> str:
    served = stats.get("chats", 0)
    tracks = stats.get("tracks", 0)
    return f"""<h2>{E('brand')} {BRAND}</h2>
<p>{SPARK} <b>High-fidelity voice-chat streaming</b> for Telegram — search, queue, download and control everything from one clean panel.</p>
<table>
<tr><td>{E('bolt')} Instant play</td><td>links, replies &amp; plain text</td></tr>
<tr><td>{E('search')} Smart search</td><td>pick from the top results</td></tr>
<tr><td>{E('download')} Downloads</td><td>MP3 &amp; MP4, cached on disk</td></tr>
<tr><td>{E('lyrics')} Lyrics</td><td>synced from LRCLIB</td></tr>
<tr><td>{E('shield')} Admin-first</td><td>safe controls, no abuse</td></tr>
</table>
<details open><summary>{E('rocket')} Get started</summary>
<p>1. Add me to a group<br/>2. Give me <b>manage voice chats</b><br/>3. Start a voice chat, then <code>/play believer</code></p></details>
<footer>Hi <b>{esc(truncate(name, 40))}</b> {BULLET} {served} chats {BULLET} {tracks} tracks played</footer>"""


_HELP: dict[str, list[tuple[str, str]]] = {
    "main": [
        ("start", "open the home card"),
        ("play <song|link>", "stream audio in the voice chat"),
        ("vplay <song|link>", "stream video"),
        ("song <song|link>", "send the MP3 to this chat"),
        ("video <song|link>", "send the MP4 to this chat"),
        ("search <text>", "browse results, then pick"),
        ("lyrics [song]", "lyrics for the current track"),
        ("ping", "latency + uptime"),
    ],
    "playback": [
        ("pause / resume", "hold or continue the stream"),
        ("skip [n]", "jump forward n tracks"),
        ("stop", "end the session and leave"),
        ("seek <0:45>", "jump inside the current track"),
        ("volume <1-200>", "set assistant volume"),
        ("loop [off|one|all]", "cycle the repeat mode"),
        ("shuffle", "shuffle what is queued"),
        ("np", "refresh the now-playing card"),
    ],
    "queue": [
        ("queue [page]", "paginated queue view"),
        ("remove <pos>", "drop one entry"),
        ("move <from> <to>", "reorder the queue"),
        ("jump <pos>", "play that entry right now"),
        ("clear", "empty the queue, keep playing"),
    ],
    "tools": [
        ("fav / favs", "save and list favourites"),
        ("history", "your recently played"),
        ("playlist <url>", "queue up to 50 tracks"),
        ("settings", "per-chat defaults"),
        ("emojis", "premium emoji pack status"),
    ],
}


def help_card(section: str = "main") -> str:
    section = section if section in _HELP else "main"
    rows = "".join(
        f"<tr><td><code>/{cmd}</code></td><td>{esc(desc)}</td></tr>"
        for cmd, desc in _HELP[section]
    )
    return f"""<h2>{E('tools')} {small_caps('commands')} {DASH} {section.title()}</h2>
<table>{rows}</table>
<details><summary>{E('info')} Good to know</summary>
<p>• Works with YouTube links, playlists, replies to audio files and plain text.<br/>
• In groups only admins can control playback.<br/>
• Everything is cached, so replays start instantly.</p></details>
<footer>{settings.bot_username} {BULLET} {BRAND}</footer>"""


# ── now playing (editable HTML lane) ────────────────────────────────────────
def now_playing_card(state: ChatState, track: Track | None = None) -> str:
    track = track or state.current
    if not track:
        return f"{E('moon')} <b>Nothing is playing</b>\n<blockquote>Use /play to start the session.</blockquote>"

    requester = _requester(track)
    requested = f"\n{E('user')} {requester}" if requester else ""
    status = f"{E('pause')} Paused" if state.paused else f"{E('play')} Streaming"
    quality = small_caps(settings.audio_quality)
    loop = state.loop.label
    extra = [] if not state.autoplay else ["autoplay"]
    if state.always_on:
        extra.append("24/7")

    footer_bits = [f"{E('volume')} {state.volume}%", f"{E('loop')} {loop}", f"{E('queue')} {len(state.queue)}"]
    if extra:
        footer_bits.append(f"{E('spark')} {', '.join(extra)}")

    title = esc(truncate(track.title, 68))
    link = track.watch_url
    heading = f'<a href="{esc(link)}">{title}</a>' if link else title

    return f"""{E('headphone')} <b>{small_caps('now playing')}</b>  {BULLET}  {status}

<blockquote>{E('note')} <b>{heading}</b>
{E('microphone')} {esc(truncate(track.uploader, 34) or 'unknown artist')}  {BULLET}  {E('clock')} {fmt_duration(track.duration)}  {BULLET}  {_source_badge(track)}{requested}</blockquote>

{progress_block(state, track)}

<code>{'  '.join(footer_bits)}</code>  {BULLET}  <i>{quality} audio</i>"""


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

    if not tracks:
        body = f"<p>{E('moon')} The queue is empty — add something with <code>/play</code>.</p>"
    else:
        rows = "".join(
            f"<tr><td><b>{page * per_page + index + 1}</b></td>"
            f"<td>{esc(truncate(track.title, 48))}</td>"
            f"<td>{fmt_duration(track.duration)}</td></tr>"
            for index, track in enumerate(window)
        )
        body = f"<table>{rows}</table>"

    total_time = sum(t.duration for t in tracks)
    current = state.current
    header = (
        f"{E('queue')} <b>{small_caps('queue')}</b> {DASH} {len(tracks)} tracks {BULLET} {fmt_duration(total_time)}"
    )
    now = (
        f"<blockquote>{E('headphone')} <b>Playing</b> {BULLET} {esc(truncate(current.title, 44))}</blockquote>\n"
        if current
        else ""
    )
    footer = f"<footer>page {page + 1}/{pages} {BULLET} {state.loop.label} loop {BULLET} {state.volume}%</footer>"
    return f"<h2>{header}</h2>\n{now}{body}\n{footer}", pages


# ── search / downloads ──────────────────────────────────────────────────────
def search_card(query: str, tracks: Iterable[Track]) -> str:
    tracks = list(tracks)
    rows = "".join(
        f"<tr><td><b>{index + 1}</b></td>"
        f"<td>{esc(truncate(track.title, 46))}</td>"
        f"<td>{fmt_duration(track.duration)}</td></tr>"
        for index, track in enumerate(tracks)
    )
    return f"""<h2>{E('search')} {small_caps('search')} {DASH} {esc(truncate(query, 40))}</h2>
<table>{rows}</table>
<footer>{E('info')} Tap a result below to stream it {BULLET} {len(tracks)} found</footer>"""


def download_card(track: Track, kind: str = "audio") -> str:
    icon = E("song") if kind == "audio" else E("video")
    return (
        f"{E('download')} <b>Preparing {kind}</b>\n"
        f"<blockquote>{icon} {esc(truncate(track.title, 56))}\n"
        f"{E('clock')} {fmt_duration(track.duration)} {BULLET} {esc(truncate(track.uploader, 28))}</blockquote>"
        f"\n<i>Fetching the best available quality…</i>"
    )


def favorites_card(items: list[dict]) -> str:
    if not items:
        return f"{E('favorite')} <b>No favourites yet</b>\n<blockquote>Save a track with /fav while it plays.</blockquote>"
    rows = "".join(
        f"<tr><td><b>{index + 1}</b></td><td>{esc(truncate(str(item.get('title', '?')), 44))}</td>"
        f"<td>{fmt_duration(int(item.get('duration') or 0))}</td></tr>"
        for index, item in enumerate(items[:10])
    )
    return f"<h2>{E('favorite')} {small_caps('favourites')}</h2><table>{rows}</table>"


def history_card(items: list[dict]) -> str:
    if not items:
        return f"{E('clock')} <b>Nothing played yet</b>\n<blockquote>Your history will appear here.</blockquote>"
    rows = "".join(
        f"<tr><td><b>{index + 1}</b></td><td>{esc(truncate(str(item.get('title', '?')), 44))}</td></tr>"
        for index, item in enumerate(items[:10])
    )
    return f"<h2>{E('clock')} {small_caps('recently played')}</h2><table>{rows}</table>"


# ── settings / stats / lyrics ───────────────────────────────────────────────
def settings_card(cfg: dict, chat_title: str = "") -> str:
    volume = int(cfg.get("volume", settings.default_volume))
    loop = str(cfg.get("loop", "off")).title()
    autoplay = "On" if cfg.get("autoplay", True) else "Off"
    always = "On" if cfg.get("always_on", False) else "Off"
    return f"""<h2>{E('settings')} {small_caps('settings')}</h2>
<table>
<tr><td>{E('volume')} Volume</td><td><b>{volume}%</b></td></tr>
<tr><td>{E('loop')} Loop</td><td><b>{loop}</b></td></tr>
<tr><td>{E('spark')} Autoplay</td><td><b>{autoplay}</b></td></tr>
<tr><td>{E('clock')} 24/7 mode</td><td><b>{always}</b></td></tr>
</table>
<footer>{esc(truncate(chat_title, 40) or 'this chat')} {BULLET} changes apply instantly</footer>"""


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
    return f"""<h2>{E('stats')} {small_caps('statistics')}</h2>
<table>
<tr><td>{E('clock')} Uptime</td><td><b>{human_time(uptime)}</b></td></tr>
<tr><td>{E('chat')} Known chats</td><td><b>{chats}</b></td></tr>
<tr><td>{E('live')} Active players</td><td><b>{active}</b></td></tr>
<tr><td>{E('note')} Tracks played</td><td><b>{tracks}</b></td></tr>
<tr><td>{E('download')} Downloads</td><td><b>{downloads}</b></td></tr>
<tr><td>{E('cloud')} Cache</td><td><b>{human_size(cache_bytes)}</b></td></tr>
<tr><td>{E('code')} Storage</td><td><b>{backend}</b></td></tr>
</table>
<footer>{E('bolt')} VYRON v{version} {BULLET} python-telegram core</footer>"""


def lyrics_card(track: Track, lyrics: LyricsResult | None) -> str:
    if not lyrics or not (lyrics.plain or lyrics.synced):
        return (
            f"{E('lyrics')} <b>No lyrics found</b>\n"
            f"<blockquote>{esc(truncate(track.title, 60))}</blockquote>"
        )
    body = esc(lyrics.as_text(3000))
    synced = "synced" if lyrics.has_sync else "plain"
    return (
        f"{E('lyrics')} <b>{esc(truncate(lyrics.title, 52))}</b>\n"
        f"<i>{esc(truncate(lyrics.artist, 40))}</i>  {BULLET}  {synced}\n\n"
        f"<blockquote expandable>{body}</blockquote>"
    )


def about_card() -> str:
    return f"""<h2>{E('brand')} {BRAND} {DASH} about</h2>
<p>{SPARK} A modern Telegram voice-chat music bot: rich cards, premium emoji, yt-dlp powered search, MP3/MP4 downloads and a persistent queue.</p>
<table>
<tr><td>{E('code')} Stack</td><td>Kurigram + PyTgCalls</td></tr>
<tr><td>{E('bolt')} API</td><td>Bot API rich messages</td></tr>
<tr><td>{E('cloud')} Deploy</td><td>Docker · Render · Koyeb · VPS</td></tr>
</table>
<footer>{E('star')} <a href="{esc(settings.git_repo)}">{esc(settings.git_repo)}</a></footer>"""


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


__all__ = [
    "about_card",
    "download_card",
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
]
