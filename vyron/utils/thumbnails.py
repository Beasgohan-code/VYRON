# ---------------------------------------------------------------------------
#  VYRON — generated "now playing" artwork
#
#  A 1280×720 poster rendered with Pillow: the cover art with a vinyl disc
#  slipping out from behind it, the title and artist in Inter, duration and
#  requester chips, and a waveform that fills as the track plays. The accent
#  colour is pulled from the artwork itself, so every track looks like it was
#  designed for that song rather than dropped into a template.
#
#  Pillow stays optional: `render` returns None when it is missing and every
#  caller falls back to the text card.
# ---------------------------------------------------------------------------
from __future__ import annotations

import colorsys
import io
import logging
import math
import random
from pathlib import Path
from typing import Any

from vyron.core.queue import ChatState, Track
from vyron.ui.progress import fmt_duration
from vyron.utils.net import fetch_bytes

logger = logging.getLogger(__name__)

try:  # pragma: no cover - optional dependency
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    PIL_AVAILABLE = True
except Exception:  # pragma: no cover
    PIL_AVAILABLE = False
    Image = ImageDraw = ImageFilter = ImageFont = None  # type: ignore[assignment]

W, H = 1280, 720

# Brand fallbacks when the cover has no usable colour.
ACCENT = (139, 92, 246)
ACCENT_2 = (45, 232, 200)
TEXT = (247, 247, 250)
MUTED = (166, 166, 182)
CHIP_TEXT = (238, 238, 246)

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# name → (file, covers) — `covers` lets us pick a font that can actually draw
# the title (Inter is latin-only; Noto handles Devanagari and Malayalam).
_FAMILIES: dict[str, dict[int, str]] = {
    "inter": {
        400: "Inter-400.ttf",
        500: "Inter-500.ttf",
        600: "Inter-600.ttf",
        700: "Inter-700.ttf",
        800: "Inter-800.ttf",
    },
    "devanagari": {400: "NotoDevanagari-400.ttf", 700: "NotoDevanagari-700.ttf"},
    "malayalam": {400: "NotoMalayalam-400.ttf", 700: "NotoMalayalam-700.ttf"},
}
_SYSTEM_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)
_CACHE: dict[tuple[str, int, int], Any] = {}


def _resolve(weight: int) -> int:
    """Snap a requested weight onto the closest file we ship."""
    for candidate in (700, 600, 500, 800, 400):
        if weight <= candidate:
            return candidate
    return 400


def _covers(font, text: str) -> bool:
    """True when *font* can draw every printable character of *text*."""
    if not text:
        return True
    try:
        cmap = font.font.getbestcmap() if hasattr(font, "font") else None
        if cmap is None:  # pragma: no cover - old Pillow
            return True
        for char in text:
            if char.isspace():
                continue
            if ord(char) not in cmap:
                return False
        return True
    except Exception:  # pragma: no cover - be permissive
        return True


def font(size: int, weight: int = 400, text: str = ""):
    """A font that can render *text*, falling back through the families."""
    if not PIL_AVAILABLE:
        return None
    order = ["inter", "devanagari", "malayalam"]
    if text and any("\u0d00" <= char <= "\u0d7f" for char in text):
        order = ["malayalam", "inter", "devanagari"]
    elif text and any("\u0900" <= char <= "\u097f" for char in text):
        order = ["devanagari", "inter", "malayalam"]

    for family in order:
        files = _FAMILIES.get(family) or {}
        weight_key = _resolve(weight)
        path = FONT_DIR / files.get(weight_key, "")
        if not path.is_file():
            continue
        key = (family, weight_key, size)
        loaded = _CACHE.get(key)
        if loaded is None:
            try:
                loaded = ImageFont.truetype(str(path), size)
            except Exception:  # pragma: no cover
                continue
            _CACHE[key] = loaded
        if not text or _covers(loaded, text):
            return loaded

    key = ("system", 400, size)
    loaded = _CACHE.get(key)
    if loaded is None:
        for candidate in _SYSTEM_FONTS:
            if Path(candidate).is_file():
                try:
                    loaded = ImageFont.truetype(candidate, size)
                    break
                except Exception:  # pragma: no cover
                    continue
        if loaded is None:  # pragma: no cover
            loaded = ImageFont.load_default()
        _CACHE[key] = loaded
    return loaded


def _clip(draw, text: str, face, max_width: int) -> str:
    text = str(text or "")
    if draw.textlength(text, font=face) <= max_width:
        return text
    while text and draw.textlength(f"{text}…", font=face) > max_width:
        text = text[:-1]
    return f"{text}…" if text else "…"


