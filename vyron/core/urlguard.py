# ---------------------------------------------------------------------------
#  VYRON — refuse to fetch the machine's own network
# ---------------------------------------------------------------------------
# `/v1/tracks` and `/play` accept a URL from a stranger. Handing that URL to
# yt-dlp or the downloader without looking at it is server-side request
# forgery: `http://127.0.0.1:6379` or `http://169.254.169.254/latest/meta-data`
# is one line of input away from reading the host's own services.
#
# The rule is simple: http(s) only, and the host must resolve to a public
# address. Anything else is refused before a socket is opened.
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

ALLOWED_SCHEMES = {"http", "https"}
_CACHE: dict[str, bool] = {}


class BlockedURL(ValueError):
    """Raised when a URL points somewhere a media bot must never reach."""


def _is_private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False  # not an IP literal (hostname) — checked after resolution
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _looks_local_host(host: str) -> bool:
    name = (host or "").strip().rstrip(".").lower()
    if not name:
        return True
    if name in {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}:
        return True
    if name.endswith(".local") or name.endswith(".internal") or name.endswith(".localhost"):
        return True
    return False


def check_sync(url: str) -> str:
    """Validate *url* without doing any I/O; returns it unchanged when fine."""
    text = (url or "").strip()
    if not text:
        raise BlockedURL("empty url")
    split = urlsplit(text)
    if split.scheme.lower() not in ALLOWED_SCHEMES:
        raise BlockedURL(f"scheme {split.scheme or '(none)'!r} is not allowed")
    host = split.hostname or ""
    if _looks_local_host(host):
        raise BlockedURL("that url points at the server itself")
    if _is_private(host):
        raise BlockedURL("that url points at a private address")
    if split.username or split.password:
        raise BlockedURL("credentials in a url are not allowed")
    return text


async def check(url: str, *, resolver=None) -> str:
    """Validate *url*, resolving the host to make sure it is public."""
    text = check_sync(url)
    host = urlsplit(text).hostname or ""
    cached = _CACHE.get(host)
    if cached is False:
        raise BlockedURL("that host resolves to a private address")
    if cached is True:
        return text

    loop = asyncio.get_running_loop()
    try:
        infos = await (resolver or loop.getaddrinfo)(host, None)
    except socket.gaierror as exc:
        raise BlockedURL(f"that host does not resolve ({exc})") from exc
    addresses = {info[4][0] for info in infos if info and info[4]}
    if not addresses:
        raise BlockedURL("that host does not resolve")
    for address in addresses:
        if _is_private(address):
            _CACHE[host] = False
            logger.warning("blocked a request for %s (resolves to %s)", host, address)
            raise BlockedURL("that host resolves to a private address")
    _CACHE[host] = True
    return text


def allowed_hosts(settings=None) -> set[str]:
    """Hosts we are allowed to reach even if they live on a private network.

    A self-hosted Cobalt, Invidious or Piped instance usually sits on
    `http://cobalt:8080` inside a compose network. Those are *our* mirrors, so
    they are exempt — a user typing `http://169.254.169.254` is not.
    """
    from vyron.config import settings as default_settings

    settings = settings or default_settings
    hosts: set[str] = set()
    for attribute in ("cobalt_urls", "cobalt_url", "invidious_hosts", "piped_hosts"):
        raw = getattr(settings, attribute, "") or ""
        for chunk in str(raw).replace(",", " ").split():
            host = urlsplit(chunk if "://" in chunk else f"http://{chunk}").hostname
            if host:
                hosts.add(host.lower())
    return hosts


async def check_user_url(url: str, *, settings=None, resolver=None) -> str:
    """The entry point for anything typed by a user or sent by a client."""
    host = (urlsplit(check_sync(url)).hostname or "").lower()
    if host in allowed_hosts(settings):
        return url
    return await check(url, resolver=resolver)


def reset_cache() -> None:
    _CACHE.clear()


__all__ = ["BlockedURL", "allowed_hosts", "check", "check_sync", "check_user_url", "reset_cache"]
