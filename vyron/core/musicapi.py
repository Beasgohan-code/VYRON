# ---------------------------------------------------------------------------
#  VYRON — Music API (Eldian-compatible)
#
#  A small, self-hosted music API for *other* bots and apps, served from the
#  very same process/port as VYRON — so one Render deployment gives you the
#  bot, the Mini App and this API on a single URL:
#
#      POST /v1/track/by-video-id   → audio file (X-API-Key)
#      POST /v1/track/by-query      → audio file from a search string
#      POST /v1/search              → JSON results
#      GET  /v1/info/by-video-id    → JSON metadata (no download)
#      GET  /v1/lyrics              → JSON lyrics (LRCLIB)
#      GET  /v1/health              → status (open)
#      GET  /v1                     → human docs page (open)
#
#  The wire format follows github.com/Eldian-Network/eldian-music-api: the
#  track endpoint streams the file back with the API key in `X-API-Key`, keys
#  live in MongoDB when MONGO_URL is set (JSON storage otherwise), and they are
#  issued/revoked with the owner commands /getapi, /listkey and /revoke.
#
#  On top of that it adds per-key rate limiting, usage counters, key labels,
#  bearer-token auth, Range support (aiohttp FileResponse) and JSON metadata,
#  so it is useful for players as well as downloaders.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from vyron.config import Settings, settings as default_settings

KEY_PREFIX = "vyrn_"
KEY_BODY_BYTES = 30  # token_urlsafe(30) → 40 chars
MAX_KEYS_PER_OWNER = 10
RATE_WINDOW = 60.0
KEY_CACHE_SECONDS = 15.0  # auth hits the cache, not MongoDB, on every request


def generate_key() -> str:
    """A fresh, unambiguous API key (`vyrn_` + 40 url-safe characters)."""
    return KEY_PREFIX + secrets.token_urlsafe(KEY_BODY_BYTES)


def mask_key(key: str) -> str:
    """`vyrn_ab…yz` — safe to show in logs, cards and screenshots."""
    if not key:
        return ""
    if len(key) <= 12:
        return key[:4] + "…"
    return f"{key[:8]}…{key[-4:]}"


def looks_like_key(value: str) -> bool:
    return bool(value) and value.startswith(KEY_PREFIX) and len(value) > 20


@dataclass
class AuthResult:
    """Outcome of an API-key check (never raises into the HTTP layer)."""

    ok: bool
    record: dict[str, Any] | None = None
    status: int = 200
    error: str = ""
    limit: int = 0
    remaining: int = 0
    reset_in: int = 0
    open_access: bool = False


