# ---------------------------------------------------------------------------
#  VYRON — process-wide runtime container
#  A single mutable object so modules can reach shared services without
#  threading dependencies through every handler.
# ---------------------------------------------------------------------------
from __future__ import annotations

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
    version: str = "1.2.0"
    handlers_loaded: list[str] = field(default_factory=list)

    # ── readiness ──────────────────────────────────────────────────────────
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
        from vyron.core import acl

        await acl.load(self.storage)
        self.player = Player(
            bot=self.bot,
            calls=self.calls,
            settings=self.settings,
            storage=self.storage,
            youtube=self.youtube,
        )
        logger.info("services ready (storage=%s, streaming=%s)", self.storage.backend, self.streaming_ready)

    async def shutdown(self) -> None:
        if self.player:
            await self.player.shutdown()
        if self.lyrics:
            await self.lyrics.close()
        if self.storage:
            await self.storage.close()


runtime = Runtime()


__all__ = ["Runtime", "runtime"]
