# ---------------------------------------------------------------------------
#  VYRON — a modern Telegram voice-chat music bot
#  Kurigram (Pyrogram) · PyTgCalls · yt-dlp · Bot API rich messages
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import sys

__version__ = "1.10.22"
# Shown by /doctor and /health: the fastest way to answer "did my deploy land?"
__build__ = "2026-10-25"
__author__ = "Beasgohan-code"
__repo__ = "https://github.com/Beasgohan-code/VYRON"

BANNER = r"""
 __      __ __   __ ____    ___   _   _
 \ \    / / \ \ / /|  _ \  / _ \ | \ | |
  \ \  / /   \ V / | |_) || | | ||  \| |
   \ \/ /     | |  |  _ < | |_| || |\  |
    \  /      | |  |_| \_\ \___/ |_| \_|
     \/       |_|      telegram music
"""


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        level=getattr(logging, str(level).upper(), logging.INFO),
        force=True,
    )
    for noisy in ("pyrogram", "pytgcalls", "ntgcalls", "yt_dlp", "aiohttp", "pymongo"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    # Every handler now scrubs credentials before writing: keys, bot tokens,
    # connection strings and session strings never reach a log line.
    from vyron.core.redact import install as install_redaction

    install_redaction()


def banner_text() -> str:
    return BANNER.strip("\n")


__all__ = ["BANNER", "__version__", "banner_text", "setup_logging"]
