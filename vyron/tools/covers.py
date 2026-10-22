#!/usr/bin/env python3
# ---------------------------------------------------------------------------
#  VYRON — procedural cover art generator
#
#  Renders the abstract gradient covers used by the web app whenever a track
#  has no artwork (offline previews, audio-only Telegram files, private
#  uploads).  Run once after changing the palette:
#
#      python -m vyron.tools.covers
#
#  Output: webapp/assets/covers/01.jpg … 10.jpg
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required: pip install Pillow") from exc

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "webapp" / "assets" / "covers"

SIZE = 512

# name → (top-left colour, bottom-right colour, accent)
PALETTES = [
    ("violet", (124, 92, 255), (32, 194, 214), (255, 255, 255)),
    ("sunset", (255, 122, 89), (255, 60, 172), (255, 236, 210)),
    ("ocean", (26, 90, 255), (0, 214, 190), (225, 250, 255)),
    ("forest", (16, 185, 129), (34, 197, 94), (236, 255, 245)),
    ("amber", (255, 176, 32), (255, 94, 98), (255, 250, 235)),
    ("midnight", (56, 46, 128), (14, 20, 44), (170, 200, 255)),
    ("rose", (244, 114, 182), (139, 92, 246), (255, 240, 250)),
    ("steel", (90, 106, 133), (24, 30, 44), (220, 236, 255)),
    ("lime", (163, 230, 53), (16, 185, 129), (250, 255, 235)),
    ("coral", (255, 107, 107), (255, 209, 102), (255, 248, 240)),
]


def _gradient(size: int, start: tuple, end: tuple, angle: float) -> "Image.Image":
    image = Image.new("RGB", (size, size))
    draw = ImageDraw.Draw(image)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    for y in range(size):
        for step in range(0, size, 4):
            ratio = (step * cos_a + y * sin_a) / size
            ratio = min(1.0, max(0.0, (ratio + 1) / 2))
            colour = tuple(int(start[i] * (1 - ratio) + end[i] * ratio) for i in range(3))
            draw.rectangle((step, y, step + 3, y), fill=colour)
    return image


def _glow(image: "Image.Image", rng: random.Random, accent: tuple) -> "Image.Image":
    """Soft light blooms blended with `screen` so colours stay saturated."""
    size = image.width
    layer = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for _ in range(rng.randint(2, 3)):
        radius = rng.randint(size // 4, int(size * 0.7))
        cx = rng.randint(-radius // 3, size + radius // 3)
        cy = rng.randint(-radius // 3, size + radius // 3)
        tone = tuple(min(255, int(channel * 0.62)) for channel in accent)
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=tone)
    layer = layer.filter(ImageFilter.GaussianBlur(size // 7))
    return ImageChops.screen(image, layer)


def _motif(image: "Image.Image", rng: random.Random, accent: tuple) -> "Image.Image":
    """A single bold geometric motif — arcs and a thin rule."""
    size = image.width
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    stroke = tuple(int(channel * 0.35 + 180) for channel in accent)
    cx = rng.randint(int(size * 0.3), int(size * 0.8))
    cy = rng.randint(int(size * 0.2), int(size * 0.7))
    radius = rng.randint(int(size * 0.2), int(size * 0.42))
    width = max(3, size // 90)
    start = rng.randint(0, 180)
    draw.arc(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        start=start,
        end=start + rng.randint(150, 290),
        fill=(*stroke, 190),
        width=width,
    )
    inner = int(radius * rng.uniform(0.42, 0.6))
    draw.arc(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        start=start + 40,
        end=start + 40 + rng.randint(120, 240),
        fill=(*stroke, 120),
        width=max(2, width - 1),
    )
    # thin diagonal rule
    offset = rng.randint(-size // 6, size // 6)
    draw.line(
        [(size * 0.08, size * 0.86 + offset), (size * 0.92, size * 0.86 - offset)],
        fill=(*stroke, 70),
        width=1,
    )
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def _vignette(image: "Image.Image") -> "Image.Image":
    size = image.width
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((-size * 0.2, -size * 0.2, size * 1.2, size * 1.2), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(size // 6))
    dark = Image.new("RGB", (size, size), (6, 6, 14))
    inner = Image.composite(image, dark, mask)
    return Image.blend(image, inner, 0.55)


def _grain(image: "Image.Image", rng: random.Random) -> "Image.Image":
    size = image.width
    noise = Image.new("L", (size, size))
    noise.putdata([rng.randint(96, 160) for _ in range(size * size)])
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    grain = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(image, grain, 0.07)


def render(name: str, start, end, accent, seed: int, size: int = SIZE) -> "Image.Image":
    rng = random.Random(seed)
    image = _gradient(size, start, end, angle=rng.uniform(0.35, 1.15))
    image = _glow(image, rng, accent)
    image = _motif(image, rng, accent)
    image = _vignette(image)
    return _grain(image, rng)


def main() -> None:
    parser = argparse.ArgumentParser(description="render VYRON fallback covers")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--size", type=int, default=SIZE)
    args = parser.parse_args()

    size = max(128, int(args.size))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for index, (name, start, end, accent) in enumerate(PALETTES, 1):
        image = render(name, start, end, accent, seed=index * 977, size=size)
        target = out_dir / f"{index:02d}.jpg"
        image.save(target, format="JPEG", quality=82, optimize=True)
        print(f"{target.relative_to(ROOT)}  {target.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
