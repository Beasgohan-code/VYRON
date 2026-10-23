# ---------------------------------------------------------------------------
#  VYRON — brand artwork
#
#  Renders the pictures the bot *is*: the /start hero and the share/OG card.
#  Everything is drawn from the shipped profile mark (assets/pfp.png) plus the
#  same Inter faces the now-playing poster uses, so the bot looks like one
#  product in Telegram, in a chat preview, and inside the Mini App.
#
#      python -m vyron.tools.brand           # write both into assets/
#      python -m vyron.tools.brand --start   # only the /start hero
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import logging
import math
from pathlib import Path

from vyron.utils.thumbnails import PIL_AVAILABLE, font

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
MARK = ROOT / "assets" / "pfp.png"

W, H = 1280, 720

VIOLET = (139, 92, 246)
VIOLET_DEEP = (76, 29, 149)
TEAL = (45, 232, 200)
INK = (5, 5, 10)
TEXT = (250, 250, 255)
MUTED = (170, 168, 190)

try:  # pragma: no cover - optional dependency
    from PIL import Image, ImageDraw, ImageFilter

    _READY = PIL_AVAILABLE
except Exception:  # pragma: no cover
    _READY = False


def _mark(size: int):
    """The profile mark as an RGBA square, or a drawn fallback."""
    if MARK.is_file():
        try:
            with Image.open(MARK) as raw:
                return raw.convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception as exc:  # pragma: no cover
            logger.debug("could not read the brand mark: %s", exc)

    placeholder = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(placeholder)
    draw.ellipse((0, 0, size - 1, size - 1), outline=(*VIOLET, 255), width=6)
    draw.polygon(
        [
            (size * 0.30, size * 0.30),
            (size * 0.50, size * 0.74),
            (size * 0.70, size * 0.30),
            (size * 0.60, size * 0.30),
            (size * 0.50, size * 0.55),
            (size * 0.40, size * 0.30),
        ],
        fill=(235, 235, 245, 255),
    )
    return placeholder


def _circle(image, size: int):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    out = image.resize((size, size), Image.LANCZOS).convert("RGBA")
    out.putalpha(mask)
    return out


def _letterspaced(draw, xy, text: str, face, fill, spacing: int) -> int:
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=face, fill=fill)
        x += draw.textlength(char, font=face) + spacing
    return int(x)


def _backdrop() -> "Image.Image":
    base = _mark(720).convert("RGB").resize((W, H), Image.LANCZOS).filter(
        ImageFilter.GaussianBlur(120)
    )
    base = Image.blend(base, Image.new("RGB", (W, H), INK), 0.52)

    glow = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((-320, -260, 780, 840), fill=tuple(int(c * 0.55) for c in VIOLET))
    draw.ellipse((640, 200, 1620, 1180), fill=tuple(int(c * 0.26) for c in VIOLET_DEEP))
    draw.ellipse((980, -220, 1420, 220), fill=tuple(int(c * 0.18) for c in TEAL))
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    return Image.blend(base, glow, 0.42)


def _aurora_canvas() -> "Image.Image":
    """The classic black canvas: two soft glows and a few drifting bokeh."""
    canvas = Image.new("RGB", (W, H), (4, 5, 8))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    draw.ellipse((W * 0.55, H * 0.18, W * 1.05, H * 0.95), fill=(10, 92, 92))
    draw.ellipse((W * 0.72, H * 0.05, W * 1.10, H * 0.75), fill=(48, 22, 96))
    glow = glow.filter(ImageFilter.GaussianBlur(150))
    canvas = Image.blend(canvas, glow, 0.85)

    bokeh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dots = (
        (0.60, 0.14, 26, (45, 232, 200, 26)),
        (0.66, 0.30, 16, (139, 92, 246, 30)),
        (0.72, 0.10, 34, (45, 232, 200, 18)),
        (0.79, 0.36, 22, (139, 92, 246, 22)),
        (0.86, 0.18, 40, (45, 232, 200, 14)),
        (0.91, 0.42, 18, (139, 92, 246, 26)),
        (0.63, 0.46, 12, (45, 232, 200, 22)),
        (0.95, 0.12, 26, (120, 90, 220, 20)),
    )
    bdraw = ImageDraw.Draw(bokeh)
    for x, y, radius, colour in dots:
        bdraw.ellipse(
            (W * x - radius, H * y - radius, W * x + radius, H * y + radius),
            fill=colour,
        )
    bokeh = bokeh.filter(ImageFilter.GaussianBlur(7))
    return Image.alpha_composite(canvas.convert("RGBA"), bokeh)


