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
#  * legacy records from the old plaintext format (and older upstream
#    databases) are still accepted and transparently upgraded on first use.
#
#  The store is VYRON's normal storage layer: MongoDB when configured, a JSON
#  file otherwise — the same lifecycle as the rest of the bot.
# ---------------------------------------------------------------------------
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from vyron.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

# Per-key rolling caps, on top of the per-minute window. A leaked key should
# cost a bounded number of files, not "until somebody notices": the minute
# limit stops a burst, these stop the quiet overnight drain.
QUOTA_FIELDS = ("daily_requests", "monthly_requests", "daily_bytes", "monthly_bytes")
QUOTA_SAVE_EVERY = 30.0     # seconds between writes for one key's counters

# Wire version of the /v1 surface. Bumped for additive changes that a client
# can act on (new routes, new fields); the bot's own version lives in
# vyron/__init__.py. Sent back as X-API-Version on every response.
API_VERSION = "2.3"

KEY_MARKER = "vyrn_"
KEY_BODY_BYTES = 30  # token_urlsafe(30) → 40 url-safe characters
PREFIX_LENGTH = 12  # "vyrn_" + 7 body chars, enough for a unique lookup
MAX_KEYS_PER_OWNER = 25
#: A revoked key is kept this long and then deleted for good. The grace period
#: exists so `/apikeys` can still show what was revoked and by whom ("did I
#: rotate that one, or did it just stop working?"); after it, keeping the record
#: is only a liability — a hash of a dead secret, sitting in the store forever.
REVOKED_GRACE_DAYS = 7
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
    owner: bool = False

    def has(self, scope: str) -> bool:
        return self.owner or self.open_access or "admin" in self.scopes or scope in self.scopes


