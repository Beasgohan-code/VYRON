# ---------------------------------------------------------------------------
#  VYRON API — typed request/application state keys
#
#  aiohttp 3.13+ wants AppKey/RequestKey objects instead of bare strings; the
#  shim keeps older releases (pinned at >=3.9) working unchanged.
# ---------------------------------------------------------------------------
from __future__ import annotations

try:  # aiohttp >= 3.13
    from aiohttp.web import AppKey, RequestKey

    REQUEST_ID = RequestKey("vyron_request_id")
    AUTH = RequestKey("vyron_auth")
    RATE_HEADERS = RequestKey("vyron_rate_headers")
    MOUNTED = AppKey("music_api_mounted", bool)
except ImportError:  # pragma: no cover - older aiohttp
    REQUEST_ID = "vyron_request_id"
    AUTH = "vyron_auth"
    RATE_HEADERS = "vyron_rate_headers"
    MOUNTED = "music_api_mounted"


__all__ = ["AUTH", "MOUNTED", "RATE_HEADERS", "REQUEST_ID"]
