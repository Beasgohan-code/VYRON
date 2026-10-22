# ---------------------------------------------------------------------------
#  VYRON — generated "now playing" artwork
#
#  Renders a 1280×720 card (cover, title, artist, progress, footer) with
#  Pillow so /np can answer with a real image instead of a text card.  Returns
#  None whenever Pillow is unavailable, and every caller falls back to the
#  regular card — the dependency therefore stays optional.
# ---------------------------------------------------------------------------
from __future__ import annotations

import io
import logging
from pathlib import Path

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
BG = (11, 11, 18)
TEXT = (245, 245, 250)
MUTED = (152, 152, 174)
ACCENT = (139, 92, 246)
ACCENT_2 = (34, 211, 238)

_FONTS = {
    (True, 24): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    (True, 26): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    (True, 56): "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    (False, 22): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    (False, 24): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    (False, 30): "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
}
_FALLBACK_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
)


def _font(size: int, bold: bool = False):
    if not PIL_AVAILABLE:
        return None
    preferred = _FONTS.get((bold, size))
    for candidate in (preferred, *_FALLBACK_FONTS):
        if candidate and Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:  # pragma: no cover
        return None


def _clip(draw, text: str, font, max_width: int) -> str:
    """Trim *text* with an ellipsis so it fits *max_width*."""
    text = str(text or "")
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(f"{text}…", font=font) > max_width:
        text = text[:-1]
    return f"{text}…" if text else "…"


def _wrap(draw, text: str, font, max_width: int, limit: int = 2) -> list[str]:
    words = str(text or "").split()
    lines: list[str] = []
    current = ""
    consumed = 0
    for index, word in enumerate(words):
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            consumed = index + 1
            continue
        if current:
            lines.append(current)
        current = word
        consumed = index + 1
        if len(lines) == limit - 1:
            # last allowed line: keep appending until it overflows
            for rest in words[index + 1 :]:
                candidate = f"{current} {rest}".strip()
                if draw.textlength(candidate, font=font) > max_width:
                    break
                current = candidate
                consumed += 1
            break
    if current and len(lines) < limit:
        lines.append(current)
    if not lines:
        lines = ["Unknown track"]
    clipped = [_clip(draw, line, font, max_width) for line in lines]
    if consumed < len(words):
        clipped[-1] = _clip(draw, clipped[-1].rstrip("…") + "…", font, max_width)
    return clipped


def _background() -> "Image.Image":
    base = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(glow)
    for x in range(W):
        ratio = x / max(1, W - 1)
        colour = tuple(int(ACCENT[i] * (1 - ratio) + ACCENT_2[i] * ratio) for i in range(3))
        draw.line([(x, 0), (x, H)], fill=colour)
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    return Image.blend(base, glow, 0.24)


def _cover_art(cover: bytes | None, size: int = 420) -> "Image.Image":
    if cover:
        try:
            image = Image.open(io.BytesIO(cover)).convert("RGB")
            return image.resize((size, size), Image.LANCZOS)
        except Exception as exc:
            logger.debug("cover decode failed: %s", exc)
    placeholder = Image.new("RGB", (size, size), (26, 26, 42))
    draw = ImageDraw.Draw(placeholder)
    centre = size // 2
    draw.ellipse((centre - 62, centre - 62, centre + 62, centre + 62), fill=(48, 42, 78))
    draw.ellipse((centre - 20, centre - 20, centre + 20, centre + 20), fill=(18, 18, 30))
    draw.ellipse((centre - 5, centre - 5, centre + 5, centre + 5), fill=ACCENT_2)
    return placeholder


def render(state: ChatState, track: Track, cover: bytes | None = None) -> bytes | None:
    """Render the now-playing card. Returns JPEG bytes or ``None``."""
    if not PIL_AVAILABLE or track is None:
        return None
    try:
        image = _background()
        draw = ImageDraw.Draw(image)

        cover_size = 420
        cover_x = 70
        cover_y = (H - cover_size) // 2
        art = _cover_art(cover, cover_size)
        mask = Image.new("L", (cover_size, cover_size), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, cover_size, cover_size), radius=30, fill=255
        )
        image.paste(art, (cover_x, cover_y), mask)

        text_x = cover_x + cover_size + 56
        max_width = W - text_x - 70

        draw.text((text_x, cover_y + 4), "NOW PLAYING", font=_font(24, True), fill=ACCENT_2)

        title_font = _font(56, True)
        y = cover_y + 52
        for line in _wrap(draw, track.title, title_font, max_width, limit=2):
            draw.text((text_x, y), line, font=title_font, fill=TEXT)
            y += 64

        artist_font = _font(30)
        draw.text(
            (text_x, y + 8),
            _clip(draw, track.uploader or "unknown artist", artist_font, max_width),
            font=artist_font,
            fill=MUTED,
        )

        # progress
        elapsed = state.elapsed() if state else 0
        total = int(track.duration or 0)
        bar_y = cover_y + cover_size - 74
        bar_w = max_width
        draw.rounded_rectangle((text_x, bar_y, text_x + bar_w, bar_y + 12), radius=6, fill=(38, 38, 54))
        if total:
            ratio = max(0.0, min(1.0, elapsed / total))
            draw.rounded_rectangle(
                (text_x, bar_y, text_x + max(12, int(bar_w * ratio)), bar_y + 12),
                radius=6,
                fill=ACCENT_2,
            )
        draw.text(
            (text_x, bar_y + 26),
            f"{fmt_duration(elapsed)}  /  {fmt_duration(total) if total else 'live'}",
            font=_font(24),
            fill=MUTED,
        )

        # footer
        draw.text((70, H - 60), "VYRON", font=_font(26, True), fill=(222, 222, 238))
        draw.text((196, H - 56), "· music beyond limits", font=_font(22), fill=MUTED)

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=88, optimize=True)
        return buffer.getvalue()
    except Exception as exc:  # pragma: no cover
        logger.debug("now-playing artwork failed: %s", exc)
        return None


async def now_playing(state: ChatState, track: Track) -> bytes | None:
    """Fetch the cover art (if any) then render the card."""
    if not PIL_AVAILABLE or track is None:
        return None
    cover = await fetch_bytes(track.thumbnail, limit=1_400_000) if track.thumbnail else None
    return render(state, track, cover)


__all__ = ["PIL_AVAILABLE", "now_playing", "render"]
