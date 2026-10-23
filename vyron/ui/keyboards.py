# ---------------------------------------------------------------------------
#  VYRON — inline keyboards
#  Every callback lives under the ``v:`` namespace and is routed by one
#  handler (vyron/modules/callbacks.py).
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram.types import InlineKeyboardButton as B
from pyrogram.types import InlineKeyboardMarkup as KM
from pyrogram.types import WebAppInfo

from vyron.config import settings
from vyron.core.queue import ChatState
from vyron.ui.theme import raw_glyph as G


def _btn(text: str, data: str) -> B:
    return B(text, callback_data=data)


def _url(text: str, url: str) -> B:
    return B(text, url=url)


def app_url() -> str:
    """The Mini App entry point, normalised, or "" when it is not configured."""
    raw = (settings.webapp_url or "").strip()
    if not raw or not settings.webapp:
        return ""
    from vyron.ui.cards import _app_root

    return _app_root(raw)


def app_button(text: str = "▶️ Player") -> B | None:
    """A Mini App button — Telegram opens this *inside* the client.

    A plain https:// link would be handed to the browser, which is exactly what
    we do not want. ``web_app`` buttons are only legal in private chats, so the
    caller decides: DM → this button, group → :func:`dm_hint_markup`.
    """
    url = app_url()
    if not url:
        return None
    return B(text, web_app=WebAppInfo(url=url))


def app_markup(*, with_close: bool = False) -> KM | None:
    button = app_button()
    if button is None:
        return None
    rows = [[button, _btn(f"{G('queue')} Queue", "v:queue:0")]]
    if with_close:
        rows.append([_btn(f"{G('back')} Close", "v:close")])
    return KM(rows)


def dm_markup() -> KM | None:
    """Group fallback: point at the private chat (t.me opens in Telegram)."""
    username = (settings.bot_username or "").lstrip("@")
    if not username:
        return None
    return KM([[B("👤 Open in DM", url=f"https://t.me/{username}"), _btn("Queue", "v:queue:0")]])


def now_playing(state: ChatState, *, is_fav: bool = False) -> KM:
    play_pause = (
        _btn(f"{G('resume')} Resume", "v:resume")
        if state.paused
        else _btn(f"{G('pause')} Pause", "v:pause")
    )
    rows = [
        [play_pause, _btn(f"{G('skip')} Skip", "v:skip"), _btn(f"{G('stop')} Stop", "v:stop")],
        [
            _btn(f"{G('volume')} −", "v:vol:-10"),
            _btn(f"{state.volume}%", "v:vol:show"),
            _btn(f"{G('volume')} +", "v:vol:10"),
        ],
        [
            _btn(f"{G('loop')} {state.loop.label}", "v:loop"),
            _btn(f"{G('shuffle')} Shuffle", "v:shuffle"),
            _btn(f"{G('queue')} Queue", "v:queue:0"),
        ],
        [
            _btn(f"{G('favorite')} {'Saved' if is_fav else 'Save'}", "v:fav"),
            _btn(f"{G('lyrics')} Lyrics", "v:lyrics"),
            _btn(f"{G('back')} Close", "v:close"),
        ],
    ]
    return KM(rows)


def queue(state: ChatState, page: int, pages: int) -> KM:
    nav: list[B] = []
    if page > 0:
        nav.append(_btn("‹ Prev", f"v:queue:{page - 1}"))
    nav.append(_btn(f"{page + 1}/{max(1, pages)}", "v:noop"))
    if page + 1 < pages:
        nav.append(_btn("Next ›", f"v:queue:{page + 1}"))
    rows = [
        [_btn(f"{G('shuffle')} Shuffle", "v:shuffle"), _btn(f"{G('stop')} Clear", "v:clearqueue")],
        nav,
        [_btn(f"{G('now')} Now playing", "v:np"), _btn(f"{G('back')} Close", "v:close")],
    ]
    return KM(rows)


def _duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "live"
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{rest:02d}" if hours else f"{minutes}:{rest:02d}"