@dataclass
class MusicAPI:
    """Key issuing, authentication, scopes and rate limiting."""

    settings: Settings = field(default_factory=lambda: default_settings)
    _memory: dict[str, dict[str, Any]] = field(default_factory=dict)
    _hits: dict[str, deque[float]] = field(default_factory=dict)
    _quota_saved: dict[str, float] = field(default_factory=dict)
    # Live counters per key. The store is written every QUOTA_SAVE_EVERY seconds,
    # but enforcement must be immediate — a cached ledger is the truth while the
    # process is up, and a restart picks the last written snapshot back up.
    _quota: dict[str, dict[str, Any]] = field(default_factory=dict)
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
        by: int | None = None,
        limits: dict[str, int] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Create a key. The raw value is returned **once** in the record.

        `by` records which owner minted it, so an admin-issued key can be told
        apart from one the owner created in the Mini App.
        """
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
            "by": int(by or owner_id),
            "scopes": normalise_scopes(scopes),
            "active": True,
            "created_at": now,
            "expires_at": (now + max(1, int(days)) * 86400) if days else None,
            "last_used_at": None,
            "uses": 0,
            "bytes": 0,
            "rate_limit": max(1, int(rate_limit)) if rate_limit else None,
        }
        for name, value in (limits or {}).items():
            if name in QUOTA_FIELDS and value:
                record[name] = max(1, int(value))
        await self._save(record)
        return {**record, "key": raw}, ""

    async def revoke(
        self,
        owner_id: int | None,
        identifier: str,
        *,
        force: bool = False,
        by: int | None = None,
    ) -> bool:
        """Deactivate by id, prefix or full key. `owner_id=None` = sudo."""
        identifier = (identifier or "").strip()
        if not identifier:
            return False
        for item in await self._load(fresh=True):
            if not self._matches(item, identifier):
                continue
            if not force and owner_id is not None and int(item.get("owner_id", 0)) != int(owner_id):
                return False
            patch = {"active": False, "revoked_at": time.time()}
            if by is not None:
                patch["revoked_by"] = int(by)
            return await self._patch(item, patch)
        return False

    async def purge_revoked(self, days: float | None = None) -> list[dict[str, Any]]:
        """Delete keys revoked more than *days* ago (default seven).

        Returns the records that were removed, so a caller can journal or count
        them. Runs from the housekeeping loop and once at boot; also safe to
        call by hand. Never raises on a backend hiccup — a failed delete simply
        leaves the row for the next sweep.
        """
        grace = REVOKED_GRACE_DAYS if days is None else max(0.0, float(days))
        cutoff = time.time() - grace * 86400
        removed: list[dict[str, Any]] = []
        storage = self._storage()
        for record in await self._load(fresh=True):
            if record.get("active", True):
                continue
            revoked_at = record.get("revoked_at")
            try:
                stamp = float(revoked_at or 0.0)
            except (TypeError, ValueError):
                stamp = 0.0
            if not stamp or stamp > cutoff:
                # No revocation stamp means we cannot prove it is old enough:
                # leave it, and let the next revoke write one.
                continue
            reference = str(record.get("id") or record.get("key") or record.get("prefix") or "")
            if not reference:
                continue
            deleted = False
            if storage is not None:
                try:
                    deleted = bool(await storage.delete_api_key(reference))
                except Exception as exc:  # pragma: no cover - backend hiccup
                    logger.debug("could not delete revoked key %s: %s", record.get("prefix"), exc)
            self._memory.pop(reference, None)
            if deleted or storage is None:
                removed.append(record)
        if removed:
            self._invalidate()
            logger.info(
                "deleted %d revoked API key(s) older than %s day(s)", len(removed), grace
            )
        return removed

    async def rotate(
        self, owner_id: int, identifier: str, *, by: int | None = None
    ) -> tuple[dict[str, Any] | None, str]:
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
            by=by if by is not None else owner_id,
        )
        if record is None:
            return None, error
        await self._patch(
            target,
            {
                "active": False,
                "revoked_at": time.time(),
                "revoked_by": int(by if by is not None else owner_id),
                "replaced_by": record["id"],
            },
        )
        return record, ""

    async def find(
        self, identifier: str, *, owner_id: int | None = None, force: bool = False
    ) -> dict[str, Any] | None:
        """One key record by id / prefix / raw value (never exposes the hash)."""
        identifier = (identifier or "").strip()
        if not identifier:
            return None
        for item in await self._load(fresh=True):
            if not self._matches(item, identifier):
                continue
            if not force and owner_id is not None and int(item.get("owner_id", 0)) != int(owner_id):
                return None
            record = {key: value for key, value in item.items() if key != "hash"}
            record["scopes"] = normalise_scopes(record.get("scopes"))
            record["expired"] = bool(record.get("expires_at") and record["expires_at"] < time.time())
            prefix = str(record.get("prefix") or "")
            record["masked"] = f"{prefix}…" if prefix else ""
            return record
        return None

    async def update_key(
        self,
        owner_id: int | None,
        identifier: str,
        *,
        label: str | None = None,
        scopes: Any = None,
        days: int | None = None,
        rate_limit: int | None = None,
        force: bool = False,
        by: int | None = None,
        limits: dict[str, int] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        """Edit a key in place: label, scopes, expiry, per-key rate limit.

        Rotation is a *different* operation (it mints a new secret) — this one
        never changes the key value, so a client that already holds it keeps
        working while the owner tightens or widens what it may do.
        """
        identifier = (identifier or "").strip()
        if not identifier:
            return None, "an id, prefix or key value is required"
        target = None
        for item in await self._load(fresh=True):
            if self._matches(item, identifier):
                target = item
                break
        if target is None:
            return None, "key not found"
        if not force and owner_id is not None and int(target.get("owner_id", 0)) != int(owner_id):
            return None, "that key belongs to someone else"
        if not target.get("active", True):
            return None, "that key is revoked"

        patch: dict[str, Any] = {"updated_at": time.time()}
        if by is not None:
            patch["updated_by"] = int(by)
        if label is not None:
            text = str(label).strip()[:40]
            if not text:
                return None, "label cannot be empty"
            patch["label"] = text
        if scopes is not None:
            chosen = normalise_scopes(scopes)
            if not chosen:
                return None, "unknown scopes (use read, search, download, admin)"
            patch["scopes"] = chosen
        if rate_limit is not None:
            try:
                value = int(rate_limit)
            except (TypeError, ValueError):
                return None, "rate_limit must be a number"
            if value < 0:
                return None, "rate_limit cannot be negative"
            patch["rate_limit"] = value or None
        for name, value in (limits or {}).items():
            if name not in QUOTA_FIELDS:
                continue
            try:
                number = int(value)
            except (TypeError, ValueError):
                return None, f"{name} must be a number"
            if number < 0:
                return None, f"{name} cannot be negative"
            patch[name] = number or None
        if days is not None:
            try:
                span = int(days)
            except (TypeError, ValueError):
                return None, "days must be a number"
            patch["expires_at"] = (
                time.time() + span * 86400 if span > 0 else None
            )
        if (
            label is None
            and scopes is None
            and rate_limit is None
            and days is None
            and not limits
        ):
            return None, (
                "nothing to change (send label, scopes, days, rate_limit or a quota)"
            )
        if not await self._patch(target, patch):
            return None, "could not save the change"
        record = {key: value for key, value in target.items() if key != "hash"}
        record["scopes"] = normalise_scopes(record.get("scopes"))
        record["expired"] = bool(record.get("expires_at") and record["expires_at"] < time.time())
        logger.info(
            "api key %s updated for %s: %s",
            record.get("prefix"),
            record.get("owner_id"),
            ", ".join(sorted(key for key in patch if key != "updated_at")),
        )
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

    # ── quotas ─────────────────────────────────────────────────────────────
    @staticmethod
    def _periods(now: float | None = None) -> tuple[str, str]:
        stamp = time.gmtime(now or time.time())
        return time.strftime("%Y-%m-%d", stamp), time.strftime("%Y-%m", stamp)

    @staticmethod
    def _reference(record: dict[str, Any]) -> str:
        return str(record.get("id") or record.get("prefix") or record.get("key") or "")

    def _windows(self, record: dict[str, Any], now: float | None = None) -> dict[str, Any]:
        """Today's and this month's counters, reset when the period rolls over."""
        day, month = self._periods(now)
        live = self._quota.get(self._reference(record))
        if live is None:
            stored = record.get("windows")
            live = dict(stored) if isinstance(stored, dict) else {}
            self._quota[self._reference(record)] = live
        windows = live
        if not isinstance(windows, dict):
            windows = {}
        current = windows.get("day")
        if not isinstance(current, dict) or current.get("key") != day:
            windows["day"] = {"key": day, "requests": 0, "bytes": 0}
        current = windows.get("month")
        if not isinstance(current, dict) or current.get("key") != month:
            windows["month"] = {"key": month, "requests": 0, "bytes": 0}
        record["windows"] = windows
        return windows

    @staticmethod
    def _limits(record: dict[str, Any]) -> dict[str, int]:
        out: dict[str, int] = {}
        for name in QUOTA_FIELDS:
            value = record.get(name)
            if value:
                try:
                    out[name] = max(1, int(value))
                except (TypeError, ValueError):
                    continue
        return out

    def quota(self, record: dict[str, Any] | None, now: float | None = None) -> dict[str, Any]:
        """What this key has spent today and this month, and what is left."""
        record = record or {}
        limits = self._limits(record)
        windows = self._windows(record, now)
        day, month = self._periods(now)
        day_used = int(windows["day"].get("requests") or 0)
        day_bytes = int(windows["day"].get("bytes") or 0)
        month_used = int(windows["month"].get("requests") or 0)
        month_bytes = int(windows["month"].get("bytes") or 0)
        remaining = {
            "daily_requests": max(0, limits["daily_requests"] - day_used) if "daily_requests" in limits else None,
            "monthly_requests": max(0, limits["monthly_requests"] - month_used) if "monthly_requests" in limits else None,
            "daily_bytes": max(0, limits["daily_bytes"] - day_bytes) if "daily_bytes" in limits else None,
            "monthly_bytes": max(0, limits["monthly_bytes"] - month_bytes) if "monthly_bytes" in limits else None,
        }
        exceeded = [name for name, left in remaining.items() if left == 0]
        return {
            "limits": limits,
            "used": {
                "day": {"key": day, "requests": day_used, "bytes": day_bytes},
                "month": {"key": month, "requests": month_used, "bytes": month_bytes},
            },
            "remaining": remaining,
            "exceeded": exceeded,
        }

    def _quota_blocked(self, record: dict[str, Any]) -> dict[str, Any] | None:
        state = self.quota(record)
        if not state["exceeded"]:
            return None
        return state

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

        from vyron.core import shortlived

        if shortlived.looks_like_token(raw):
            return self._authenticate_token(raw)

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

        blocked = self._quota_blocked(record)
        if blocked is not None:
            names = ", ".join(blocked["exceeded"])
            return AuthResult(
                False,
                record,
                status=429,
                code="quota_exceeded",
                error=f"quota reached ({names}) — this key is capped for the period",
                limit=self._limit_for(record),
                remaining=0,
                scopes=tuple(normalise_scopes(record.get("scopes"))),
            )

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

    def _authenticate_token(self, raw: str) -> AuthResult:
        """A browser token: signed, scoped, short-lived, and not a key.

        It carries no counters of its own — the owner's window applies — but it
        is rate limited per token id so one open tab cannot drain the quota.
        """
        from vyron.core import shortlived

        try:
            body = shortlived.verify(raw, settings=self.settings)
        except shortlived.TokenError as exc:
            return AuthResult(
                False,
                None,
                status=403,
                code="invalid_token",
                error=f"invalid token: {exc}",
            )
        scopes = tuple(normalise_scopes(body.get("sc")))
        limit = max(int(self.settings.music_api_rate), 60)
        bucket = f"token:{body.get('jti') or body.get('sub')}"
        if not self._consume(bucket, limit):
            remaining, reset_in = self._rate(bucket, limit)
            return AuthResult(
                False,
                None,
                status=429,
                code="rate_limited",
                error=f"rate limit reached ({limit}/min) — retry in {reset_in}s",
                limit=limit,
                remaining=remaining,
                reset_in=reset_in,
                scopes=scopes,
            )
        remaining, reset_in = self._rate(bucket, limit)
        return AuthResult(
            True,
            {"token": True, "owner_id": int(body.get("sub") or 0), "scopes": list(scopes),
             "expires_at": body.get("exp"), "kid": body.get("kid", "")},
            limit=limit,
            remaining=remaining,
            reset_in=reset_in,
            scopes=scopes,
        )

    async def authenticate_owner(self, owner_id: int) -> AuthResult:
        """Authenticate the deployment owner (web-app/API owner token).

        Owner access is scoped to `admin` + everything else, gets a more
        generous window and never touches the key store.
        """
        limit = max(int(self.settings.music_api_rate), 120)
        bucket = f"owner:{int(owner_id)}"
        if not self._consume(bucket, limit):
            remaining, reset_in = self._rate(bucket, limit)
            return AuthResult(
                False,
                None,
                status=429,
                code="rate_limited",
                error=f"rate limit reached ({limit}/min) — retry in {reset_in}s",
                limit=limit,
                remaining=remaining,
                reset_in=reset_in,
                scopes=tuple(SCOPES),
                owner=True,
            )
        remaining, reset_in = self._rate(bucket, limit)
        return AuthResult(
            True,
            None,
            limit=limit,
            remaining=remaining,
            reset_in=reset_in,
            scopes=tuple(SCOPES),
            owner=True,
        )

    async def note_use(self, record: dict[str, Any] | None, *, size: int = 0) -> None:
        if not record:
            return
        now = time.time()
        self._invalidate()
        await self._count_quota(record, size=size, now=now)
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

    async def _count_quota(self, record: dict[str, Any], *, size: int, now: float) -> None:
        """Add one use to today's and this month's window, persist occasionally."""
        if not self._limits(record):
            return    # no caps set: nothing to count
        windows = self._windows(record, now)
        for name in ("day", "month"):
            windows[name]["requests"] = int(windows[name].get("requests") or 0) + 1
            windows[name]["bytes"] = int(windows[name].get("bytes") or 0) + max(0, int(size))
        reference = str(record.get("id") or record.get("prefix") or record.get("key") or "")
        last = self._quota_saved.get(reference, 0.0)
        if now - last < QUOTA_SAVE_EVERY:
            return
        self._quota_saved[reference] = now
        await self._patch(record, {"windows": windows})

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
            "version": API_VERSION,
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
