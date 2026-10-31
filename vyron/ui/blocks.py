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
    # Block-level elements end with a newline: every card is a concatenation of
    # these pieces, and the plain-text fallback has no HTML to break lines.
    attr = " expandable" if expandable else ""
    return f"<blockquote{attr}>{text}</blockquote>\n"


def quote(text: str) -> str:
    return f"<aside>{text}</aside>\n"


def divider() -> str:
    return "<hr/>\n"


def footer(text: str) -> str:
    return f"<footer>{text}</footer>\n"


def spacer() -> str:
    return "<br/>"


def bullets(items: Iterable[str], *, ordered: bool = False) -> str:
    tag = "ol" if ordered else "ul"
    body = "".join(f"<li>{item}</li>" for item in items if item is not None)
    return f"<{tag}>{body}</{tag}>\n"


def table(headers: Sequence[str] | None, rows: Iterable[Sequence[str]], *, border: int = 1) -> str:
    parts = [f'<table border="{int(border)}">']
    if headers:
        parts.append("<tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>")
    for row in rows:
        parts.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>")
    parts.append("</table>")
    return "".join(parts) + "\n"


def kv(pairs: Iterable[tuple[str, str]], *, border: int = 1) -> str:
    return table(None, [(f"<b>{key}</b>", value) for key, value in pairs if value is not None], border=border)


def details(summary: str, body: str, *, open: bool = False) -> str:
    attr = " open" if open else ""
    return f"<details{attr}><summary>{summary}</summary>{body}</details>\n"


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
    """``(glyph, label, value)`` → the aligned field block.

    Every status screen in the bot is a list of these, so they are one
    primitive: `◈ ⏱ ᴜᴘᴛɪᴍᴇ: 3d 8h` — not a table, which on a narrow phone
    wraps a long value into a second row of a phantom column.
    """
    return fields(pairs)


def powered_line(version: str = "") -> str:
    tail = f" · v{version}" if version else ""
    return footer(f"{SPARK} VYRON{tail}")


# ── design kit ─────────────────────────────────────────────────────────────
#  Every card in the bot is built from these five pieces, so a settings screen
#  and a queue screen feel like the same product:
#
#      head()      one line: glyph, SMALL-CAPS title, optional right-side meta
#      context()   a quoted sentence saying what this card is about
#      pill()      a small status token (live · 3 queued · owner)
#      section()   a labelled block, separated by a hairline when repeated
#      actions()   the button rows, always after a divider
#
#  They are deliberately thin — richgram does the rendering, this only keeps
#  the rhythm identical everywhere.

PILL_TONES = {
    "ok": "🟢",
    "live": "🔴",
    "idle": "⚪",
    "warn": "🟡",
    "off": "⚫",
    "info": "🔵",
    "owner": "👑",
}


#: The hairline every masthead and section break is drawn with. A single
#: character repeated, so it renders identically on every client — no images,
#: no alignment surprises, and it survives being copied into a plain chat.
RULE_CHAR = "━"
RULE_WIDTH = 18
FIELD_MARK = "◈"
SECTION_MARK = "✦"


def rule(width: int = RULE_WIDTH, char: str = RULE_CHAR) -> str:
    return char * max(3, int(width))


def rich_lane() -> bool:
    """Is the rich renderer available *and* on for this process?

    Cards ask this at build time so the same source can produce either lane:
    a real rich message when the server supports it, or the classic HTML
    equivalent that `rich.to_html` derives from it.
    """
    from vyron.ui import rich as _rich

    return bool(_rich.RICH_AVAILABLE and _rich.rich_enabled())