def search_results(tracks) -> KM:
    """Classic-lane keyboard: numbered, titled, with the length on the button."""
    rows = [
        [
            _btn(
                f"{index + 1} · {_duration(track.duration)} · {track.title[:30]}",
                f"v:pick:{index}",
            )
        ]
        for index, track in enumerate(tracks[:5])
    ]
    rows.append([_btn(f"{G('close')} Cancel", "v:close")])
    return KM(rows)


def results_page(tracks) -> KM:
    rows = [
        [
            _btn(
                f"⬇ {index + 1} · {_duration(track.duration)} · {track.title[:28]}",
                f"v:dl:{index}",
            )
        ]
        for index, track in enumerate(tracks[:5])
    ]
    rows.append([_btn(f"{G('close')} Close", "v:close")])
    return KM(rows)


def settings_panel(cfg: dict) -> KM:
    loop = str(cfg.get("loop", "off")).title()
    autoplay = "On" if cfg.get("autoplay", True) else "Off"
    always = "On" if cfg.get("always_on", False) else "Off"
    poster = "On" if cfg.get("poster", True) else "Off"
    return KM(
        [
            [
                _btn(f"{G('loop')} Loop: {loop}", "v:set:loop"),
                _btn(f"{G('spark')} Autoplay: {autoplay}", "v:set:autoplay"),
            ],
            [
                _btn(f"{G('clock')} 24/7: {always}", "v:set:always"),
                _btn(f"{G('image')} Poster: {poster}", "v:set:poster"),
            ],
            [_btn(f"{G('back')} Close", "v:close")],
        ]
    )


def start_panel(player: bool = False) -> KM:
    """``player=True`` adds the Mini App button — private chats only."""
    rows: list[list[B]] = []
    if player:
        button = app_button()
        if button is not None:
            rows.append([button])
    rows += [
        [
            _url(f"{G('rocket')} Add to group", f"https://t.me/{settings.bot_username}?startgroup=true"),
            _btn(f"{G('queue')} Commands", "v:help:main"),
        ],
        [
            _url(f"{G('chat')} Support", settings.support_chat),
            _url(f"{G('star')} Updates", settings.updates_channel),
        ],
        [_btn(f"{G('info')} About VYRON", "v:about")],
    ]
    return KM(rows)


def help_nav(section: str = "main") -> KM:
    tabs = ["main", "playback", "queue", "tools", "social", "power"]
    labels = {
        "main": "Basics",
        "playback": "Playback",
        "queue": "Queue",
        "tools": "Tools",
        "social": "Groups",
        "power": "Owner",
    }
    row = [
        _btn(("• " if tab == section else "") + labels[tab], f"v:help:{tab}")
        for tab in tabs
    ]
    return KM([row, [_btn(f"{G('back')} Close", "v:close")]])


def back_close(back_data: str = "v:np") -> KM:
    return KM([[_btn(f"{G('back')} Back", back_data), _btn(f"{G('close')} Close", "v:close")]])


def download_choice(index: int = 0) -> KM:
    return KM(
        [
            [
                _btn(f"{G('song')} Audio (MP3)", f"v:get:audio:{index}"),
                _btn(f"{G('video')} Video (MP4)", f"v:get:video:{index}"),
            ],
            [_btn(f"{G('close')} Cancel", "v:close")],
        ]
    )


def admin_panel() -> KM:
    return KM(
        [
            [
                _btn(f"{G('stats')} Stats", "v:admin:stats"),
                _btn(f"{G('live')} Active", "v:admin:active"),
            ],
            [_btn(f"{G('close')} Close", "v:close")],
        ]
    )


__all__ = [
    "app_button",
    "app_markup",
    "app_url",
    "dm_markup",
    "admin_panel",
    "back_close",
    "download_choice",
    "help_nav",
    "now_playing",
    "queue",
    "results_page",
    "search_results",
    "settings_panel",
    "start_panel",
]