def _waveform_layer() -> "Image.Image":
    """Thin sine ribbons that read as a live waveform, not a stock divider."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    bands = (
        ((45, 232, 200, 220), 3, 1.00, 0.0),
        ((45, 232, 200, 150), 2, 0.72, 1.5),
        ((139, 246, 236, 190), 1, 0.46, 2.6),
        ((139, 92, 246, 200), 3, 0.88, 0.8),
        ((168, 128, 255, 150), 2, 0.58, 2.1),
        ((210, 190, 255, 90), 1, 0.34, 3.4),
    )
    left, right = W * 0.34, W * 0.97
    mid = H * 0.50
    for colour, width, scale, phase in bands:
        points = []
        steps = 260
        for index in range(steps + 1):
            ratio = index / steps
            x = left + (right - left) * ratio
            envelope = math.sin(min(1.0, ratio * 1.25) * math.pi) ** 0.6
            wobble = (
                math.sin(ratio * 17 + phase) * 44
                + math.sin(ratio * 41 + phase * 2) * 22
                + math.sin(ratio * 7 + phase / 2) * 58
            )
            points.append((x, mid + wobble * envelope * scale))

        # Draw segment by segment so the ribbon can *fade to nothing* at both
        # ends. Fading only the wobble leaves a flat hairline where every point
        # collapses onto the centre line — which is exactly what the first
        # render shipped with.
        for index in range(steps):
            ratio = (index + 0.5) / steps
            fade = min(1.0, ratio * 5.0) * max(0.0, min(1.0, (0.86 - ratio) / 0.34))
            if fade <= 0.02:
                continue
            alpha = int(colour[3] * fade * (0.45 + 0.55 * envelope))
            if alpha <= 6:
                continue
            draw.line(
                [points[index], points[index + 1]],
                fill=(*colour[:3], alpha),
                width=width,
            )

    glow = layer.filter(ImageFilter.GaussianBlur(11))
    return Image.alpha_composite(glow, layer)


def start_image() -> bytes | None:
    """The /start hero — the classic VYRON banner.

    Big wordmark, the aurora waveform on the right, one gradient underline.  It
    is deliberately quiet: it is the first thing anyone sees, and a logo says
    more than a wall of feature chips.
    """
    if not _READY:
        return None
    try:
        canvas = _aurora_canvas()
        canvas = Image.alpha_composite(canvas, _waveform_layer())

        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # wordmark — the only thing that has to be readable at 300 px wide
        word_x, word_y = 96, 198
        face = font(196, 800, "VYRON")
        cursor = word_x
        for char in "VYRON":
            draw.text((cursor, word_y), char, font=face, fill=(252, 252, 255))
            cursor += draw.textlength(char, font=face) + 6

        # gradient underline with a period dot
        bar_y, bar_h = 448, 5
        bar_left, bar_right = 92, 486
        for x in range(bar_left, bar_right):
            ratio = (x - bar_left) / max(1, bar_right - bar_left)
            colour = tuple(
                int(TEAL[i] * (1 - ratio) + VIOLET[i] * ratio) for i in range(3)
            )
            draw.line([(x, bar_y), (x, bar_y + bar_h)], fill=(*colour, 255))
        draw.ellipse((bar_right + 6, bar_y - 3, bar_right + 20, bar_y + 11), fill=(*VIOLET, 255))

        # a whisper of the tagline, bottom-left, so the banner has a footer
        _letterspaced(
            draw,
            (96, H - 96),
            "MUSIC BEYOND LIMITS",
            font(15, 600, "MUSIC BEYOND LIMITS"),
            (120, 118, 142),
            4,
        )

        canvas = Image.alpha_composite(canvas.convert("RGBA"), layer).convert("RGB")
        buffer = io.BytesIO()
        canvas.save(buffer, format="JPEG", quality=92, optimize=True, progressive=True)
        return buffer.getvalue()
    except Exception as exc:  # pragma: no cover
        logger.debug("start hero render failed: %s", exc)
        return None


def og_image() -> bytes | None:
    """1200×630 link preview: same art, room for a headline."""
    if not _READY:
        return None
    try:
        canvas = _backdrop().convert("RGBA")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        size = 300
        x, y = 96, (H - size) // 2
        layer.alpha_composite(_circle(_mark(size), size), (x, y))
        draw.ellipse((x, y, x + size, y + size), outline=(*VIOLET, 220), width=3)

        text_x = 460
        draw.text((text_x, 232), "VYRON", font=font(96, 800, "VYRON"), fill=TEXT)
        _letterspaced(draw, (text_x, 352), "TELEGRAM MUSIC, PROPERLY", font(15, 600, "T"), VIOLET, 4)
        draw.text(
            (text_x, 396),
            "Voice chat · downloads · Mini App",
            font=font(28, 500, "Voice"),
            fill=MUTED,
        )

        canvas = Image.alpha_composite(canvas, layer).convert("RGB")
        ImageDraw.Draw(canvas).line([(0, H - 4), (W, H - 4)], fill=VIOLET, width=4)
        buffer = io.BytesIO()
        canvas.save(buffer, format="JPEG", quality=90, optimize=True, progressive=True)
        return buffer.getvalue()
    except Exception as exc:  # pragma: no cover
        logger.debug("og render failed: %s", exc)
        return None


__all__ = ["og_image", "start_image"]