def _wrap(draw, text: str, face, max_width: int, limit: int = 2) -> list[str]:
    words = str(text or "").split()
    if not words:
        return ["Unknown track"]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=face) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == limit:
            break
    if current and len(lines) < limit:
        lines.append(current)
    if not lines:
        lines = ["Unknown track"]
    lines = [_clip(draw, line, face, max_width) for line in lines[:limit]]
    joined = " ".join(lines)
    if len(joined) < len(" ".join(words)) and lines:
        lines[-1] = _clip(draw, lines[-1].rstrip("…") + " …", face, max_width)
    return lines


def _letterspaced(draw, xy, text: str, face, fill, spacing: int = 3) -> int:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=face, fill=fill)
        x += draw.textlength(char, font=face) + spacing
    return int(x)


# ── colour ──────────────────────────────────────────────────────────────────
def _accent_from(art) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Pick a vivid accent + a cooler companion out of the artwork."""
    try:
        small = art.convert("RGB").resize((48, 48))
        quantised = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = quantised.getpalette() or []
        counts = sorted(quantised.getcolors() or [], reverse=True)
        for count, index in counts[:6]:
            r, g, b = palette[index * 3 : index * 3 + 3]
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s < 0.25 or v < 0.16:
                continue
            # keep it luminous: brand-adjacent hues only get a nudge, others
            # are lifted so the poster never turns muddy
            s = min(1.0, max(0.45, s))
            v = min(1.0, max(0.62, v))
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            accent = (int(r * 255), int(g * 255), int(b * 255))
            h2 = (h + 0.09) % 1.0
            r2, g2, b2 = colorsys.hsv_to_rgb(h2, min(1.0, s * 0.9), min(1.0, v * 0.85))
            return accent, (int(r2 * 255), int(g2 * 255), int(b2 * 255))
    except Exception as exc:  # pragma: no cover - palette maths is best effort
        logger.debug("accent extraction failed: %s", exc)
    return ACCENT_2, ACCENT


def _gradient(size: tuple[int, int], top: tuple[int, int, int], bottom: tuple[int, int, int]):
    strip = Image.new("RGB", (1, size[1]))
    draw = ImageDraw.Draw(strip)
    for y in range(size[1]):
        ratio = y / max(1, size[1] - 1)
        draw.point((0, y), fill=tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3)))
    return strip.resize(size)


def _cover(cover: bytes | None, size: int = 360):
    if cover:
        try:
            image = Image.open(io.BytesIO(cover)).convert("RGB")
            w, h = image.size
            side = min(w, h)
            image = image.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2))
            return image.resize((size, size), Image.LANCZOS)
        except Exception as exc:
            logger.debug("cover decode failed: %s", exc)
    placeholder = Image.new("RGB", (size, size), (18, 20, 30))
    draw = ImageDraw.Draw(placeholder)
    centre = size // 2
    for radius, colour in ((150, (26, 30, 46)), (110, (22, 25, 38)), (70, (30, 34, 52))):
        draw.ellipse(
            (centre - radius, centre - radius, centre + radius, centre + radius),
            fill=colour,
        )
    draw.ellipse((centre - 8, centre - 8, centre + 8, centre + 8), fill=ACCENT_2)
    return placeholder


def _rounded(image, radius: int):
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.size[0] - 1, image.size[1] - 1), radius=radius, fill=255)
    return mask


def _background(art, accent) -> "Image.Image":
    backdrop = art.resize((W, H), Image.LANCZOS).filter(ImageFilter.GaussianBlur(46))
    backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), (5, 6, 10)), 0.58)

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-260, -220, 780, 820), fill=tuple(int(c * 0.55) for c in accent))
    draw.ellipse((700, 260, 1560, 1120), fill=tuple(int(c * 0.30) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), (0, 0, 0)), 0.10)
    backdrop = Image.blend(backdrop, glow, 0.28)

    # left-to-right shade keeps the type readable without flattening the art
    shade = Image.new("L", (1, 1))
    strip = Image.new("L", (W, 1))
    for x in range(W):
        strip.putpixel((x, 0), int(120 * max(0.0, 1 - x / (W * 0.62))))
    shade = strip.resize((W, H))
    return Image.composite(_gradient((W, H), (3, 4, 8), (0, 0, 0)), backdrop, shade)


def _vinyl(size: int, accent) -> "Image.Image":
    disc = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(disc)
    centre = size // 2
    draw.ellipse((0, 0, size - 1, size - 1), fill=(12, 12, 16, 255))
    # grooves
    radius = centre - 6
    step = 3
    toggle = 0
    while radius > centre * 0.34:
        shade = 26 if toggle % 3 == 0 else 18
        draw.ellipse(
            (centre - radius, centre - radius, centre + radius, centre + radius),
            outline=(shade, shade, shade + 3, 255),
            width=1,
        )
        radius -= step
        toggle += 1
    # sheen — two soft arcs
    sheen = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(sheen)
    sdraw.arc((14, 14, size - 14, size - 14), 205, 285, fill=(255, 255, 255, 40), width=26)
    sdraw.arc((14, 14, size - 14, size - 14), 25, 95, fill=(255, 255, 255, 18), width=18)
    sheen = sheen.filter(ImageFilter.GaussianBlur(7))
    disc = Image.alpha_composite(disc, sheen)
    draw = ImageDraw.Draw(disc)
    # accent label
    label = int(centre * 0.36)
    draw.ellipse(
        (centre - label, centre - label, centre + label, centre + label),
        fill=(*accent, 255),
    )
    draw.ellipse(
        (centre - label + 8, centre - label + 8, centre + label - 8, centre + label - 8),
        outline=(255, 255, 255, 60),
        width=2,
    )
    draw.ellipse((centre - 7, centre - 7, centre + 7, centre + 7), fill=(8, 8, 12, 255))
    return disc


def _chip(draw, xy: tuple[int, int], label: str, value: str, width: int, accent) -> None:
    """A pill with a micro label and a bold value, like the reference card."""
    x, y = xy
    height = 74
    draw.rounded_rectangle((x, y, x + width, y + height), radius=18, fill=(16, 17, 24, 168))
    draw.rounded_rectangle(
        (x, y, x + width, y + height), radius=18, outline=(255, 255, 255, 26), width=1
    )
    dot_x = x + 18
    draw.ellipse((dot_x, y + 16, dot_x + 9, y + 25), fill=accent)
    _letterspaced(draw, (dot_x + 16, y + 13), label, font(12, 600, label), MUTED, 2)
    draw.text((x + 18, y + 33), value, font=font(27, 600, value), fill=CHIP_TEXT)


def _bars(seed_text: str, count: int) -> list[int]:
    rng = random.Random(seed_text or "vyron")
    heights = []
    for index in range(count):
        wave = math.sin(index / 3.1) * 0.35 + math.sin(index / 1.7) * 0.18
        heights.append(int(max(0.14, min(1.0, 0.55 + wave + rng.uniform(-0.28, 0.28))) * 46))
    return heights


def render(state: ChatState, track: Track, cover: bytes | None = None) -> bytes | None:
    """Render the poster; returns JPEG bytes or ``None`` when Pillow is absent."""
    if not PIL_AVAILABLE or track is None:
        return None
    try:
        art = _cover(cover, 360)
        accent, accent2 = _accent_from(art)
        canvas = _background(art, accent).convert("RGB")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        cover_x, cover_y, cover_size = 84, 192, 360
        vinyl_size = 372
        vinyl_x = cover_x + cover_size - 44
        vinyl_y = cover_y + cover_size // 2 - vinyl_size // 2

        # soft shadow behind the artwork stack
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        sdraw.ellipse(
            (cover_x - 30, cover_y + cover_size - 46, vinyl_x + vinyl_size - 10, cover_y + cover_size + 60),
            fill=(0, 0, 0, 150),
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(38))
        layer = Image.alpha_composite(layer, shadow)

        disc = _vinyl(vinyl_size, accent)
        layer.alpha_composite(disc, (vinyl_x, vinyl_y))

        rounded = art.convert("RGBA")
        layer.paste(rounded, (cover_x, cover_y), _rounded(rounded, 26))
        draw = ImageDraw.Draw(layer)
        draw.rounded_rectangle(
            (cover_x, cover_y, cover_x + cover_size - 1, cover_y + cover_size - 1),
            radius=26,
            outline=(255, 255, 255, 34),
            width=2,
        )

        # ── type column ────────────────────────────────────────────────────
        text_x = 720
        max_width = W - text_x - 62

        _letterspaced(draw, (56, 74), "VYRON", font(17, 600, "VYRON"), (236, 236, 242), 5)
        draw.ellipse((150, 78, 159, 87), fill=accent)

        # NOW PLAYING + equaliser glyph
        bars_x, bars_y = text_x, 158
        for index in range(4):
            height = (14, 26, 20, 32)[index]
            draw.rounded_rectangle(
                (bars_x + index * 9, bars_y + (32 - height), bars_x + index * 9 + 5, bars_y + 32),
                radius=2,
                fill=accent,
            )
        _letterspaced(draw, (text_x + 48, bars_y + 10), "NOW PLAYING", font(15, 600, "NOW PLAYING"), MUTED, 4)

        # Fit the title instead of always truncating: two full lines beat two
        # half-lines, and long "Artist - Title (Official Video)" names are the
        # norm for what people play.
        title = str(track.title or "").strip()
        size, lines = 52, []
        for candidate in (52, 47, 42, 38, 34):
            face = font(candidate, 700, title)
            lines = _wrap(draw, title, face, max_width, limit=2)
            size = candidate
            if "…" not in " ".join(lines):  # everything fits: stop shrinking
                break
        title_y = 214
        for line in lines:
            draw.text((text_x, title_y), line, font=font(size, 700, line), fill=TEXT)
            title_y += int(size * 1.14)

        artist = track.uploader or "unknown artist"
        draw.text(
            (text_x, title_y + 8),
            _clip(draw, artist, font(26, 500, artist), max_width),
            font=font(26, 500, artist),
            fill=MUTED,
        )

        # ── chips ──────────────────────────────────────────────────────────
        chips_y = title_y + 62
        total = int(track.duration or 0)
        requested_name = (getattr(track, "requested_name", "") or "").strip()
        requester = requested_name.split()[0] if requested_name else ""
        if requester:
            duration_w, requester_w = 196, 246
            _chip(draw, (text_x, chips_y), "DURATION", fmt_duration(total) if total else "—", duration_w, accent)
            _chip(
                draw,
                (text_x + duration_w + 16, chips_y),
                "REQUESTED BY",
                _clip(draw, requester, font(27, 600, requester), requester_w - 36),
                requester_w,
                accent,
            )
        else:
            _chip(draw, (text_x, chips_y), "DURATION", fmt_duration(total) if total else "—", 196, accent)
            _chip(draw, (text_x + 212, chips_y), "SOURCE", str(getattr(track, "source", "stream")) or "stream", 190, accent)

        # ── waveform ───────────────────────────────────────────────────────
        elapsed = state.elapsed() if state else 0
        ratio = max(0.0, min(1.0, elapsed / total)) if total else 0.0
        wave_y = 566
        gap = 5
        bar_w = 5
        count = max(12, (W - text_x - 62) // (bar_w + gap))
        heights = _bars(str(track.id or track.title), count)
        cursor = text_x
        played_until = ratio * count
        for index, height in enumerate(heights):
            played = index < played_until
            top = wave_y - height
            draw.rounded_rectangle(
                (cursor, top, cursor + bar_w, wave_y + height // 3),
                radius=2,
                fill=accent if played else (255, 255, 255, 92),
            )
            cursor += bar_w + gap

        draw.text(
            (text_x, wave_y + 42),
            fmt_duration(elapsed),
            font=font(20, 500),
            fill=(226, 226, 236) if elapsed else MUTED,
        )
        total_text = fmt_duration(total) if total else "live"
        face = font(20, 500)
        draw.text(
            (W - 62 - draw.textlength(total_text, font=face), wave_y + 42),
            total_text,
            font=face,
            fill=MUTED,
        )

        _letterspaced(
            draw, (56, H - 74), "MUSIC BEYOND LIMITS", font(13, 500, "MUSIC BEYOND LIMITS"), (150, 150, 168), 3
        )

        canvas = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")
        # accent hairline that ties the poster to the brand
        edge = ImageDraw.Draw(canvas)
        edge.line([(0, H - 3), (W, H - 3)], fill=tuple(int(c * 0.65) for c in accent2), width=3)

        buffer = io.BytesIO()
        canvas.save(buffer, format="JPEG", quality=90, optimize=True, progressive=True)
        return buffer.getvalue()
    except Exception as exc:  # pragma: no cover - never break playback for art
        logger.debug("now-playing artwork failed: %s", exc)
        return None


async def now_playing(state: ChatState, track: Track) -> bytes | None:
    """Fetch the cover art and render the poster off the event loop.

    The render is ~120 ms of pure CPU work; on a busy bot that is long enough to
    delay every other coroutine, so it runs in a thread.
    """
    if not PIL_AVAILABLE or track is None:
        return None
    cover = await fetch_bytes(track.thumbnail, limit=1_400_000) if track.thumbnail else None
    import asyncio

    return await asyncio.to_thread(render, state, track, cover)


__all__ = ["PIL_AVAILABLE", "font", "now_playing", "render"]