def banner(title: str, *, glyph: str = "brand", meta: str = "", width: int = RULE_WIDTH) -> str:
    """The top of a card: a heading, then a hairline.

        <h2>🎧 ᴠʏʀᴏɴ · ᴘʟᴀʏᴇʀ</h2>
        <hr/>

    This is the one element that makes every screen recognisably the same
    product, so it is a primitive rather than something each card retypes.

    In the rich lane it is a real heading and a real divider — that is what
    turns 90-odd cards from "bold text with a line of ━" into rich messages.
    Without rich support the same card falls back to the character rule, so
    nothing has to know which lane it is in.
    """
    from vyron.ui.theme import small_caps

    plain = f"{E(glyph)} {small_caps(title)}"
    if meta:
        plain += f"  {meta}"
    if rich_lane():
        # A heading is already bold; nesting <b> inside it makes Telegram's
        # classic fallback emit "<b><b>…</b></b>".
        return f"<h2>{plain}</h2>\n<hr/>\n"
    # Classic lane: a quoted line. Telegram draws the quote bar for us, which
    # reads as a header on a phone — and unlike a line of "━━━━━━" it is not a
    # wall of characters sitting between every section of every card.
    return f"<blockquote>{E(glyph)} <b>{small_caps(title)}</b>{('  ' + meta) if meta else ''}</blockquote>\n"


def fields(rows: Sequence[tuple[str, str, str]]) -> str:
    """``◈ 🟢 ꜱᴛᴀᴛᴜꜱ: Online`` — one line per fact, aligned by the mark.

    Reads better than a table on a phone: no column widths to guess, no
    wrapping surprises, and the glyph does the scanning for you.
    """
    from vyron.ui.theme import small_caps

    lines: list[str] = []
    for glyph, label, value in rows:
        prefix = f"{E(glyph)} " if glyph else ""
        lines.append(f"{FIELD_MARK} {prefix}<b>{small_caps(label)}</b>: {value}")
    return "\n".join(lines) + "\n" if lines else ""


def items(rows: Sequence[tuple[str, str, str]]) -> str:
    """``◈ 📥 ꜱᴀᴠᴇ — what it does`` — the feature list under a section title.

    In the rich lane this is a real ``<ul>``: Telegram draws the bullets, hangs
    the second line, and the block reads as a list instead of as prose with
    marks in front of it. The classic lane keeps the ``◈`` line form, which is
    what ``to_html`` would turn a list into anyway.
    """
    from vyron.ui.theme import small_caps

    lines: list[str] = []
    for glyph, name, text in rows:
        prefix = f"{E(glyph)} " if glyph else ""
        label = f"<b>{small_caps(name)}</b>"
        lines.append(f"{prefix}{label} — {text}" if text else f"{prefix}{label}")
    if not lines:
        return ""
    if rich_lane():
        return "<ul>" + "".join(f"<li>{line}</li>" for line in lines) + "</ul>\n"
    return "\n".join(f"{FIELD_MARK} {line}" for line in lines) + "\n"


def section_title(label: str, *, glyph: str | None = None) -> str:
    """``✦ ᴡʜᴀᴛ ɪ ᴄᴀɴ ᴅᴏ ✦`` — a centred-feeling break inside a card."""
    from vyron.ui.theme import small_caps

    prefix = f"{E(glyph)} " if glyph else ""
    if rich_lane():
        return f"\n<h3>{SECTION_MARK} {prefix}{small_caps(label)}</h3>\n"
    return f"\n{SECTION_MARK} <b>{prefix}{small_caps(label)}</b>\n"


def head(title: str, *, glyph: str = "spark", meta: str = "", level: int = 2) -> str:
    """Card header: glyph + small-caps title, with an optional trailing meta."""
    from vyron.ui.theme import small_caps

    line = f"{E(glyph)} {small_caps(title)}"
    if meta:
        line += f"  {meta}"
    return heading(line, level)


def context(text: str) -> str:
    return note(text)


def pill(text: str, tone: str = "info") -> str:
    """A status token. Stays plain so it can live inside a heading."""
    dot = PILL_TONES.get(tone, PILL_TONES["info"])
    return f"{dot} {text}"


def section(label: str, body: str, *, glyph: str | None = None, rule: bool = True) -> str:
    """A labelled block: hairline, label, body.

    The label is a heading in the rich lane so it is visibly a section of the
    card rather than another bold line inside it.
    """
    from vyron.ui.theme import small_caps

    prefix = f"{E(glyph)} " if glyph else ""
    if rich_lane():
        label = heading(f"{prefix}{small_caps(label)}", 4)
    else:
        label = f"<b>{prefix}{small_caps(label)}</b>"
    return (divider() if rule else "") + label + body


