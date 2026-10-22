#!/usr/bin/env python3
# ---------------------------------------------------------------------------
#  VYRON — premium emoji pack builder
#
#  Turns any Telegram *custom emoji* sticker pack into VYRON's emoji.json:
#
#      python -m vyron.tools.emoji_fetch --pack vyron_premium
#
#  The pack must be a "custom emoji" pack (Telegram only exposes those ids).
#  VYRON matches the pack's emoji characters against its own glyph map, so a
#  pack that covers ▶️ 🔁 📜 … lights up the entire UI automatically.
# ---------------------------------------------------------------------------
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp

from vyron.ui.theme import GLYPHS


def _api(token: str, method: str) -> str:
    return f"https://api.telegram.org/bot{token}/{method}"


async def fetch_pack(token: str, pack: str) -> list[dict]:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(_api(token, "getStickerSet"), params={"name": pack}) as response:
            payload = await response.json(content_type=None)
    if not payload.get("ok"):
        raise SystemExit(f"Telegram error: {payload.get('description')}")
    stickers = payload["result"].get("stickers", [])
    if not stickers:
        raise SystemExit("That pack has no stickers.")
    return stickers


async def run(args: argparse.Namespace) -> int:
    token = args.token or os.getenv("BOT_TOKEN", "")
    if not token:
        print("Provide --token or set BOT_TOKEN", file=sys.stderr)
        return 2

    stickers = await fetch_pack(token, args.pack)
    by_glyph: dict[str, dict] = {}
    for sticker in stickers:
        emoji = sticker.get("emoji")
        custom_id = sticker.get("custom_emoji_id")
        if emoji and custom_id and emoji not in by_glyph:
            by_glyph[emoji] = {"id": str(custom_id), "fallback": emoji}

    mapping: dict[str, dict] = {}
    unmatched: list[str] = []
    for name, glyph in GLYPHS.items():
        if glyph in by_glyph:
            mapping[name] = by_glyph[glyph]
        else:
            unmatched.append(f"{name} ({glyph})")

    out = Path(args.out)
    out.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"✔ {len(mapping)}/{len(GLYPHS)} glyphs matched from “{args.pack}”")
    print(f"✔ wrote {out}")
    if unmatched:
        print("\nNot in this pack (unicode fallback will be used):")
        for item in unmatched:
            print("  ·", item)
    print(
        "\nNext: restart VYRON (or send /emojireload as owner). "
        "Set PREMIUM_EMOJI_FILE if the file is not at ./emoji.json"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Build VYRON's premium emoji pack")
    parser.add_argument("--pack", required=True, help="custom emoji sticker set short name")
    parser.add_argument("--token", default="", help="bot token (defaults to $BOT_TOKEN)")
    parser.add_argument("--out", default="emoji.json", help="output path (default: emoji.json)")
    raise SystemExit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
