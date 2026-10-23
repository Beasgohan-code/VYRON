# ---------------------------------------------------------------------------
#  VYRON API — authentication, scopes and response headers
# ---------------------------------------------------------------------------
from __future__ import annotations

from aiohttp import web

from vyron.api.errors import ApiError
from vyron.api.state import AUTH, RATE_HEADERS
from vyron.config import settings
from vyron.core.musicapi import AuthResult, get_music_api
from vyron.web.auth import OWNER_TOKEN_PREFIX, verify_owner_token


def raw_key(request: web.Request) -> str:
    value = (
        request.headers.get("X-API-Key")
        or request.headers.get("X-Api-Key")
        or request.headers.get("x-api-key")
        or ""
    ).strip()
    if not value:
        bearer = request.headers.get("Authorization", "")
        if bearer.lower().startswith("bearer "):
            value = bearer[7:].strip()
    if not value:
        value = (request.query.get("key") or "").strip()
    return value


def headers_for(auth: AuthResult) -> dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(auth.limit),
        "X-RateLimit-Remaining": str(max(0, auth.remaining)),
        "X-RateLimit-Reset": str(auth.reset_in),
        "X-API-Version": "2.0",
    }
    if auth.record:
        headers["X-Key-Prefix"] = str(auth.record.get("prefix") or "")
        headers["X-Key-Scopes"] = ",".join(auth.scopes or ())
    elif auth.owner:
        headers["X-Auth-Mode"] = "owner"
        headers["X-Key-Scopes"] = ",".join(auth.scopes or ())
    elif auth.open_access:
        headers["X-Auth-Mode"] = "open"
    return headers


def owner_token(request: web.Request) -> str:
    """`X-Owner-Token` (or an `X-API-Key` carrying a `vown_` token)."""
    header = (request.headers.get("X-Owner-Token") or "").strip()
    if header:
        return header
    key = raw_key(request)
    return key if key.startswith(OWNER_TOKEN_PREFIX) else ""


async def authorize(request: web.Request, scope: str | None = None) -> AuthResult:
    """Authenticate the request and (optionally) enforce a scope.

    Accepts an API key **or** the deployment owner's signed token (which gets
    every scope). Raises :class:`ApiError` with the correct status +
    rate-limit headers so the middleware can render a consistent envelope.
    """
    api = get_music_api()
    token = owner_token(request)
    if token:
        who = verify_owner_token(token, settings.bot_token)
        if who is None or who.user_id not in settings.owners:
            raise ApiError(
                "invalid_key",
                "owner token is invalid, expired or not for this deployment",
                status=403,
                hint="run /apitoken in the bot to mint a fresh one",
            )
        auth = await api.authenticate_owner(who.user_id)
    else:
        auth = await api.authenticate(raw_key(request))
    headers = headers_for(auth)

    if not auth.ok:
        if auth.status == 429:
            headers["Retry-After"] = str(max(1, auth.reset_in))
        raise ApiError(
            auth.code or "invalid_key",
            auth.error or None,
            status=auth.status or 403,
            headers=headers,
        )

    if scope and not auth.has(scope):
        raise ApiError(
            "forbidden_scope",
            f"this key needs the '{scope}' scope (it has: {', '.join(auth.scopes) or 'none'})",
            hint="mint a key with that scope in the Mini App → Music API, or /getapi <label> <scopes>",
            headers=headers,
        )

    request[AUTH] = auth
    request[RATE_HEADERS] = headers
    return auth


def describe(auth: AuthResult) -> dict:
    record = auth.record or {}
    prefix = str(record.get("prefix") or "")
    return {
        "key": f"{prefix}…" if prefix else "",
        "id": record.get("id"),
        "owner": bool(auth.owner),
        "mode": "owner" if auth.owner else ("open" if auth.open_access else "key"),
        "prefix": record.get("prefix"),
        "label": record.get("label", ""),
        "owner_id": record.get("owner_id"),
        "scopes": list(auth.scopes),
        "open_access": bool(auth.open_access),
        "created_at": record.get("created_at"),
        "expires_at": record.get("expires_at"),
        "last_used_at": record.get("last_used_at"),
        "uses": int(record.get("uses") or 0),
        "bytes": int(record.get("bytes") or 0),
        "quota": {
            "limit_per_minute": auth.limit,
            "remaining": max(0, auth.remaining),
            "reset_in": auth.reset_in,
        },
    }


__all__ = ["authorize", "describe", "headers_for", "owner_token", "raw_key"]
