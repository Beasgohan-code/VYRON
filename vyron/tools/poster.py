# ---------------------------------------------------------------------------
#  VYRON — regenerate the README's "now playing" examples
#
#      python -m vyron.tools.poster            # both examples
#      python -m vyron.tools.poster --out /tmp
#
#  The cover art in the examples is drawn here on purpose: the README should
#  never carry a copyrighted album sleeve, and a procedural cover shows exactly
#  what the renderer does with an accent colour.
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
import io
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _cover(seed: float, size: int = 640) -> bytes:
    """A warm, wavy sleeve: two aurora ribbons over a lit floor."""
    from PIL import Image, ImageDraw, ImageFilter

    top = (36, 18, 30)
    bottom = (10, 8, 14)
    image = Image.new("RGB", (size, size), top)
    draw = ImageDraw.Draw(image)
    for y in range(size):
        ratio = y / max(1, size - 1)
        draw.line(
            [(0, y), (size, y)],
            fill=tuple(int(top[i] * (1 - ratio) + bottom[i] * ratio) for i in range(3)),
        )

    glow = Image.new("RGB", (size, size), (0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    gdraw.ellipse(
        (size * 0.06, size * 0.02, size * 0.94, size * 0.62),
        fill=(214, 116, 74),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.09))
    image = Image.blend(image, glow, 0.55)

    ribbons = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(ribbons)
    for band, (colour, width, phase) in enumerate(
        (
            ((246, 196, 158, 190), 7, 0.0),
            ((238, 140, 168, 150), 4, 1.6),
            ((255, 232, 208, 90), 2, 3.1),
        )
    ):
        points = []
        for x in range(0, size + 8, 8):
            base = size * (0.56 + 0.05 * math.sin(x / size * 5.4 + seed + phase))
            wave = math.sin(x / size * 9.0 + phase) * size * 0.045
            points.append((x, base + wave + band * 6))
        rdraw.line(points, fill=colour, width=width, joint="curve")
    image = Image.alpha_composite(image.convert("RGBA"), ribbons)

    wash = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(wash).rectangle((0, int(size * 0.72), size, size), fill=(128, 40, 92, 120))
    wash = wash.filter(ImageFilter.GaussianBlur(size * 0.06))
    image = Image.alpha_composite(image, wash)

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description="render the README poster examples")
    parser.add_argument("--out", default="", help="output directory (default: assets/)")
    args = parser.parse_args()

    from vyron.core.queue import ChatState, Track
    from vyron.utils import thumbnails

    if not thumbnails.PIL_AVAILABLE:
        print("Pillow is not installed — nothing to render")
        return 1

    out = Path(args.out) if args.out else ROOT / "assets"
    out.mkdir(parents=True, exist_ok=True)

    state = ChatState(chat_id=-100)
    state.current = Track(
        id="example-1",
        title="LET THE WORLD BURN",
        uploader="Chris Grey",
        duration=164,
        requested_name="Rahul",
    )
    state.queue = [
        Track(id="example-2", title="Starboy", uploader="The Weeknd", duration=230),
        Track(id="example-3", title="Nightcall", uploader="Kavinsky", duration=258),
    ]
    state.offset = 42

    plain = ChatState(chat_id=-100)
    plain.current = Track(
        id="example-4",
        title="Sunset Drive",
        uploader="VYRON Sessions",
        duration=208,
        source="youtube",
    )
    plain.offset = 76

    rendered = 0
    for name, chat, track, seed in (
        ("poster-example.jpg", state, state.current, 0.4),
        ("poster-example-2.jpg", plain, plain.current, 2.2),
    ):
        # Render directly (no network) with the procedural sleeve as the cover.
        data = thumbnails.render(chat, track, _cover(seed))
        if not data:
            print(f"{name}: render failed")
            continue
        (out / name).write_bytes(data)
        rendered += 1
        print(f"{name}: {len(data) // 1024} KB")
    return 0 if rendered else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
