# ---------------------------------------------------------------------------
#  VYRON — short-lived tokens for browsers
# ---------------------------------------------------------------------------
# A Mini App runs inside someone else's WebView. Putting a long-lived `vyrn_`
# key in that JavaScript means the secret lives in a cache, in a screenshot of
# devtools and in whatever the WebView persists. So the browser never sees a
# key: it asks the server for a token that expires in fifteen minutes, carries
# the scopes it may use, and cannot be turned into a new key.
#
# The token is signed with a secret derived from the bot token, so it survives
# a restart and dies the moment the deployment's credentials change:
#
#   vyt_<base64url(payload)>.<base64url(hmac-sha256)>
#
# Nothing here is a JWT on purpose — no algorithm negotiation means nothing to
# downgrade, and the payload is small and fixed.
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

from vyron.config import settings as default_settings

logger = logging.getLogger(__name__)

PREFIX = "vyt_"
DEFAULT_TTL = 900          # 15 minutes
MAX_TTL = 3600


class TokenError(ValueError):
    """Raised when a token is malformed, forged or expired."""


def _secret(settings=None) -> bytes:
    settings = settings or default_settings
    raw = getattr(settings, "api_token_secret", "") or ""
    if not raw:
        # Derived, not random: a token minted before a restart still verifies
        # after it, which matters when Render restarts under a live session.
        material = f"{getattr(settings, 'bot_token', '')}|{getattr(settings, 'owner_id', 0)}|vyron"
        raw = hashlib.sha256(material.encode()).hexdigest()
    return raw.encode()


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload: bytes, settings=None) -> str:
    return _b64(hmac.new(_secret(settings), payload, hashlib.sha256).digest())


def mint(
    *,
    owner_id: int,
    scopes: list[str] | tuple[str, ...] | None = None,
    ttl: int = DEFAULT_TTL,
    key_id: str = "",
    settings=None,
) -> dict[str, Any]:
    """Return `{token, expires_in, scopes}` for a browser session."""
    ttl = max(30, min(MAX_TTL, int(ttl or DEFAULT_TTL)))
    now = int(time.time())
    body = {
        "sub": int(owner_id),
        "sc": list(scopes or ("read", "search")),
        "iat": now,
        "exp": now + ttl,
        "jti": secrets.token_hex(4),
    }
    if key_id:
        body["kid"] = str(key_id)[:32]
    payload = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    token = f"{PREFIX}{_b64(payload)}.{_sign(payload, settings)}"
    return {"token": token, "expires_in": ttl, "scopes": body["sc"], "expires_at": body["exp"]}


def verify(token: str, *, settings=None) -> dict[str, Any]:
    """Return the payload of a valid token, or raise :class:`TokenError`."""
    text = (token or "").strip()
    if not text.startswith(PREFIX):
        raise TokenError("not a Vyron token")
    try:
        encoded, signature = text[len(PREFIX) :].split(".", 1)
        payload = _unb64(encoded)
    except Exception as exc:  # malformed base64 / missing dot
        raise TokenError("malformed token") from exc
    if not hmac.compare_digest(signature, _sign(payload, settings)):
        raise TokenError("bad signature")
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:  # pragma: no cover - signature covers this
        raise TokenError("malformed payload") from exc
    if int(body.get("exp") or 0) < int(time.time()):
        raise TokenError("token expired")
    if not int(body.get("sub") or 0):
        raise TokenError("token has no subject")
    return body


def looks_like_token(value: str) -> bool:
    return (value or "").strip().startswith(PREFIX)


__all__ = ["DEFAULT_TTL", "MAX_TTL", "PREFIX", "TokenError", "looks_like_token", "mint", "verify"]
