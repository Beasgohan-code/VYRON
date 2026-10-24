# ---------------------------------------------------------------------------
#  VYRON API — error envelope + request identity
#
#  Every failure returns the same shape so clients (and bots) can branch on
#  `code` instead of parsing prose:
#
#      {"ok": false, "error": "human readable", "code": "invalid_key",
#       "hint": "…", "request_id": "req_…"}
# ---------------------------------------------------------------------------
from __future__ import annotations

import secrets
from typing import Any

from aiohttp import web

from vyron.api.state import REQUEST_ID

ERRORS: dict[str, tuple[int, str]] = {
    "bad_request": (400, "the request is missing something or malformed"),
    "invalid_video": (400, "video_id must be a YouTube id (6-24 chars)"),
    "missing_query": (400, "query is required"),
    "missing_key": (401, "send your key in the X-API-Key header"),
    "invalid_key": (403, "that API key does not exist"),
    "revoked_key": (403, "that API key was revoked"),
    "expired_key": (403, "that API key has expired"),
    "forbidden_scope": (403, "this key is missing the required scope"),
    "not_found": (404, "nothing here"),
    "rate_limited": (429, "rate limit reached — retry after X-RateLimit-Reset seconds"),
    "not_ready": (503, "the bot is still starting — retry in a moment"),
    "blocked_url": (400, "that url is not allowed (private, local or a bad scheme)"),
    "invalid_token": (403, "that browser token is invalid or expired — mint a new one"),
    "upstream_failed": (502, "the upstream provider failed"),
    "internal": (500, "unexpected server error"),
}


class ApiError(Exception):
    """Raised anywhere in the API layer; rendered by the middleware."""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        status: int | None = None,
        hint: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        default_status, default_message = ERRORS.get(code, (400, "request failed"))
        self.code = code
        self.status = status or default_status
        self.message = message or default_message
        self.hint = hint or ""
        self.headers = dict(headers or {})
        if self.status == 503 and "Retry-After" not in self.headers:
            # 503 here means "booting", which is temporary: tell the client how
            # long to wait instead of letting it retry in a tight loop.
            self.headers["Retry-After"] = "5"
        super().__init__(self.message)


def request_id(request: web.Request) -> str:
    rid = request.get(REQUEST_ID)
    if not rid:
        rid = "req_" + secrets.token_hex(6)
        request[REQUEST_ID] = rid
    return rid


def _detail(code: str) -> str:
    return ERRORS.get(code, (400, ""))[1]


def envelope(
    error: str,
    *,
    code: str = "bad_request",
    hint: str = "",
    status: int | None = None,
    headers: dict[str, str] | None = None,
    request: web.Request | None = None,
) -> web.Response:
    payload: dict[str, Any] = {
        "ok": False,
        "error": error,
        "code": code,
    }
    if hint:
        payload["hint"] = hint
    if request is not None:
        payload["request_id"] = request_id(request)
    return web.json_response(payload, status=status or ERRORS.get(code, (400, ""))[0], headers=headers)


def error_response(exc: ApiError, request: web.Request) -> web.Response:
    return envelope(
        exc.message,
        code=exc.code,
        hint=exc.hint or _detail(exc.code),
        status=exc.status,
        headers=exc.headers,
        request=request,
    )


__all__ = ["ApiError", "ERRORS", "envelope", "error_response", "request_id"]
