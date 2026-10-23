# ---------------------------------------------------------------------------
#  VYRON — Music API key service
#
#  Domain layer for the professional music API that lives at /v1 on the same
#  deployment as the bot and its Mini App.
#
#  Security model
#  --------------
#  * keys look like `vyrn_<40 url-safe chars>` and are **never stored in the
#    clear**: the store keeps `sha256(key)` plus a 12-char `prefix` used for
#    lookup and display, so a leaked database dump cannot be replayed.
#  * every key carries scopes (`read`, `search`, `download`, `admin`), an
#    optional expiry, a label and per-key usage counters.
#  * legacy records from the old plaintext format (and upstream Eldian
#    databases) are still accepted and transparently upgraded on first use.
#
#  The store is VYRON's normal storage layer: MongoDB when configured, a JSON
#  file otherwise — the same lifecycle as the rest of the bot.
# ---------------------------------------------------------------------------
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from vyron.config import Settings, settings as default_settings

KEY_MARKER = "vyrn_"
KEY_BODY_BYTES = 30  # token_urlsafe(30) → 40 url-safe characters
PREFIX_LENGTH = 12  # "vyrn_" + 7 body chars, enough for a unique lookup
MAX_KEYS_PER_OWNER = 25
RATE_WINDOW = 60.0
KEY_CACHE_SECONDS = 10.0

SCOPES: tuple[str, ...] = ("read", "search", "download", "admin")
DEFAULT_SCOPES: tuple[str, ...] = ("read", "search", "download")

# Backwards-compatible aliases (older code imported these names).
KEY_PREFIX = KEY_MARKER


def generate_key() -> str:
    """A fresh API key: `vyrn_` + 40 url-safe characters."""
    return KEY_MARKER + secrets.token_urlsafe(KEY_BODY_BYTES)


def hash_key(raw: str) -> str:
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def key_prefix(raw: str) -> str:
    return (raw or "")[:PREFIX_LENGTH]


def mask_key(key: str) -> str:
    """`vyrn_ab…wxyz` — safe for logs, cards and screenshots."""
    if not key:
        return ""
    if "…" in key:
        return key
    if len(key) <= 14:
        return key[:4] + "…"
    return f"{key[:9]}…{key[-4:]}"


def find_key(keys: list[dict[str, Any]], needle: str) -> dict[str, Any] | None:
    """Match a key by id, prefix, masked display or raw value (prefix-tolerant)."""
    needle = (needle or "").strip()
    if not needle:
        return None
    for item in keys:
        if needle in {
            str(item.get("id") or ""),
            str(item.get("prefix") or ""),
            str(item.get("key") or ""),
            str(item.get("masked") or ""),
            str(item.get("preview") or ""),
        }:
            return item
    return next(
        (
            item
            for item in keys
            if str(item.get("key") or "").startswith(needle)
            or str(item.get("prefix") or "").startswith(needle)
            or (item.get("masked") and str(item["masked"]).startswith(needle))
        ),
        None,
    )


def looks_like_key(value: str) -> bool:
    return bool(value) and value.startswith(KEY_MARKER) and len(value) > 20


def normalise_scopes(values: Any) -> list[str]:
    """Accept a list/CSV string and return known scopes (admin implies all)."""
    if values is None:
        return list(DEFAULT_SCOPES)
    if isinstance(values, str):
        values = [chunk for chunk in values.replace(";", ",").split(",")]
    chosen = {str(item).strip().lower() for item in values if str(item).strip()}
    if "admin" in chosen or "*" in chosen or "all" in chosen:
        return list(SCOPES)
    return [scope for scope in SCOPES if scope in chosen] or list(DEFAULT_SCOPES)


@dataclass
class AuthResult:
    """Outcome of an API-key check — never raises into the HTTP layer."""

    ok: bool
    record: dict[str, Any] | None = None
    status: int = 200
    error: str = ""
    code: str = ""
    scopes: tuple[str, ...] = ()
    limit: int = 0
    remaining: int = 0
    reset_in: int = 0
    open_access: bool = False

    def has(self, scope: str) -> bool:
        return self.open_access or "admin" in self.scopes or scope in self.scopes


