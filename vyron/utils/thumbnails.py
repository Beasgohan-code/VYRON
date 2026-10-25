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
import re
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
_MARK_CACHE: dict[int, Any] = {}


def _brand_mark(size: int):
    """The profile mark as a circular RGBA tile, or ``None`` when unavailable."""
    if not PIL_AVAILABLE:
        return None
    cached = _MARK_CACHE.get(size)
    if cached is not None:
        return cached
    path = Path(__file__).resolve().parents[2] / "assets" / "pfp.png"
    try:
        image = Image.open(path).convert("RGB")
        side = min(image.size)
        image = image.crop(
            ((image.width - side) // 2, (image.height - side) // 2,
             (image.width + side) // 2, (image.height + side) // 2)
        ).resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        tile.paste(image, (0, 0), mask)
        ring = ImageDraw.Draw(tile)
        ring.ellipse((0, 0, size - 1, size - 1), outline=(255, 255, 255, 40), width=1)
    except Exception as exc:  # pragma: no cover - brand art is best effort
        logger.debug("brand mark unavailable: %s", exc)
        tile = None
    _MARK_CACHE[size] = tile
    return tile


def _accent_from(art) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Pick a vivid accent + a cooler companion out of the artwork."""
    try:
        small = art.convert("RGB").resize((48, 48))
        quantised = small.quantize(colors=8, method=Image.Quantize.MEDIANCUT)
        palette = quantised.getpalette() or []
        counts = quantised.getcolors() or []
        best = None
        for count, index in counts:
            r, g, b = palette[index * 3 : index * 3 + 3]
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            if s < 0.20 or v < 0.20:
                continue
            # Vividness (not frequency) decides: a small saturated detail in
            # the artwork makes a far better accent than a large grey field.
            # Area still counts a little, so a one-pixel highlight cannot win.
            score = (s ** 1.4) * (v ** 0.6) * (0.35 + 0.65 * (count / (counts[0][0] or 1)) ** 0.25)
            if best is None or score > best[0]:
                best = (score, h, s, v)
        if best is not None:
            _score, h, s, v = best
            # keep it luminous: the poster is dark, so the accent must glow
            s = min(1.0, max(0.55, s))
            v = min(1.0, max(0.72, v))
            r, g, b = colorsys.hsv_to_rgb(h, s, v)
            accent = (int(r * 255), int(g * 255), int(b * 255))
            # companion = the accent pulled halfway toward the brand violet,
            # which keeps every poster in the VYRON palette
            r2 = (accent[0] * 0.55 + ACCENT[0] * 0.45) / 255
            g2 = (accent[1] * 0.55 + ACCENT[1] * 0.45) / 255
            b2 = (accent[2] * 0.55 + ACCENT[2] * 0.45) / 255
            h2, s2, v2 = colorsys.rgb_to_hsv(r2, g2, b2)
            r2, g2, b2 = colorsys.hsv_to_rgb(h2, min(1.0, s2 * 1.05), v2)
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
    # No cover art (search results often arrive without one): draw a sleeve
    # that looks designed on purpose rather than an empty grey tile.
    placeholder = _gradient((size, size), (30, 24, 56), (10, 11, 18))
    draw = ImageDraw.Draw(placeholder, "RGBA")
    centre = size // 2
    for index, radius in enumerate(range(int(size * 0.46), 0, -int(size * 0.055))):
        alpha = 12 + index * 5
        draw.ellipse(
            (centre - radius, centre - radius, centre + radius, centre + radius),
            outline=(255, 255, 255, alpha),
            width=2,
        )
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(
        (centre - 96, centre - 96, centre + 96, centre + 96),
        fill=(*ACCENT, 90),
    )
    placeholder = Image.alpha_composite(
        placeholder.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(48))
    ).convert("RGB")
    draw = ImageDraw.Draw(placeholder)
    draw.ellipse(
        (centre - 46, centre - 46, centre + 46, centre + 46),
        outline=(*ACCENT_2, 120),
        width=3,
    )
    draw.ellipse((centre - 6, centre - 6, centre + 6, centre + 6), fill=ACCENT_2)
    return placeholder


def _rounded(image, radius: int):
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.size[0] - 1, image.size[1] - 1), radius=radius, fill=255)
    return mask


def _backdrop(image_bytes: bytes | None):
    """Cover-crop an arbitrary picture to the poster's 16:9 canvas."""
    if not image_bytes:
        return None
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        scale = max(W / image.width, H / image.height)
        size = (max(W, round(image.width * scale)), max(H, round(image.height * scale)))
        image = image.resize(size, Image.LANCZOS)
        left = (image.width - W) // 2
        top = (image.height - H) // 2
        return image.crop((left, top, left + W, top + H))
    except Exception as exc:  # pragma: no cover - never break playback for art
        logger.debug("custom backdrop decode failed: %s", exc)
        return None


def _background(
    art,
    accent,
    backdrop=None,
    dim: float = 0.42,
    blur: int = 46,
    glow_strength: float = 0.34,
) -> "Image.Image":
    base = backdrop if backdrop is not None else art.resize((W, H), Image.LANCZOS)
    # The darkening tint carries the artwork's own hue instead of going
    # grey-black: a warm sleeve keeps a warm poster, which is the difference
    # between "a UI wrapped around a song" and "a picture of the song".
    tint = tuple(int(channel * 0.11) for channel in accent)
    backdrop = base.filter(ImageFilter.GaussianBlur(blur))
    backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), tint), dim)

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-260, -220, 780, 820), fill=tuple(int(c * 0.55) for c in accent))
    draw.ellipse((700, 260, 1560, 1120), fill=tuple(int(c * 0.30) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    backdrop = Image.blend(backdrop, Image.new("RGB", (W, H), tint), 0.10)
    backdrop = Image.blend(backdrop, glow, glow_strength)

    # left-to-right shade keeps the type readable without flattening the art
    shade = Image.new("L", (1, 1))
    strip = Image.new("L", (W, 1))
    for x in range(W):
        strip.putpixel((x, 0), int(120 * max(0.0, 1 - x / (W * 0.62))))
    shade = strip.resize((W, H))
    backdrop = Image.composite(_gradient((W, H), (3, 4, 8), (0, 0, 0)), backdrop, shade)
    if blur < 46:
        # A photo brings its own detail; darken the right-hand type column so
        # the title never fights the artwork.
        column = Image.new("L", (W, 1))
        for x in range(W):
            column.putpixel((x, 0), int(150 * max(0.0, (x - W * 0.42) / (W * 0.58))))
        column = column.resize((W, H))
        backdrop = Image.composite(Image.new("RGB", (W, H), (3, 4, 8)), backdrop, column)
    return backdrop


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
    # Shrink to fit rather than clip: a chip that ends in "…" is a name the
    # bot could not be bothered to show.
    room = width - 36
    size = 27
    for candidate in (27, 25, 23, 21, 19, 17):
        size = candidate
        face = font(candidate, 600, value)
        if draw.textlength(value, font=face) <= room:
            break
    draw.text(
        (x + 18, y + 33 + max(0, (27 - size) // 2)),
        value,
        font=font(size, 600, value),
        fill=CHIP_TEXT,
    )


def _bars(seed_text: str, count: int) -> list[int]:
    rng = random.Random(seed_text or "vyron")
    heights = []
    for index in range(count):
        wave = math.sin(index / 3.1) * 0.35 + math.sin(index / 1.7) * 0.18
        heights.append(int(max(0.14, min(1.0, 0.55 + wave + rng.uniform(-0.28, 0.28))) * 46))
    return heights


def render(
    state: ChatState,
    track: Track,
    cover: bytes | None = None,
    backdrop: bytes | None = None,
) -> bytes | None:
    """Render the poster; returns JPEG bytes or ``None`` when Pillow is absent.

    ``backdrop`` is the chat's custom artwork (`/thumbnail`): it replaces the
    blurred cover behind the type, while the colour accent and the cover tile
    still come from the song, so the poster stays recognisably *this* track in
    a room that has its own branding.
    """
    if not PIL_AVAILABLE or track is None:
        return None
    try:
        art = _cover(cover, 360)
        custom = _backdrop(backdrop)
        # With no cover art there is no song colour to pull, so the custom
        # artwork supplies the palette instead of a grey placeholder.
        accent, accent2 = _accent_from(art if cover or custom is None else custom)
        if custom:
            # A chat's own artwork should still be recognisable: less blur,
            # less dimming, and a softer colour wash on top of it.
            canvas = _background(
                art, accent, backdrop=custom, dim=0.46, blur=22, glow_strength=0.16
            ).convert("RGB")
        else:
            canvas = _background(art, accent).convert("RGB")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        cover_x, cover_y, cover_size = 72, 188, 344
        vinyl_size = 348
        vinyl_x = cover_x + cover_size - 36
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
        text_x = 744
        max_width = W - text_x - 56

        # hairline that separates the artwork from the type column
        draw.line(
            [(text_x - 30, 176), (text_x - 30, 560)],
            fill=(255, 255, 255, 16),
            width=1,
        )

        # ── letterhead ─────────────────────────────────────────────────────
        mark = _brand_mark(30)
        mark_y = 54
        if mark is not None:
            layer.alpha_composite(mark, (56, mark_y))
        wordmark_x = 56 + (44 if mark is not None else 0)
        _letterspaced(draw, (wordmark_x, 60), "VYRON", font(16, 700, "VYRON"), (240, 240, 246), 5)
        _letterspaced(
            draw,
            (wordmark_x + 1, 82),
            "MUSIC BEYOND LIMITS",
            font(10, 500, "MUSIC BEYOND LIMITS"),
            (128, 128, 148),
            2,
        )

        # “NOW PLAYING” + a tiny equaliser, aligned with the type column
        for index in range(4):
            height = (13, 24, 18, 30)[index]
            draw.rounded_rectangle(
                (text_x + index * 9, 66 + (30 - height), text_x + index * 9 + 5, 96),
                radius=2,
                fill=accent,
            )
        _letterspaced(
            draw,
            (text_x + 48, 70),
            "NOW PLAYING",
            font(14, 600, "NOW PLAYING"),
            MUTED,
            4,
        )

        # The name a person would write, not the one the uploader chose: the
        # poster is a picture of *this song*, so a repost account and an
        # "(Official Video)" do not belong in the largest type on it.
        from vyron.utils.naming import display_parts, poster_name

        artist_name, song_name = display_parts(track.title, track.uploader)
        title = poster_name(song_name or str(track.title or "").strip(), limit=64) or "Unknown"
        size, lines = 58, []
        for candidate in (58, 52, 46, 40, 34, 30):
            face = font(candidate, 700, title)
            lines = _wrap(draw, title, face, max_width, limit=2)
            size = candidate
            if "…" not in " ".join(lines):  # everything fits: stop shrinking
                break
        title_y = 168
        for line in lines:
            draw.text((text_x, title_y), line, font=font(size, 700, line), fill=TEXT)
            title_y += int(size * 1.15)

        artist = poster_name(artist_name, limit=40) or "unknown artist"
        # title_y already advanced past the last line; the small extra gap keeps
        # descenders (g, y, p) from touching the artist line
        artist_y = title_y + 2
        draw.text(
            (text_x, artist_y),
            _clip(draw, artist, font(27, 500, artist), max_width),
            font=font(27, 500, artist),
            fill=(224, 224, 232),
        )

        # ── chips ──────────────────────────────────────────────────────────
        chips_y = artist_y + 62
        total = int(track.duration or 0)
        # The whole display name, clipped to the chip — taking the first word
        # turned "Beast Gohan" into "Beast" on the poster, which is somebody
        # else's name.
        requester = poster_name(getattr(track, "requested_name", ""), limit=22)
        if requester:
            duration_w, requester_w = 176, 300
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
            source = str(getattr(track, "source", "stream")) or "stream"
            _chip(draw, (text_x, chips_y), "DURATION", fmt_duration(total) if total else "—", 176, accent)
            _chip(draw, (text_x + 192, chips_y), "SOURCE", source[:12], 220, accent)

        # ── waveform ───────────────────────────────────────────────────────
        elapsed = state.elapsed() if state else 0
        ratio = max(0.0, min(1.0, elapsed / total)) if total else 0.0
        wave_y = 596
        gap = 4
        bar_w = 4
        count = max(12, (W - text_x - 56) // (bar_w + gap))
        heights = _bars(str(track.id or track.title), count)
        cursor = text_x
        played_until = ratio * count
        for index, height in enumerate(heights):
            played = index < played_until
            mix = index / max(1, count - 1)
            colour = tuple(
                int(accent[channel] * (1 - mix) + accent2[channel] * mix) for channel in range(3)
            )
            top = wave_y - height
            draw.rounded_rectangle(
                (cursor, top, cursor + bar_w, wave_y + height // 3),
                radius=2,
                fill=(*colour, 255) if played else (*colour, 62),
            )
            cursor += bar_w + gap

        if ratio:
            head = text_x + ratio * count * (bar_w + gap)
            draw.line([(head, wave_y - 58), (head, wave_y + 20)], fill=(*accent2, 210), width=2)

        draw.text(
            (text_x, wave_y + 34),
            fmt_duration(elapsed),
            font=font(19, 500),
            fill=(226, 226, 236) if elapsed else MUTED,
        )
        total_text = fmt_duration(total) if total else "live"
        face = font(19, 500)
        draw.text(
            (W - 56 - draw.textlength(total_text, font=face), wave_y + 34),
            total_text,
            font=face,
            fill=MUTED,
        )

        # ── up next (fills the space under the sleeve with real information) ─
        upcoming = [item for item in (state.queue if state else []) if item][:1]
        if upcoming:
            nxt = upcoming[0]
            _letterspaced(draw, (56, 566), "UP NEXT", font(11, 600, "UP NEXT"), (132, 132, 152), 3)
            from vyron.utils.naming import display_line, poster_name

            next_name = poster_name(display_line(nxt.title, nxt.uploader), limit=46)
            face = font(19, 500, next_name)
            draw.text(
                (56, 588),
                _clip(draw, next_name, face, 300),
                font=face,
                fill=(214, 214, 226),
            )
            face = font(17, 500)
            meta = f"{getattr(nxt, 'uploader', '') or fmt_duration(getattr(nxt, 'duration', 0))}"
            draw.text((56, 616), _clip(draw, meta, face, 300), font=face, fill=(132, 132, 152))

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


#: YouTube's thumbnail names, smallest to largest. `maxresdefault` is 1280×720
#: and only exists for uploads that were encoded from an HD source.
_YT_THUMBS = ("default", "mqdefault", "hqdefault", "sddefault", "maxresdefault")


def best_cover_url(url: str | None) -> str:
    """The largest version of a cover URL, when the CDN offers one.

    Pure string work — no request — so a missing maxres costs one failed fetch
    and no latency of its own.
    """
    if not url:
        return ""
    text = str(url).strip()
    # i.ytimg.com / img.youtube.com: swap the size name in the file name.
    for small in _YT_THUMBS[:-1]:
        for host in ("ytimg.com", "youtube.com"):
            if host in text and f"/{small}.jpg" in text:
                return text.replace(f"/{small}.jpg", "/maxresdefault.jpg")
    # Audius and friends: a square size hint in the path.
    match = re.search(r"/(\d{2,4})x(\d{2,4})/", text)
    if match:
        largest = max(int(match.group(1)), int(match.group(2)))
        if largest < 1000:
            return re.sub(r"/\d{2,4}x\d{2,4}/", "/1000x1000/", text, count=1)
    return text


async def now_playing(
    state: ChatState,
    track: Track,
    *,
    backdrop: bytes | None = None,
) -> bytes | None:
    """Fetch the cover art and render the poster off the event loop.

    The render is ~120 ms of pure CPU work; on a busy bot that is long enough to
    delay every other coroutine, so it runs in a thread.
    """
    if not PIL_AVAILABLE or track is None:
        return None
    cover = None
    if track.thumbnail:
        # Ask for the biggest version of the artwork first: the poster draws it
        # at 344 px and blurs it to 1080 wide, and a 480 px "hq" thumbnail
        # turns to mush behind the type. The original URL is the fallback,
        # because a maxres variant does not exist for every upload.
        big = best_cover_url(track.thumbnail)
        if big and big != track.thumbnail:
            cover = await fetch_bytes(big, limit=3_000_000)
        cover = cover or await fetch_bytes(track.thumbnail, limit=1_400_000)
    import asyncio

    return await asyncio.to_thread(render, state, track, cover, backdrop)


__all__ = ["PIL_AVAILABLE", "font", "now_playing", "render"]
