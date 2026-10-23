# ---------------------------------------------------------------------------
#  VYRON — inline keyboards
#  Every callback lives under the ``v:`` namespace and is routed by one
#  handler (vyron/modules/callbacks.py).
#
#  Layout rules (kept deliberately boring so the bot feels calm):
#    * three buttons per row at most — Telegram squeezes anything wider
#    * the primary action always sits top-left
#    * destructive actions are last, never next to the primary one
#    * a status value is its own button only when tapping it does something
# ---------------------------------------------------------------------------
from __future__ import annotations

from pyrogram.types import InlineKeyboardButton as B
from pyrogram.types import InlineKeyboardMarkup as KM
from pyrogram.types import WebAppInfo

from vyron.config import settings
from vyron.core.queue import ChatState
from vyron.ui.theme import small_caps
from vyron.ui.theme import raw_glyph as G


def _btn(text: str, data: str) -> B:
    return B(text, callback_data=data)


def _url(text: str, url: str) -> B:
    return B(text, url=url)


def _label(*parts: str) -> str:
    """Join button fragments with a hair space thin enough to survive."""
    return " ".join(part for part in parts if part)


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
    caller decides: DM → this button, group → :func:`dm_markup`.
    """
    url = app_url()
    if not url:
        return None
    return B(text, web_app=WebAppInfo(url=url))


def app_markup(*, with_close: bool = False) -> KM | None:
    button = app_button()
    if button is None:
        return None
    rows = [[button, _btn(_label(G("queue"), "Queue"), "v:queue:0")]]
    if with_close:
        rows.append([_btn(_label(G("back"), "Close"), "v:close")])
    return KM(rows)


def dm_markup() -> KM | None:
    """Group fallback: point at the private chat (t.me opens in Telegram)."""
    username = (settings.bot_username or "").lstrip("@")
    if not username:
        return None
    return KM(
        [
            [
                B("👤 Open in DM", url=f"https://t.me/{username}"),
                _btn(_label(G("queue"), "Queue"), "v:queue:0"),
            ]
        ]
    )


def now_playing(state: ChatState, *, is_fav: bool = False) -> KM:
    """Four rows, one idea each: transport, volume, modes, extras."""
    play_pause = (
        _btn(_label(G("resume"), "Resume"), "v:resume")
        if state.paused
        else _btn(_label(G("pause"), "Pause"), "v:pause")
    )
    loop_label = str(state.loop.label).title()
    rows = [
        [
            play_pause,
            _btn(_label(G("skip"), "Skip"), "v:skip"),
            _btn(_label(G("stop"), "Stop"), "v:stop"),
        ],
        [
            _btn(f"{G('volume')} −10", "v:vol:-10"),
            _btn(f"{G('volume')} {int(state.volume)}%", "v:vol:show"),
            _btn(f"{G('volume')} +10", "v:vol:10"),
        ],
        [
            _btn(_label(G("loop"), loop_label), "v:loop"),
            _btn(_label(G("shuffle"), "Shuffle"), "v:shuffle"),
            _btn(_label(G("queue"), "Queue"), "v:queue:0"),
        ],
        [
            _btn(_label(G("favorite"), "Saved" if is_fav else "Save"), "v:fav"),
            _btn(_label(G("lyrics"), "Lyrics"), "v:lyrics"),
            _btn(_label(G("close"), "Close"), "v:close"),
        ],
    ]
    return KM(rows)


def queue(state: ChatState, page: int, pages: int) -> KM:
    """Shuffle next to the page arrows, clearing kept away from the arrows."""
    pages = max(1, pages)
    nav: list[B] = []
    if page > 0:
        nav.append(_btn("‹  Prev", f"v:queue:{page - 1}"))
    nav.append(_btn(f"· {page + 1} / {pages} ·", "v:noop"))
    if page + 1 < pages:
        nav.append(_btn("Next  ›", f"v:queue:{page + 1}"))
    rows = [
        nav,
        [
            _btn(_label(G("shuffle"), "Shuffle"), "v:shuffle"),
            _btn(_label(G("now"), "Now playing"), "v:np"),
            _btn(_label(G("stop"), "Clear"), "v:clearqueue"),
        ],
        [_btn(_label(G("back"), "Close"), "v:close")],
    ]
    return KM(rows)


def _duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    if seconds <= 0:
        return "live"
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{rest:02d}" if hours else f"{minutes}:{rest:02d}"


def _track_row(index: int, track, prefix: str, action: str) -> list[B]:
    title = str(getattr(track, "title", "") or "unknown")[:32]
    return [
        _btn(
            f"{prefix} {index + 1} · {title} · {_duration(getattr(track, 'duration', 0))}",
            f"{action}:{index}",
        )
    ]


def search_results(tracks) -> KM:
    """Classic-lane keyboard: numbered, titled, with the length on the button."""
    rows = [_track_row(index, track, G("play"), "v:pick") for index, track in enumerate(tracks[:5])]
    rows.append([_btn(_label(G("close"), "Cancel"), "v:close")])
    return KM(rows)


def results_page(tracks) -> KM:
    rows = [_track_row(index, track, G("download"), "v:dl") for index, track in enumerate(tracks[:5])]
    rows.append([_btn(_label(G("close"), "Close"), "v:close")])
    return KM(rows)


def settings_panel(cfg: dict) -> KM:
    loop = str(cfg.get("loop", "off")).title()
    autoplay = "On" if cfg.get("autoplay", True) else "Off"
    always = "On" if cfg.get("always_on", False) else "Off"
    poster = "On" if cfg.get("poster", True) else "Off"
    return KM(
        [
            [
                _btn(_label(G("loop"), f"Loop · {loop}"), "v:set:loop"),
                _btn(_label(G("spark"), f"Autoplay · {autoplay}"), "v:set:autoplay"),
            ],
            [
                _btn(_label(G("clock"), f"24/7 · {always}"), "v:set:always"),
                _btn(_label(G("image"), f"Poster · {poster}"), "v:set:poster"),
            ],
            [_btn(_label(G("back"), "Close"), "v:close")],
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
            _url(
                _label(G("rocket"), "Add to group"),
                f"https://t.me/{settings.bot_username}?startgroup=true",
            ),
            _btn(_label(G("tools"), "Commands"), "v:help:main"),
        ],
        [
            _url(_label(G("chat"), "Support"), settings.support_chat),
            _url(_label(G("star"), "Updates"), settings.updates_channel),
        ],
        [_btn(_label(G("info"), "About VYRON"), "v:about")],
    ]
    return KM(rows)


# Tab order and glyphs for /help — also used by the card itself.
HELP_TABS: tuple[tuple[str, str, str], ...] = (
    ("main", "home", "Basics"),
    ("playback", "play", "Playback"),
    ("queue", "queue", "Queue"),
    ("tools", "tools", "Tools"),
    ("social", "users", "Groups"),
    ("power", "crown", "Owner"),
)
HELP_LABELS = {key: label for key, _, label in HELP_TABS}


def help_nav(section: str = "main") -> KM:
    """Two rows of three tabs; the active one is marked, not hidden."""
    buttons = [
        _btn(_label(G(glyph), ("• " if key == section else "") + label), f"v:help:{key}")
        for key, glyph, label in HELP_TABS
    ]
    return KM([buttons[:3], buttons[3:], [_btn(_label(G("back"), "Close"), "v:close")]])


def back_close(back_data: str = "v:np") -> KM:
    return KM(
        [
            [
                _btn(_label(G("back"), "Back"), back_data),
                _btn(_label(G("close"), "Close"), "v:close"),
            ]
        ]
    )


def download_choice(index: int = 0) -> KM:
    return KM(
        [
            [
                _btn(_label(G("song"), "Audio · MP3"), f"v:get:audio:{index}"),
                _btn(_label(G("video"), "Video · MP4"), f"v:get:video:{index}"),
            ],
            [_btn(_label(G("close"), "Cancel"), "v:close")],
        ]
    )


def admin_panel() -> KM:
    return KM(
        [
            [
                _btn(_label(G("stats"), small_caps("stats")), "v:admin:stats"),
                _btn(_label(G("live"), small_caps("active")), "v:admin:active"),
            ],
            [_btn(_label(G("close"), "Close"), "v:close")],
        ]
    )


__all__ = [
    "HELP_LABELS",
    "HELP_TABS",
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
