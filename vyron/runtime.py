# ---------------------------------------------------------------------------
#  VYRON — process-wide runtime container
#  A single mutable object so modules can reach shared services without
#  threading dependencies through every handler.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pyrogram import Client

from vyron.config import Settings, settings as default_settings
from vyron.core.charts import Charts
from vyron.core.downloader import Downloader
from vyron.core.lyrics import LyricsClient
from vyron.core.player import Player
from vyron.core.search import YouTube
from vyron.database import Storage

logger = logging.getLogger(__name__)


@dataclass
class Runtime:
    settings: Settings = field(default_factory=lambda: default_settings)
    bot: Client | None = None
    assistant: Client | None = None
    calls: Any = None
    storage: Storage | None = None
    youtube: YouTube | None = None
    downloader: Downloader | None = None
    charts: Charts | None = None
    lyrics: LyricsClient | None = None
    player: Player | None = None
    started_at: float = field(default_factory=time.time)
    version: str = "1.3.0"
    build: str = ""
    handlers_loaded: list[str] = field(default_factory=list)
    # The HTTP port opens before the bot finishes booting, on purpose: a host
    # that never sees the port assumes the deploy failed. That leaves a window
    # where a request arrives while yt-dlp and Mongo are still coming up — the
    # gate below makes those requests *wait* instead of failing with a 503.
    # A plain flag, polled in short steps: an asyncio.Event would bind itself to
    # the first loop that touches it, which breaks every test that builds a
    # fresh loop (and any tooling that restarts the loop).
    _ready: bool = field(default=False, repr=False)
    boot_started_at: float = field(default_factory=time.time)
    # non-fatal problems found at boot; surfaced by /health and /doctor so a
    # degraded deployment explains itself instead of just misbehaving
    boot_problems: list[str] = field(default_factory=list)

    # ── readiness ──────────────────────────────────────────────────────────
    # ── boot gate ──────────────────────────────────────────────────────────
    @property
    def ready(self) -> bool:
        return bool(self._ready)

    def mark_ready(self) -> None:
        """Services are up; anyone waiting on boot may proceed."""
        if not self._ready:
            logger.info("boot gate open after %.1fs", time.time() - self.boot_started_at)
            self._ready = True

    async def wait_ready(self, timeout: float = 20.0) -> bool:
        """Block until boot finishes, or until *timeout* seconds pass.

        Returns True when the services exist. A cold start on a free host can
        take a while, and a user who opened the Mini App during it deserves a
        slower answer rather than an error.
        """
        deadline = time.monotonic() + max(0.0, timeout)
        while not self._ready and time.monotonic() < deadline:
            await asyncio.sleep(min(0.1, max(0.01, deadline - time.monotonic())))
        return self.youtube is not None

    @property
    def streaming_ready(self) -> bool:
        return self.calls is not None and self.assistant is not None

    def require_player(self) -> Player:
        if self.player is None:  # pragma: no cover - defensive
            raise RuntimeError("runtime.player is not initialised")
        return self.player

    @property
    def uptime(self) -> float:
        return max(0.0, time.time() - self.started_at)

    # ── construction ───────────────────────────────────────────────────────
    async def build_services(self) -> None:
        from vyron.database import make_storage

        self.youtube = YouTube(self.settings)
        self.charts = Charts(self.youtube)
        self.downloader = Downloader(self.settings)
        self.lyrics = LyricsClient()
        self.storage = await make_storage(self.settings)
        from vyron.core import acl, sources

        await acl.load(self.storage)
        # Source health survives a deploy, so /doctor can say "Audius has been
        # failing since Tuesday" instead of "no failures since boot".
        await sources.load(self.storage)
        self.player = Player(
            bot=self.bot,
            calls=self.calls,
            settings=self.settings,
            storage=self.storage,
            youtube=self.youtube,
            assistant=self.assistant,
            downloader=self.downloader,
        )
        logger.info("services ready (storage=%s, streaming=%s)", self.storage.backend, self.streaming_ready)

    async def shutdown(self) -> None:
        try:
            from vyron.core import sources

            await sources.save(force=True)
        except Exception:  # pragma: no cover - shutdown must never raise
            pass
        if self.player:
            await self.player.shutdown()
        if self.lyrics:
            await self.lyrics.close()
        if self.storage:
            await self.storage.close()


runtime = Runtime()


__all__ = ["Runtime", "runtime"]