@dataclass
class MusicAPI:
    """Key issuing + authentication on top of VYRON's storage layer."""

    settings: Settings = field(default_factory=lambda: default_settings)
    _memory: dict[str, dict[str, Any]] = field(default_factory=dict)
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _cache: list[dict[str, Any]] | None = field(default=None, repr=False)
    _cache_at: float = field(default=0.0, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # ── persistence (Mongo when available, in-memory otherwise) ────────────
    @staticmethod
    def _storage():
        from vyron.runtime import runtime

        return runtime.storage

    def _invalidate(self) -> None:
        self._cache = None
        self._cache_at = 0.0

    async def _load(self) -> list[dict[str, Any]]:
        if self._cache is not None and time.time() - self._cache_at < KEY_CACHE_SECONDS:
            return [dict(item) for item in self._cache]
        storage = self._storage()
        records: list[dict[str, Any]] | None = None
        if storage is not None:
            try:
                records = await storage.api_keys()
            except Exception:  # pragma: no cover - defensive
                records = None
        if records is None:
            records = [dict(item) for item in self._memory.values()]
        self._cache = [dict(item) for item in records]
        self._cache_at = time.time()
        return records

    async def _save(self, record: dict[str, Any]) -> None:
        self._invalidate()
        storage = self._storage()
        if storage is not None:
            try:
                await storage.add_api_key(record)
                return
            except Exception:  # pragma: no cover - defensive
                pass
        self._memory[str(record["key"])] = dict(record)

    async def _patch(self, key: str, patch: dict[str, Any]) -> bool:
        self._invalidate()
        storage = self._storage()
        if storage is not None:
            try:
                if await storage.update_api_key(key, patch):
                    return True
            except Exception:  # pragma: no cover - defensive
                pass
        record = self._memory.get(str(key))
        if record is None:
            return False
        record.update(patch)
        return True

    # ── issuing / revoking ─────────────────────────────────────────────────
    async def issue(self, owner_id: int, label: str = "") -> tuple[dict[str, Any] | None, str]:
        """Create a key. Returns ``(record, error)`` — error is empty on success."""
        owner_id = int(owner_id or 0)
        if not owner_id:
            return None, "an owner id is required"
        existing = [item for item in await self._load() if int(item.get("owner_id", 0)) == owner_id and item.get("active", True)]
        if len(existing) >= MAX_KEYS_PER_OWNER:
            return None, f"limit of {MAX_KEYS_PER_OWNER} active keys reached — revoke one first"

        record = {
            "key": generate_key(),
            "owner_id": owner_id,
            "label": (label or "bot").strip()[:40] or "bot",
            "active": True,
            "created_at": time.time(),
            "last_used_at": None,
            "uses": 0,
            "bytes": 0,
        }
        await self._save(record)
        return record, ""

    async def revoke(self, owner_id: int | None, key: str, *, force: bool = False) -> bool:
        """Deactivate a key. `owner_id=None` (sudo) revokes anyone's key."""
        key = (key or "").strip()
        if not key:
            return False
        for item in await self._load():
            if str(item.get("key")) != key:
                continue
            if not force and owner_id is not None and int(item.get("owner_id", 0)) != int(owner_id):
                return False
            return await self._patch(key, {"active": False, "revoked_at": time.time()})
        return False

    async def keys(self, owner_id: int | None = None, *, reveal: bool = True) -> list[dict[str, Any]]:
        records = await self._load()
        if owner_id is not None:
            records = [item for item in records if int(item.get("owner_id", 0)) == int(owner_id)]
        out: list[dict[str, Any]] = []
        for item in sorted(records, key=lambda row: row.get("created_at") or 0, reverse=True):
            row = dict(item)
            row["masked"] = mask_key(str(row.get("key", "")))
            row["uses"] = int(row.get("uses") or 0)
            row["bytes"] = int(row.get("bytes") or 0)
            if not reveal:
                row["key"] = row["masked"]
            out.append(row)
        return out

    # ── authentication ─────────────────────────────────────────────────────
    def _rate(self, key: str) -> tuple[int, int]:
        """(remaining, reset_in) for this key inside the current window."""
        now = time.monotonic()
        window = self._hits.setdefault(key, deque())
        while window and now - window[0] > RATE_WINDOW:
            window.popleft()
        limit = max(1, int(self.settings.music_api_rate))
        remaining = max(0, limit - len(window))
        reset_in = int(RATE_WINDOW - (now - window[0])) if window else int(RATE_WINDOW)
        return remaining, max(0, reset_in)

    def _consume(self, key: str) -> bool:
        remaining, _ = self._rate(key)
        if remaining <= 0:
            return False
        self._hits[key].append(time.monotonic())
        return True

    async def authenticate(self, raw: str) -> AuthResult:
        limit = max(1, int(self.settings.music_api_rate))
        raw = (raw or "").strip()
        if not raw:
            if self.settings.music_api_open:
                return AuthResult(True, None, limit=limit, remaining=limit, open_access=True)
            return AuthResult(False, None, status=401, error="missing API key — send X-API-Key")

        record = next((item for item in await self._load() if str(item.get("key")) == raw), None)
        if record is None:
            if self.settings.music_api_open:
                return AuthResult(True, None, limit=limit, remaining=limit, open_access=True)
            return AuthResult(False, None, status=403, error="invalid API key")
        if not record.get("active", True):
            if self.settings.music_api_open:
                return AuthResult(True, None, limit=limit, remaining=limit, open_access=True)
            return AuthResult(False, None, status=403, error="this API key was revoked")

        if not self._consume(raw):
            remaining, reset_in = self._rate(raw)
            return AuthResult(
                False,
                record,
                status=429,
                error=f"rate limit reached ({limit}/min) — retry in {reset_in}s",
                limit=limit,
                remaining=remaining,
                reset_in=reset_in,
            )

        remaining, reset_in = self._rate(raw)
        return AuthResult(
            True, record, limit=limit, remaining=remaining, reset_in=reset_in
        )

    async def note_use(self, record: dict[str, Any] | None, *, size: int = 0) -> None:
        """Bump usage counters after a successful download."""
        if not record:
            return
        key = str(record.get("key"))
        now = time.time()
        self._invalidate()
        storage = self._storage()
        if storage is not None:
            try:
                await storage.bump_api_key(key, uses=1, size=size, stamp=now)
                await storage.bump("api_bytes", max(0, int(size)))
                await storage.bump("api_downloads", 1)
                return
            except Exception:  # pragma: no cover - defensive
                pass
        self._invalidate()
        entry = self._memory.get(key)
        if entry is not None:
            entry["uses"] = int(entry.get("uses") or 0) + 1
            entry["bytes"] = int(entry.get("bytes") or 0) + max(0, int(size))
            entry["last_used_at"] = now

    # ── reporting ──────────────────────────────────────────────────────────
    async def stats(self) -> dict[str, Any]:
        records = await self._load()
        active = [item for item in records if item.get("active", True)]
        return {
            "enabled": bool(self.settings.music_api),
            "open": bool(self.settings.music_api_open),
            "keys": len(active),
            "keys_total": len(records),
            "requests": sum(int(item.get("uses") or 0) for item in records),
            "bytes": sum(int(item.get("bytes") or 0) for item in records),
            "rate_limit": int(self.settings.music_api_rate),
            "storage": (self._storage().backend if self._storage() is not None else "memory"),
        }


_music_api: MusicAPI | None = None


def get_music_api() -> MusicAPI:
    """Process-wide singleton (keys/rates must be shared across requests)."""
    global _music_api
    if _music_api is None:
        _music_api = MusicAPI(settings=default_settings)
    return _music_api


__all__ = [
    "KEY_PREFIX",
    "AuthResult",
    "MusicAPI",
    "generate_key",
    "get_music_api",
    "looks_like_key",
    "mask_key",
]
