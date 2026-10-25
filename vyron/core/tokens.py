# ---------------------------------------------------------------------------
#  VYRON — issued-token bookkeeping
#
#  Owner tokens are signed with the bot token, which makes them stateless and
#  fast to verify — but "signed" is not the same as "revocable". This module
#  adds the missing half:
#
#    · every owner token carries an *epoch*
#    · revoking bumps the epoch for that owner
#    · a token minted before the bump stops verifying, everywhere
#
#  The epoch lives in storage (Mongo/JSON) and is cached in memory, so the hot
#  path (one web request) costs a dict lookup, not a database round-trip.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time

from vyron.runtime import runtime

logger = logging.getLogger(__name__)

_META_PREFIX = "token_epoch"
_CACHE: dict[int, tuple[int, float]] = {}
_CACHE_TTL = 5.0


def _key(owner_id: int) -> str:
    return f"{_META_PREFIX}:{int(owner_id)}"


def cached_epoch(owner_id: int) -> int | None:
    """Last known epoch, or ``None`` when nothing has been read yet."""
    hit = _CACHE.get(int(owner_id))
    return None if hit is None else hit[0]


async def epoch(owner_id: int, *, fresh: bool = False) -> int:
    """Current revocation epoch for *owner_id* (``0`` when never revoked)."""
    owner_id = int(owner_id or 0)
    now = time.monotonic()
    hit = _CACHE.get(owner_id)
    if hit is not None and not fresh and now - hit[1] < _CACHE_TTL:
        return hit[0]

    storage = getattr(runtime, "storage", None)
    value = 0
    if storage is not None:
        try:
            value = int(await storage.get_meta(_key(owner_id), 0) or 0)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("token epoch read failed: %s", exc)
            value = hit[0] if hit else 0
    _CACHE[owner_id] = (value, now)
    return value


async def revoke_all(owner_id: int) -> int:
    """Invalidate every owner token minted so far. Returns the new epoch."""
    owner_id = int(owner_id or 0)
    next_epoch = (await epoch(owner_id, fresh=True)) + 1
    storage = getattr(runtime, "storage", None)
    if storage is not None:
        await storage.set_meta(_key(owner_id), next_epoch)
    _CACHE[owner_id] = (next_epoch, time.monotonic())
    logger.info("owner tokens revoked for %s (epoch %s)", owner_id, next_epoch)
    return next_epoch


async def accepts(owner_id: int, token_epoch: int) -> bool:
    """Does a token carrying *token_epoch* still verify for this owner?

    A revocation only invalidates tokens minted *before* it. Equality would
    also reject every token minted afterwards — which is how a revoke locked
    the owner out of their own console until they rotated the bot token.
    """
    return int(token_epoch or 0) >= await epoch(owner_id)


def reset_cache() -> None:
    """Forget every cached epoch (tests, and after swapping storage)."""
    _CACHE.clear()


def forge_test_epoch(owner_id: int, value: int) -> None:
    """Test helper: pin the cached epoch without touching storage."""
    _CACHE[int(owner_id)] = (int(value), time.monotonic())


__all__ = ["accepts", "cached_epoch", "epoch", "forge_test_epoch", "reset_cache", "revoke_all"]