def meter(value: float, total: float, *, width: int = 12, full: str = "▰", empty: str = "▱") -> str:
    total = max(1e-9, float(total))
    filled = int(max(0.0, min(1.0, value / total)) * width)
    return full * filled + empty * (width - filled)


def actions(*rows: str) -> str:
    """The action block: a hairline, then the buttons in the order given.

    The hairline only exists in the rich lane. In the classic lane the buttons
    are stripped and a real ``reply_markup`` keyboard is attached instead, so
    drawing a divider there left a bare line of dashes with nothing under it —
    the most "the design gave up here" part of the old cards.
    """
    body = "".join(row_ for row_ in rows if row_)
    if not body:
        return ""
    return (divider() + body) if rich_lane() else body


def meta_line(*bits: str) -> str:
    """`3:45 · 2.4M plays · youtube` — skips empty parts, keeps one separator."""
    return " · ".join(bit for bit in bits if bit)


def empty_state(glyph: str, title: str, hint: str) -> str:
    """The one screen that must never look broken: nothing here yet, and why."""
    if rich_lane():
        return heading(f"{E(glyph)} {title}", 3) + note(hint)
    return f"{E(glyph)} <b>{title}</b>\n" + note(hint)


# ── Premium polish helpers (beautiful cards) ───────────────────────────────
def soft_header(icon: str, title: str, subtitle: str | None = None) -> str:
    """Beautiful soft header used on every major card.

    The title is lower-cased before it is small-capped, so a caller may pass
    ``"Now Streaming"`` or ``"now streaming"`` and get the same heading. The
    mixed-case spelling used to render as ``Nᴏᴡ Sᴛʀᴇᴀᴍɪɴɢ`` next to cards
    that read ``ꜱᴇᴀʀᴄʜɪɴɢ``/``ɴᴏᴡ ᴘʟᴀʏɪɴɢ`` — one heading style per app.
    """
    from vyron.ui.theme import small_caps, E
    head = f"<h2>{E(icon)}  {small_caps(str(title).lower())}</h2>\n"
    if subtitle:
        head += f"<blockquote>{subtitle}</blockquote>\n"
    return head


def pretty_table(rows: list[tuple[str, str]], *, bordered: bool = True, striped: bool = True) -> str:
    """Clean key-value table with optional border + stripe."""
    attrs = []
    if bordered:
        attrs.append("bordered")
    if striped:
        attrs.append("striped")
    attr = " ".join(attrs)
    body = "".join(f"<tr><td>{k}</td><td><b>{v}</b></td></tr>" for k, v in rows)
    return f"<table {attr}>{body}</table>\n"


def status_chip(text: str, tone: str = "live") -> str:
    """LIVE / PAUSED / RADIO chip with colour."""
    colors = {
        "live": "🔴",
        "paused": "🟡",
        "ok": "🟢",
        "warn": "🟠",
        "off": "⚫",
        "info": "🔵",
    }
    return f"{colors.get(tone, '⚪')} <b>{text}</b>"


def soft_footer(*parts: str) -> str:
    """Clean footer with · separators."""
    clean = [p for p in parts if p]
    return f"<footer>{' · '.join(clean)}</footer>\n"


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
        from richgram import add_html_hook as _add_html_hook
    except Exception as exc:  # pragma: no cover - optional package
        logger.debug("richgram hook unavailable: %s", exc)
        return
    try:
        _add_html_hook(_emoji_hook)
    except Exception as exc:  # pragma: no cover
        logger.debug("could not install richgram hook: %s", exc)


install_hooks()


__all__ = [
    "FIELD_MARK",
    "RICHGRAM",
    "RULE_CHAR",
    "RULE_WIDTH",
    "SECTION_MARK",
    "banner",
    "fields",
    "items",
    "rule",
    "section_title",
    "STYLES",
    "actions",
    "badge",
    "context",
    "empty_state",
    "head",
    "meta_line",
    "meter",
    "pill",
    "section",
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
    "soft_header",
    "pretty_table",
    "status_chip",
    "soft_footer",
]