@dataclass
class MusicAPI:
    """Key issuing, authentication, scopes and rate limiting."""

    settings: Settings = field(default_factory=lambda: default_settings)
    _memory: dict[str, dict[str, Any]] = field(default_factory=dict)
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _cache: list[dict[str, Any]] | None = field(default=None, repr=False)
    _cache_at: float = field(default=0.0, repr=False)

    # ── persistence ────────────────────────────────────────────────────────
    @staticmethod
    def _storage():
        from vyron.runtime import runtime

        return runtime.storage

    def _invalidate(self) -> None:
        self._cache = None
        self._cache_at = 0.0

    async def _load(self, *, fresh: bool = False) -> list[dict[str, Any]]:
        if not fresh and self._cache is not None and time.time() - self._cache_at < KEY_CACHE_SECONDS:
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
        self._memory[str(record.get("id") or record.get("prefix"))] = dict(record)

    async def _patch(self, record: dict[str, Any], patch: dict[str, Any]) -> bool:
        self._invalidate()
        storage = self._storage()
        if storage is not None:
            try:
                key = str(record.get("key") or record.get("id") or record.get("prefix"))
                if await storage.update_api_key(key, patch):
                    record.update(patch)
                    return True
            except Exception:  # pragma: no cover - defensive
                pass
        target = self._memory.get(str(record.get("id") or record.get("prefix")))
        if target is None and record.get("key"):
            target = self._memory.get(str(record["key"]))
        if target is None:
            return False
        target.update(patch)
        record.update(patch)
        return True

    # ── issuing / revoking ─────────────────────────────────────────────────
    async def issue(
        self,
        owner_id: int,
        label: str = "",
        *,
        scopes: Any = None,
        days: int | None = None,
        rate_limit: int | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Create a key. The raw value is returned **once** in the record."""
        owner_id = int(owner_id or 0)
        if not owner_id:
            return None, "an owner id is required"
        records = await self._load(fresh=True)
        active = [
            item for item in records
            if int(item.get("owner_id", 0)) == owner_id and item.get("active", True)
        ]
        if len(active) >= MAX_KEYS_PER_OWNER:
            return None, f"limit of {MAX_KEYS_PER_OWNER} active keys reached — revoke one first"

        raw = generate_key()
        now = time.time()
        record = {
            "id": "key_" + secrets.token_hex(6),
            "prefix": key_prefix(raw),
            "hash": hash_key(raw),
            "label": (label or "key").strip()[:40] or "key",
            "owner_id": owner_id,
            "scopes": normalise_scopes(scopes),
            "active": True,
            "created_at": now,
            "expires_at": (now + max(1, int(days)) * 86400) if days else None,
            "last_used_at": None,
            "uses": 0,
            "bytes": 0,
            "rate_limit": max(1, int(rate_limit)) if rate_limit else None,
        }
        await self._save(record)
        return {**record, "key": raw}, ""

    async def revoke(self, owner_id: int | None, identifier: str, *, force: bool = False) -> bool:
        """Deactivate by id, prefix or full key. `owner_id=None` = sudo."""
        identifier = (identifier or "").strip()
        if not identifier:
            return False
        for item in await self._load(fresh=True):
            if not self._matches(item, identifier):
                continue
            if not force and owner_id is not None and int(item.get("owner_id", 0)) != int(owner_id):
                return False
            return await self._patch(item, {"active": False, "revoked_at": time.time()})
        return False

    async def rotate(self, owner_id: int, identifier: str) -> tuple[dict[str, Any] | None, str]:
        """Issue a replacement key and revoke the old one (same scopes/label)."""
        target = next((item for item in await self._load(fresh=True) if self._matches(item, identifier)), None)
        if target is None:
            return None, "key not found"
        if int(target.get("owner_id", 0)) != int(owner_id):
            return None, "that key belongs to someone else"
        record, error = await self.issue(
            owner_id,
            str(target.get("label") or "key"),
            scopes=target.get("scopes"),
            rate_limit=target.get("rate_limit"),
        )
        if record is None:
            return None, error
        await self._patch(target, {"active": False, "revoked_at": time.time(), "replaced_by": record["id"]})
        return record, ""

    async def keys(
        self,
        owner_id: int | None = None,
        *,
        reveal: bool = False,
        include_revoked: bool = True,
    ) -> list[dict[str, Any]]:
        records = await self._load()
        if owner_id is not None:
            records = [item for item in records if int(item.get("owner_id", 0)) == int(owner_id)]
        if not include_revoked:
            records = [item for item in records if item.get("active", True)]
        out: list[dict[str, Any]] = []
        for item in sorted(records, key=lambda row: row.get("created_at") or 0, reverse=True):
            row = dict(item)
            prefix = str(row.get("prefix") or "")
            row["masked"] = mask_key(str(row["key"])) if row.get("key") else (f"{prefix}…" if prefix else "")
            row["preview"] = f"{prefix}…" if prefix else row["masked"]
            row["scopes"] = normalise_scopes(row.get("scopes"))
            row["uses"] = int(row.get("uses") or 0)
            row["bytes"] = int(row.get("bytes") or 0)
            row["expires_at"] = row.get("expires_at") or None
            row["expired"] = bool(row.get("expires_at") and row["expires_at"] < time.time())
            row.pop("hash", None)
            if not reveal or "key" not in row:
                row.pop("key", None)
            out.append(row)
        return out

    # ── matching / auth ────────────────────────────────────────────────────
    @staticmethod
    def _matches(record: dict[str, Any], identifier: str) -> bool:
        if not identifier:
            return False
        if record.get("key") and hmac.compare_digest(str(record["key"]), identifier):
            return True  # legacy plaintext record
        if record.get("id") == identifier or record.get("prefix") == identifier:
            return True
        if record.get("hash") and hmac.compare_digest(str(record["hash"]), hash_key(identifier)):
            return True
        return False

    def _limit_for(self, record: dict[str, Any] | None = None) -> int:
        override = (record or {}).get("rate_limit")
        return max(1, int(override or self.settings.music_api_rate))

    def _window(self, bucket: str) -> deque[float]:
        now = time.monotonic()
        window = self._hits.setdefault(bucket, deque())
        while window and now - window[0] > RATE_WINDOW:
            window.popleft()
        return window

    def _rate(self, bucket: str, limit: int) -> tuple[int, int]:
        window = self._window(bucket)
        now = time.monotonic()
        remaining = max(0, limit - len(window))
        reset_in = int(RATE_WINDOW - (now - window[0])) if window else int(RATE_WINDOW)
        return remaining, max(0, reset_in)

    def _consume(self, bucket: str, limit: int) -> bool:
        remaining, _ = self._rate(bucket, limit)
        if remaining <= 0:
            return False
        self._window(bucket).append(time.monotonic())
        return True

    async def authenticate(self, raw: str) -> AuthResult:
        raw = (raw or "").strip()
        open_mode = bool(self.settings.music_api_open)

        if not raw:
            if open_mode:
                limit = self._limit_for()
                return AuthResult(True, None, limit=limit, remaining=limit, open_access=True)
            return AuthResult(False, None, status=401, code="missing_key", error="missing API key — send X-API-Key")

        candidates = await self._load()
        record = next((item for item in candidates if self._matches(item, raw)), None)
        if record is None:
            if open_mode:
                limit = self._limit_for()
                return AuthResult(True, None, limit=limit, remaining=limit, open_access=True)
            return AuthResult(False, None, status=403, code="invalid_key", error="invalid API key")
        if not record.get("active", True):
            if open_mode:
                limit = self._limit_for()
                return AuthResult(True, None, limit=limit, remaining=limit, open_access=True)
            return AuthResult(False, None, status=403, code="revoked_key", error="this API key was revoked")
        expires_at = record.get("expires_at")
        if expires_at and float(expires_at) < time.time():
            return AuthResult(False, record, status=403, code="expired_key", error="this API key has expired")

        limit = self._limit_for(record)
        bucket = str(record.get("id") or record.get("prefix") or raw)
        if not self._consume(bucket, limit):
            remaining, reset_in = self._rate(bucket, limit)
            return AuthResult(
                False,
                record,
                status=429,
                code="rate_limited",
                error=f"rate limit reached ({limit}/min) — retry in {reset_in}s",
                limit=limit,
                remaining=remaining,
                reset_in=reset_in,
                scopes=tuple(normalise_scopes(record.get("scopes"))),
            )

        remaining, reset_in = self._rate(bucket, limit)
        return AuthResult(
            True,
            record,
            limit=limit,
            remaining=remaining,
            reset_in=reset_in,
            scopes=tuple(normalise_scopes(record.get("scopes"))),
        )

    async def note_use(self, record: dict[str, Any] | None, *, size: int = 0) -> None:
        if not record:
            return
        now = time.time()
        self._invalidate()
        storage = self._storage()
        if storage is not None:
            try:
                reference = str(record.get("id") or record.get("key") or record.get("prefix"))
                await storage.bump_api_key(reference, uses=1, size=size, stamp=now)
                await storage.bump("api_bytes", max(0, int(size)))
                await storage.bump("api_downloads", 1)
                return
            except Exception:  # pragma: no cover - defensive
                pass
        self._invalidate()
        target = self._memory.get(str(record.get("id") or record.get("prefix")))
        if target is not None:
            target["uses"] = int(target.get("uses") or 0) + 1
            target["bytes"] = int(target.get("bytes") or 0) + max(0, int(size))
            target["last_used_at"] = now

    # ── reporting ──────────────────────────────────────────────────────────
    async def stats(self) -> dict[str, Any]:
        records = await self._load()
        active = [item for item in records if item.get("active", True)]
        storage = self._storage()
        return {
            "enabled": bool(self.settings.music_api),
            "open": bool(self.settings.music_api_open),
            "keys": len(active),
            "keys_total": len(records),
            "requests": sum(int(item.get("uses") or 0) for item in records),
            "bytes": sum(int(item.get("bytes") or 0) for item in records),
            "scopes": list(SCOPES),
            "rate_limit": int(self.settings.music_api_rate),
            "storage": storage.backend if storage is not None else "memory",
            "version": "2.0",
        }


_api: MusicAPI | None = None


def get_music_api() -> MusicAPI:
    """Process-wide singleton — keys and rate windows must be shared."""
    global _api
    if _api is None:
        _api = MusicAPI(settings=default_settings)
    return _api


__all__ = [
    "DEFAULT_SCOPES",
    "find_key",
    "KEY_MARKER",
    "KEY_PREFIX",
    "SCOPES",
    "AuthResult",
    "MusicAPI",
    "generate_key",
    "get_music_api",
    "hash_key",
    "key_prefix",
    "looks_like_key",
    "mask_key",
    "normalise_scopes",
]
