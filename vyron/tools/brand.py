# ---------------------------------------------------------------------------
#  VYRON — regenerate the brand artwork
#
#      python -m vyron.tools.brand            # start hero + OG card
#      python -m vyron.tools.brand --start    # only /start
#
#  Run it after replacing assets/pfp.png; the outputs are what the bot and the
#  Mini App actually serve.
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description="render VYRON brand artwork")
    parser.add_argument("--start", action="store_true", help="only the /start hero")
    parser.add_argument("--og", action="store_true", help="only the link-preview card")
    parser.add_argument("--out", default="", help="output directory (default: assets/)")
    args = parser.parse_args()

    from vyron.utils import brandart

    out = Path(args.out) if args.out else ROOT / "assets"
    out.mkdir(parents=True, exist_ok=True)
    targets = []
    if not args.og:
        targets.append(("start.jpg", brandart.start_image))
    if not args.start:
        targets.append(("og.jpg", brandart.og_image))

    for name, render in targets:
        raw = render()
        if not raw:
            print(f"{name}: skipped (Pillow missing or render failed)")
            continue
        (out / name).write_bytes(raw)
        print(f"{name}: {len(raw) // 1024} KB → {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
