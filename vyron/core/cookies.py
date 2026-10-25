# ---------------------------------------------------------------------------
#  VYRON — fresh YouTube cookies
#
#  The wall that stops a song on a rented server is not the video: it is a
#  datacenter IP answering YouTube's "confirm you're not a bot". Cookies from a
#  real signed-in browser are the only reliable cure, and a cookie file someone
#  pasted six weeks ago is only slightly better than none — the session expires
#  and the wall comes back, usually in the middle of a party.
#
#  So the file can now look after itself:
#
#      COOKIES_URL=https://…/cookies.txt      refreshed every REFRESH_SECONDS
#      YOUTUBE_COOKIES=…                      still supported, still wins
#      COOKIES_FILE=…                         still supported, never touched
#
#  The download is refused rather than installed when it does not look like a
#  Netscape cookie jar — a placeholder ("paste your cookies here"), an HTML
#  error page or a JSON blob would otherwise be written over a working file and
#  the wall would be blamed on us.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: How often a `COOKIES_URL` is re-read. Six hours is the shortest that is not
#: rude to whatever is hosting the file, and long enough that an expired
#: session is never more than one sweep old.
REFRESH_SECONDS = 6 * 3600

#: Refuse anything bigger than this: a cookie jar is kilobytes, not megabytes.
MAX_BYTES = 512 * 1024

#: Strings that mean "nobody filled this in".
_PLACEHOLDERS = (
    "paste",
    "your_cookies",
    "your-cookies",
    "yourcookies",
    "<cookies>",
    "insert",
    "example.com",
    "changeme",
    "xxxxxxx",
)

_state = {"path": "", "checked": 0.0, "source": ""}


def reset() -> None:
    """Forget everything (tests, and a settings reload)."""
    _state.update({"path": "", "checked": 0.0, "source": ""})


def path() -> str:
    """The cookie file to hand yt-dlp right now ("" when there is none)."""
    return _state["path"]


def source() -> str:
    """Where the current cookies came from: ``env``, ``file``, ``url`` or ""."""
    return _state["source"]


def age() -> float:
    """Seconds since the file behind `path()` was last written (0 if unknown)."""
    current = _state["path"]
    if not current:
        return 0.0
    try:
        return max(0.0, time.time() - Path(current).stat().st_mtime)
    except OSError:
        return 0.0


def usable(text: str) -> bool:
    """Does *text* look like a real Netscape cookie jar?

    Netscape format is tab-separated with seven fields; the value is the last
    one. A jar with nothing in it, an HTML page, a JSON export or a placeholder
    all fail here, which is the point: installing one of those turns a working
    download into a "cookies are invalid" error nobody can trace.
    """
    text = (text or "").strip()
    if not text or len(text) > MAX_BYTES:
        return False
    if text.startswith("{") or text.startswith("["):
        return False  # a JSON export, not what yt-dlp reads
    if "<html" in text[:400].lower() or "<!doctype" in text[:400].lower():
        return False
    rows = 0
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        value = fields[-1].strip()
        if not value or value.lower() in _PLACEHOLDERS:
            continue
        if any(marker in value.lower() for marker in _PLACEHOLDERS):
            continue
        rows += 1
    return rows > 0


def install(text: str, target: Path) -> str:
    """Write *text* to *target* (0600) and make it the active cookie file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    literal = text.strip()
    target.write_text(literal if literal.endswith("\n") else literal + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:  # pragma: no cover - some filesystems have no modes
        pass
    _state.update({"path": str(target), "checked": time.time(), "source": "url"})
    return str(target)


def adopt(path_text: str, *, origin: str = "file") -> str:
    """Use an existing file as the cookie source, if it is there."""
    if not path_text:
        return ""
    candidate = Path(path_text)
    if not candidate.is_file():
        return ""
    _state.update({"path": str(candidate), "checked": time.time(), "source": origin})
    return str(candidate)


async def download(url: str, *, timeout: float = 20.0) -> str:
    """Fetch a cookie jar. Raises on a network error or an implausible body."""
    from vyron.utils import net

    raw = await net.fetch_bytes(url, limit=MAX_BYTES, timeout=timeout)
    if raw is None:
        raise ValueError("nothing came back from COOKIES_URL (or the file is too large)")
    return raw.decode("utf-8", errors="replace")


def _have(path_text: str) -> bool:
    """Is there a file at *path_text*? (sync, so the async path stays async)."""
    return bool(path_text) and Path(str(path_text)).is_file()


def _current() -> str:
    current = _state["path"]
    return current if _have(current) else ""


async def refresh(settings, *, force: bool = False) -> str:
    """Make sure `path()` is a usable cookie file. Never raises.

    Order of preference, which is also the order of authority:

    1. `COOKIES_FILE` — an operator put it there; never overwritten;
    2. `YOUTUBE_COOKIES` — pasted text, materialised once by the resolver;
    3. `COOKIES_URL` — re-downloaded every `REFRESH_SECONDS`, or when *force*
       is set (a wall was just detected).
    """
    file_setting = str(getattr(settings, "cookies_file", "") or "")
    if _have(file_setting):
        if _state["path"] != file_setting:
            logger.info("cookies: using %s", file_setting)
        _state.update({"path": file_setting, "checked": time.time(), "source": "file"})
        return file_setting

    fresh_enough = (
        not force
        and _current()
        and (time.time() - _state["checked"]) < REFRESH_SECONDS
    )
    if fresh_enough:
        return _current()

    url = str(getattr(settings, "cookies_url", "") or "")
    if not url:
        return _current()

    target = Path(str(getattr(settings, "data_dir", "."))) / "youtube-cookies.txt"
    try:
        text = await download(url)
    except Exception as exc:
        logger.warning("cookies: could not refresh from COOKIES_URL (%s)", exc)
        _state["checked"] = time.time()  # do not retry on every single request
        return _current()
    if not usable(text):
        logger.warning(
            "cookies: COOKIES_URL did not return a Netscape cookie jar — keeping the previous one"
        )
        _state["checked"] = time.time()
        return _current()
    installed = install(text, target)
    logger.info("cookies: refreshed %s from COOKIES_URL", installed)
    return installed


__all__ = [
    "MAX_BYTES",
    "REFRESH_SECONDS",
    "adopt",
    "age",
    "download",
    "install",
    "path",
    "refresh",
    "reset",
    "source",
    "usable",
]
