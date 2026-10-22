# ---------------------------------------------------------------------------
#  VYRON — rich building blocks
#
#  Thin, themed wrapper around `richgram` (Bot API 10.3 rich messages) —
#  tables, collapsible sections, dividers, lists and *coloured* in-message
#  buttons — with a graceful local fallback when richgram is unavailable.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
from typing import Iterable, Sequence

from vyron.ui.theme import E, SPARK

logger = logging.getLogger(__name__)

try:  # pragma: no cover - depends on the installed build
    import richgram as _rg
    from richgram import add_html_hook as _add_html_hook

    RICHGRAM = True
except Exception:  # pragma: no cover
    _rg = None  # type: ignore[assignment]
    RICHGRAM = False


# ── brand tokens ────────────────────────────────────────────────────────────
STYLES = ("primary", "success", "danger", "link")


# ── primitives ──────────────────────────────────────────────────────────────
def esc(value) -> str:
    """HTML-escape untrusted text."""
    if _rg is not None:
        return _rg.rich_esc(value)
    import html as _html

    return "" if value is None else _html.escape(str(value), quote=False)


def heading(text: str, level: int = 2) -> str:
    level = max(1, min(6, int(level)))
    return f"<h{level}>{text}</h{level}>"


def note(text: str, *, expandable: bool = False) -> str:
    attr = " expandable" if expandable else ""
    return f"<blockquote{attr}>{text}</blockquote>"


def quote(text: str) -> str:
    return f"<aside>{text}</aside>"


def divider() -> str:
    return "<hr/>"


def footer(text: str) -> str:
    return f"<footer>{text}</footer>"


def spacer() -> str:
    return "<br/>"


def bullets(items: Iterable[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{item}</li>" for item in items if item is not None)
    return f"<{tag}>{body}</{tag}>"


def table(headers: Sequence[str] | None, rows: Iterable[Sequence[str]], *, border: int = 1) -> str:
    parts = [f'<table border="{int(border)}">']
    if headers:
        parts.append("<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>")
    for row in rows:
        parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    parts.append("</table>")
    return "".join(parts)


def kv(pairs: Iterable[tuple[str, str]], *, border: int = 1) -> str:
    return table(None, [(f"<b>{key}</b>", value) for key, value in pairs if value is not None], border=border)


def details(summary: str, body: str, *, open: bool = False) -> str:
    attr = " open" if open else ""
    return f"<details{attr}><summary>{summary}</summary>{body}</details>"


def image(src: str | None) -> str:
    if not src:
        return ""
    return f'<img src="{esc(src)}" />'


def code(value) -> str:
    return f"<code>{esc(value)}</code>"


def bold(text: str) -> str:
    return f"<b>{text}</b>"


def italic(text: str) -> str:
    return f"<i>{text}</i>"


def think() -> str:
    """Animated 'thinking' indicator (Bot API rich messages)."""
    return "<tg-thinking></tg-thinking>"


# ── buttons (in-message, coloured) ─────────────────────────────────────────
def btn(text: str, *, data: str | None = None, url: str | None = None, style: str | None = None) -> str:
    """A coloured rich button.

    style: ``primary`` (blue) · ``success`` (green) · ``danger`` (red) ·
    ``link`` · ``None`` (neutral grey).
    """
    if style not in STYLES:
        style = None
    attrs = []
    if style:
        attrs.append(f' style="{style}"')
    attrs = "".join(attrs)
    if data:
        return f'<tg-button type="callback_data"{attrs} data="{esc(data)}">{text}</tg-button>'
    if url:
        return f'<tg-button type="url"{attrs} url="{esc(url)}">{text}</tg-button>'
    return f"<tg-button{attrs}>{text}</tg-button>"


def row(*buttons: str, align: str | None = None) -> str:
    attrs = f' align="{align}"' if align in {"left", "center", "right"} else ""
    return f"<tg-button-row{attrs}>{''.join(buttons)}</tg-button-row>"


def grid(buttons: Sequence[str], columns: int = 2) -> str:
    """Lay buttons out in rows of *columns* (pads the last row)."""
    width = max(1, int(columns))
    rows: list[str] = []
    for index in range(0, len(buttons), width):
        rows.append(row(*buttons[index : index + width]))
    return "".join(rows)


# ── composed pieces ────────────────────────────────────────────────────────
def hero(icon: str, title: str, subtitle: str | None = None, *, level: int = 2) -> str:
    head = heading(f"{E(icon)} {title}", level)
    return head + (note(subtitle) if subtitle else "")


def badge(text: str, glyph: str = "spark") -> str:
    return f"{E(glyph)} {text}"


def stat_pairs(pairs: Sequence[tuple[str, str, str]]) -> str:
    """``(glyph, label, value)`` → a tidy key/value table."""
    return kv([(f"{E(glyph)} {label}", f"<b>{value}</b>") for glyph, label, value in pairs])


def powered_line(version: str = "") -> str:
    tail = f" · v{version}" if version else ""
    return footer(f"{SPARK} VYRON{tail} · built on Kurigram + PyTgCalls · UI by richgram")


# ── premium-emoji hook ─────────────────────────────────────────────────────
def install_hooks() -> None:
    """Normalise custom-emoji tags for every richgram send."""
    if not RICHGRAM:
        return

    def _emoji_hook(markup: str) -> str:
        # `<emoji id="123">🔥</emoji>` (Bot API spelling) → richgram/Kurigram spelling
        import re

        return re.sub(
            r'<emoji\s+id="([0-9]+)"\s*>(.*?)</emoji>',
            r'<tg-emoji emoji-id="\1">\2</tg-emoji>',
            markup,
            flags=re.I | re.S,
        )

    try:
        _add_html_hook(_emoji_hook)
    except Exception as exc:  # pragma: no cover
        logger.debug("could not install richgram hook: %s", exc)


install_hooks()


__all__ = [
    "RICHGRAM",
    "STYLES",
    "badge",
    "bold",
    "btn",
    "bullets",
    "code",
    "powered_line",
    "details",
    "divider",
    "esc",
    "footer",
    "grid",
    "heading",
    "hero",
    "image",
    "install_hooks",
    "italic",
    "kv",
    "note",
    "quote",
    "row",
    "spacer",
    "stat_pairs",
    "table",
    "think",
]
