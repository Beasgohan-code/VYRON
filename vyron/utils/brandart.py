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


def start_image() -> bytes | None:
    """The /start hero: mark on the left, wordmark and facts on the right."""
    if not _READY:
        return None
    try:
        canvas = _backdrop().convert("RGBA")
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)

        # ── mark + ring ────────────────────────────────────────────────────
        size = 400
        x, y = 92, (H - size) // 2
        halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(halo).ellipse(
            (x - 40, y - 40, x + size + 40, y + size + 40),
            fill=(*VIOLET, 110),
        )
        layer = Image.alpha_composite(layer, halo.filter(ImageFilter.GaussianBlur(60)))

        layer.alpha_composite(_circle(_mark(size), size), (x, y))
        draw = ImageDraw.Draw(layer)
        draw.ellipse((x, y, x + size, y + size), outline=(*VIOLET, 220), width=3)
        draw.ellipse((x + 14, y + 14, x + size - 14, y + size - 14), outline=(255, 255, 255, 30), width=1)

        # ── wordmark ───────────────────────────────────────────────────────
        text_x = 588
        _letterspaced(draw, (text_x, 176), "MUSIC BEYOND LIMITS", font(15, 600, "MUSIC BEYOND LIMITS"), VIOLET, 4)

        face = font(104, 800, "VYRON")
        x_cursor = text_x
        for char in "VYRON":
            draw.text((x_cursor, 208), char, font=face, fill=TEXT)
            x_cursor += draw.textlength(char, font=face) + 10
        draw.ellipse((x_cursor + 8, 258, x_cursor + 30, 280), fill=TEAL)

        draw.text(
            (text_x, 344),
            "Stream · search · download",
            font=font(30, 500, "Stream"),
            fill=MUTED,
        )

        # ── feature chips ──────────────────────────────────────────────────
        chips = (("VOICE CHAT", TEAL), ("DOWNLOADS", VIOLET), ("MINI APP", MUTED))
        chip_y = 420
        cursor = text_x
        for label, colour in chips:
            face = font(16, 600, label)
            width = int(draw.textlength(label, font=face) + len(label) * 3 + 46)
            draw.rounded_rectangle(
                (cursor, chip_y, cursor + width, chip_y + 46),
                radius=23,
                fill=(16, 14, 26, 210),
                outline=(255, 255, 255, 26),
                width=1,
            )
            draw.ellipse((cursor + 18, chip_y + 19, cursor + 26, chip_y + 27), fill=colour)
            _letterspaced(draw, (cursor + 34, chip_y + 13), label, face, TEXT, 3)
            cursor += width + 12

        # ── hairline + handle ──────────────────────────────────────────────
        draw.line([(text_x, 556), (W - 92, 556)], fill=(255, 255, 255, 26), width=1)
        _letterspaced(
            draw,
            (text_x, 584),
            "@VYRONMUSICBOT · THREE STEPS",
            font(14, 600, "@VYRONMUSICBOT"),
            (150, 148, 172),
            3,
        )
        draw.text(
            (text_x, 614),
            "Add to a group, start a voice chat, send /play",
            font=font(22, 500, "Add to a group"),
            fill=(196, 194, 214),
        )

        canvas = Image.alpha_composite(canvas, layer).convert("RGB")
        edge = ImageDraw.Draw(canvas)
        edge.line([(0, H - 4), (W, H - 4)], fill=tuple(int(c * 0.7) for c in VIOLET), width=4)

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
