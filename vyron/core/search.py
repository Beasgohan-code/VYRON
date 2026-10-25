# ---------------------------------------------------------------------------
#  VYRON — YouTube / media search & stream resolution
#
#  All yt-dlp work happens in a worker thread (``asyncio.to_thread``) so the
#  event loop — and therefore playback — never blocks.  Direct stream URLs are
#  cached with a TTL because YouTube links expire.
# ---------------------------------------------------------------------------
from __future__ import annotations

import asyncio
import json
import logging
from difflib import SequenceMatcher
from pathlib import Path
import re
import shlex
import time
import dataclasses
from dataclasses import dataclass, field
from urllib.parse import unquote
from typing import Any

import yt_dlp

from vyron.config import Settings
from vyron.core import alternate, metasources, sources, ytmusic
from vyron.core.resolvers import HEALTH
from vyron.core.queue import Track
from vyron.ui.progress import parse_duration, truncate

logger = logging.getLogger(__name__)

#: How long the catalogue lane gets before YouTube is even consulted.
CATALOGUE_GRACE = 1.3
#: How long a *walled* YouTube gets to add names the catalogues missed. Its
#: streams cannot play from this IP, so this is a glance, not a wait.
WALLED_GLANCE = 0.6
#: The last pass over the catalogues when the race came back empty. A false
#: "no results" costs more than two seconds, but not four.
SECOND_CHANCE = 2.5
#: And how long anything gets after that. A search that has not answered by
#: now is not going to feel fast, whatever it contains.
YOUTUBE_DEADLINE = 6.0
#: The same query asked twice in a few minutes is the same answer. Cached for
#: five minutes so the picker's "other results" and a retry cost nothing.
SEARCH_TTL = 300.0
_SEARCH_CACHE: dict[tuple[str, int], tuple[float, list[Track]]] = {}
_SEARCH_CACHE_MAX = 120


def _cache_get(query: str, count: int) -> list[Track] | None:
    hit = _SEARCH_CACHE.get((query.strip().lower(), int(count)))
    if not hit:
        return None
    expires, tracks = hit
    if expires <= time.time():
        _SEARCH_CACHE.pop((query.strip().lower(), int(count)), None)
        return None
    return tracks


def _cache_put(query: str, count: int, tracks: list[Track]) -> None:
    if not tracks:
        return
    if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
        # Cheap eviction: drop whatever expires first.
        for key in sorted(_SEARCH_CACHE, key=lambda item: _SEARCH_CACHE[item][0])[:20]:
            _SEARCH_CACHE.pop(key, None)
    _SEARCH_CACHE[(query.strip().lower(), int(count))] = (time.time() + SEARCH_TTL, list(tracks))


def clear_search_cache() -> None:
    """Tests, and `/clearcache`-style maintenance."""
    _SEARCH_CACHE.clear()


def _stamp(tracks: list[Track], requester: tuple[int, str]) -> list[Track]:
    """Give cached results the requester of *this* call.

    A cached list belongs to whoever asked first; handing it out untouched
    credited the wrong person on the now-playing card.
    """
    user_id, name = requester
    if not user_id and not name:
        return list(tracks)
    out: list[Track] = []
    for track in tracks:
        copy = dataclasses.replace(track, requested_by=user_id, requested_name=name)
        out.append(copy)
    return out


def _merge(primary: list[Track], secondary: list[Track]) -> list[Track]:
    """Both lanes, primary first, each song once."""
    out: list[Track] = []
    seen: set[str] = set()
    for track in [*primary, *secondary]:
        key = f"{track.source}:{track.id}"
        if key in seen:
            continue
        seen.add(key)
        out.append(track)
    return out


_URL_RE = re.compile(r"^https?://", re.I)
_YT_ID_RE = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/|/live/)([\w-]{11})")
_LIST_RE = re.compile(r"[?&]list=([\w-]+)")


class _Capture:
    """A yt-dlp logger that remembers the last thing it complained about.

    One instance per extraction: this runs inside a worker thread and several
    resolves overlap, so the state must not be shared.
    """

    def __init__(self) -> None:
        self.last_error = ""
        self.verbose = False

    def _remember(self, message: Any, *args: Any) -> None:
        try:
            text = str(message) % args if args else str(message)
        except Exception:  # pragma: no cover - odd format strings
            text = f"{message} {args}"
        if text.startswith("[debug]"):
            return
        self.last_error = text.strip()[:400]

    def debug(self, message: Any, *args: Any) -> None:
        if self.verbose:
            logger.debug("yt-dlp: %s", message)

    def info(self, message: Any, *args: Any) -> None:
        if self.verbose:
            logger.debug("yt-dlp: %s", message)

    def warning(self, message: Any, *args: Any) -> None:
        self._remember(message, *args)

    def error(self, message: Any, *args: Any) -> None:
        self._remember(message, *args)


# The reasons worth explaining, most specific first: what YouTube (or the host)
# said → what it means → what actually fixes it. Anything unmatched keeps the
# original sentence, because a wrong explanation is worse than a raw one.
_WHY: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("confirm you're not a bot", "confirm you’re not a bot", "not a bot", "sign in to confirm"),
        "YouTube thinks this server is a bot",
        "install curl_cffi (browser impersonation, on by default), set COOKIES_FILE, "
        "or self-host Cobalt (COBALT_URLS)",
    ),
    (
        ("age-restricted", "age restricted", "confirm your age", "inappropriate for some users"),
        "this video is age-restricted",
        "set COOKIES_FILE with a signed-in browser's cookies — no mirror can bypass this one",
    ),
    (
        ("private video", "this video is private"),
        "the video is private",
        "ask the owner to make it public — no resolver can see it",
    ),
    (
        ("members-only", "join this channel", "members only"),
        "the video is members-only",
        "it needs a channel membership — play something else",
    ),
    (
        ("not available in your country", "geo", "blocked it in your country", "region"),
        "the video is geo-blocked for this server",
        "set PROXY to a server in an allowed country, or pick another upload",
    ),
    (
        ("video unavailable", "this video is unavailable", "has been removed", "no longer available"),
        "the video is gone",
        "pick another result — the uploader deleted or privated it",
    ),
    (
        ("requested format is not available",),
        "the format we asked for does not exist for this video",
        "that is a selector problem, not your IP — /sources shows which clients still offer audio",
    ),
    (
        ("http error 429", "too many requests", "rate limit"),
        "YouTube is rate-limiting this server",
        "wait a minute, or self-host Cobalt (COBALT_URLS) so public mirrors are not in the path",
    ),
    (
        ("http error 403", "403: forbidden"),
        "YouTube refused the request (403)",
        "browser impersonation is the usual fix; a self-hosted Cobalt is the reliable one",
    ),
    (
        ("unable to download api page", "tls/ssl", "connection reset", "timed out", "getaddrinfo"),
        "this server cannot reach YouTube",
        "check egress/DNS or set PROXY — nothing else in the bot can help until it can",
    ),
    (
        ("premieres in", "will begin", "live event"),
        "this is a premiere or a live event",
        "it cannot be streamed until it starts",
    ),
)


def explain(reason: str) -> tuple[str, str]:
    """(what it means, what to do) for a raw yt-dlp / mirror message."""
    text = (reason or "").lower()
    for needles, meaning, fix in _WHY:
        if any(needle in text for needle in needles):
            return meaning, fix
    return "", ""


def _explain(reason: str, *, target: str = "") -> str:
    """A failure sentence a person can act on, built from yt-dlp's own words."""
    raw = (reason or "").strip()
    if raw.startswith("ERROR:"):
        raw = raw[len("ERROR:"):].strip()
    if raw.startswith("[youtube]"):
        raw = raw[len("[youtube]"):].strip()
    meaning, fix = explain(raw)
    if not raw:
        return (
            "YouTube returned no information for this link. That is usually this "
            "server's IP being refused — see /sources."
        )
    if meaning:
        return f"{meaning}: {raw[:160]} → {fix}"
    # Unrecognised wording still gets somewhere to go: /sources names the tier
    # that refused and the reason, which is what a screenshot cannot do.
    return f"{raw[:200]} → run /sources to see which resolver is refusing, and why"


_SLOT: tuple[asyncio.AbstractEventLoop, asyncio.Semaphore] | None = None


def _extract_slot(limit: int = 2) -> asyncio.Semaphore:
    """A process-wide semaphore bound to the loop that is running now."""
    global _SLOT
    loop = asyncio.get_running_loop()
    if _SLOT is None or _SLOT[0] is not loop or _SLOT[1]._value > max(1, limit):
        _SLOT = (loop, asyncio.Semaphore(max(1, limit)))
    return _SLOT[1]


def _client_source(client: str | None) -> str:
    """Scoreboard key for a yt-dlp player client."""
    return f"yt-dlp:{client or 'default'}"


class MediaError(RuntimeError):
    """Raised when a search / extraction fails in a user-presentable way."""


# Shown when YouTube refuses this server rather than this video. It is the one
# failure an operator can fix in a minute, so it says what to do.
FAILURE_HINT = (
    "YouTube is refusing this server's IP — set COOKIES_FILE (a cookies.txt from a "
    "logged-in browser) or keep STREAM_FALLBACK=on, then try again"
)


MIME_BY_EXT = {
    "m4a": "audio/mp4",
    "mp4": "audio/mp4",
    "webm": "audio/webm",
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "ogg": "audio/ogg",
    "aac": "audio/aac",
    "wav": "audio/wav",
}


@dataclass
class StreamInfo:
    """Everything a proxy needs: the URL, the headers it was minted for, mime."""

    url: str
    is_live: bool = False
    expires_at: float = 0.0
    headers: dict[str, str] = field(default_factory=dict)
    ext: str = ""
    mime: str = "audio/mp4"
    title: str = ""
    # Which engine actually serves these bytes. Empty means YouTube, or "the
    # answer predates this field"; a substitution names its catalogue so the app
    # and the logs can say where the song came from.
    source: str = ""


#: Words that say *how* to listen, not *what* to listen to. They are dropped
#: before a query is compared with a result, so "/play believer song" still
#: matches "Believer" with full confidence.
_QUERY_NOISE = {
    "song", "songs", "music", "track", "audio", "video", "official", "full",
    "the", "and", "by", "of", "an", "for", "me", "please", "play",
    "youtube", "yt", "hd", "hq", "lyrics", "lyric", "new", "latest", "best",
}


def _match_words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(word) > 1 and word not in _QUERY_NOISE
    }


def _token_hits(wanted: set[str], found: set[str]) -> set[str]:
    """Which words of *wanted* the *found* words cover — allowing one typo.

    People type an artist's name from memory, once: "wrong cheris grey" is
    "Wrong" by **Chris Grey**, and "let the world burn" is his song too. Exact
    word overlap turned every misspelling into "No results", even when YouTube
    and the catalogues had the song in the very first row. Two words count as
    the same when they start alike and are at least 78% similar ("cheris" vs
    "chris" is 0.83), which tolerates a wrong vowel without letting "love"
    match "live".
    """
    hits = wanted & found
    if len(hits) == len(wanted) or not found:
        return hits
    comparable = [word for word in found if len(word) >= 4]
    for want in wanted - hits:
        if len(want) < 4:
            continue
        for have in comparable:
            if want[0] != have[0]:
                continue
            if SequenceMatcher(None, want, have).ratio() >= 0.78:
                hits.add(want)
                break
    return hits


def match_confidence(query: str, track) -> float:
    """How sure we are that *track* is the song someone typed — 0.0 … 1.0.

    Play bots split into two camps: one plays the first search hit and is wrong
    often, the other always shows a list and costs a tap every single time.
    This number lets VYRON do both — play immediately when the match is
    obvious, show the picker when it is not.

    Coverage of the *query* is what matters (did every word they asked for
    appear?), with the artist counting for extra, because "kesariya arijit"
    matching an upload by "Arijit Singh - Topic" is a far stronger signal than
    the same words appearing in some random title.
    """
    wanted = _match_words(query)
    if not wanted:
        return 0.0
    title_words = _match_words(getattr(track, "title", "") or "")
    uploader_words = _match_words(getattr(track, "uploader", "") or "")
    covered = _token_hits(wanted, title_words | uploader_words)
    if not covered:
        return 0.0
    score = len(covered) / len(wanted)
    artist_hits = _token_hits(wanted, uploader_words)
    if artist_hits:
        score = min(1.0, score + 0.15 * len(artist_hits) / len(wanted))
    # A 20-second Short is never "the song", however well the words match.
    seconds = int(getattr(track, "duration", 0) or 0)
    if 0 < seconds < 30:
        return 0.0
    # Every word has to land: a half match is exactly the case where a human
    # should choose.
    full = score if covered == wanted else score * 0.6
    # …and a result that is a *different thing* than what was asked for is not
    # a match at all, however well the words line up: nobody typing "believer"
    # wants the nightcore cover or the ten-hour loop.
    query_low, title_low = query.lower(), str(getattr(track, "title", "")).lower()
    for variant in (
        "slowed", "reverb", "nightcore", "8d", "karaoke", "instrumental",
        "cover", "remix", "reaction", "1 hour", "10 hours", "loop", "sped up",
    ):
        if variant in title_low and variant not in query_low:
            return min(full, 0.4)
    return full


def is_confident_match(query: str, track, *, floor: float = 0.75) -> bool:
    """True when playing *track* without asking is the right call."""
    return match_confidence(query, track) >= floor


def looks_like_url(text: str) -> bool:
    return bool(_URL_RE.match((text or "").strip()))


def youtube_id(text: str) -> str | None:
    match = _YT_ID_RE.search(text or "")
    return match.group(1) if match else None


# Bracketed noise that adds nothing to a search: "(Official Video)", "[4K]".
_NOISE_RE = re.compile(r"[([{][^)\]}]*[)\]}]")
_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def _fold(text: str) -> str:
    """Strip accents, so "Kesariyā" and "Kesariya" are the same word."""
    import unicodedata

    return "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )


def relax_query(query: str) -> str:
    """A second, looser spelling of *query* — used only when the first pass is empty.

    People type songs the way they say them: "kesariyaa", "believerr",
    "Kesariyā", "Tum Hi Ho - official video". None of those are typos YouTube
    can forgive, and every one of them is a dead end on the first attempt. This
    does the three harmless fixes — drop accents, drop bracketed credits, collapse
    doubled letters — and leaves everything else (including a real word list)
    untouched, because mangling a valid query is worse than not relaxing it.
    """
    text = _fold(_NOISE_RE.sub(" ", query or ""))
    text = _PUNCT_RE.sub(" ", text)
    words = []
    for word in text.split():
        # A held final letter is the common typo ("Kesariyaa", "believerr",
        # "helloo"). Squeezing any doubled letter instead would turn "good"
        # into "god", so the rule stays on the end of the word.
        squeezed = re.sub(r"([^\W\d_])\1+$", r"\1", word) if len(word) >= 5 else word
        words.append(squeezed)
    relaxed = " ".join(words).strip()
    return relaxed if relaxed and relaxed.lower() != (query or "").strip().lower() else ""


_warned_impersonate = False


def impersonate_target(settings: Any):
    """A ready ``ImpersonateTarget``, or ``""`` when unavailable.

    yt-dlp wants the *object*, not the string (the CLI parses it for you).
    Requires curl_cffi — without it the option is skipped, never fatal.

    Lives at module level because the *downloader* needs it too: metadata was
    fetched as Chrome while the media was fetched as a bare `aiohttp`, which is
    precisely the difference YouTube looks at when it decides to refuse a
    download that had already been named successfully.
    """
    global _warned_impersonate
    requested = (getattr(settings, "impersonate", "") or "").strip()
    if requested.lower() in {"", "off", "none", "0", "false"}:
        return ""
    try:
        import curl_cffi  # noqa: F401  (yt-dlp needs the module, not the API)
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except Exception:
        if not _warned_impersonate:
            _warned_impersonate = True
            logger.info(
                "browser impersonation is off: `pip install curl_cffi` enables it "
                "(it is the best no-cookie fix for a datacenter IP)"
            )
        return ""
    try:
        return ImpersonateTarget.from_str(requested or "chrome")
    except Exception as exc:  # an unknown target must not break playback
        logger.info("ignoring IMPERSONATE=%s (%s)", requested, exc)
        return ""


def _materialise_cookies(settings: Any) -> str:
    """Turn `YOUTUBE_COOKIES` (env text) into the cookie file yt-dlp wants.

    A datacenter IP is the usual reason YouTube answers "confirm you're not a
    bot"; the fix is an account's cookies. Uploading a file is awkward on
    Render, so pasting the Netscape-format text into an env var is supported and
    written to disk here (0600, outside the repo).
    """
    text = (getattr(settings, "cookies_text", "") or "").strip()
    path = getattr(settings, "cookies_file", "") or ""
    if not text:
        return path
    if path and Path(path).is_file():
        return path
    target = Path(path) if path else Path(getattr(settings, "data_dir", ".")) / "cookies.txt"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        literal = text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
        target.write_text(literal if literal.endswith("\n") else literal + "\n", encoding="utf-8")
        target.chmod(0o600)
        settings.cookies_file = str(target)
        logger.info("wrote YOUTUBE_COOKIES to %s", target)
        return str(target)
    except Exception as exc:  # pragma: no cover - a bad cookie never blocks boot
        logger.warning("could not write the YouTube cookies: %s", exc)
        return path


class YouTube:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        _materialise_cookies(settings)
        self._stream_cache: dict[str, StreamInfo] = {}
        # One resolve per track at a time: the app asks for a stream and starts
        # playback at the same moment, and doing the whole client ladder twice
        # is how a 12-second failure became a 45-second one.
        self._inflight: dict[str, asyncio.Task[StreamInfo]] = {}
        # A track that just failed will fail again for a while. Remember it, so
        # the next tap answers instantly instead of grinding the ladder again.
        self._failures: dict[str, float] = {}
        # …and what to say about it: the classified reason beats a generic hint
        self._failure_reasons: dict[str, str] = {}
        # the player client that last produced a playable URL (None = yt-dlp default)
        self._client_hint: str | None = None
        self._warned_impersonate = False
        # When YouTube refuses the *server* (not one video), no client ladder
        # will help: "Failed to extract any player response" from two different
        # clients in a row means the IP is walled. Remember that for a while so
        # playback goes straight to the substitution tier instead of burning
        # twenty seconds per tap proving the same thing again.
        self._wall_until = 0.0
        self._wall_logged = False

    # ── yt-dlp plumbing ────────────────────────────────────────────────────
    def _opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "geo_bypass": True,
            "nocheckcertificate": True,
            "ignoreerrors": True,
            "extractor_retries": 2,
            "socket_timeout": 15,
            "retries": 2,
        }
        # `cookies.path()` is the refreshed jar when COOKIES_URL is set, and
        # the operator's own file otherwise — one place decides, so the
        # resolver and the downloader can never disagree about who is signed in.
        from vyron.core import cookies

        cookiefile = cookies.path() or self.settings.cookies_file
        if cookiefile:
            opts["cookiefile"] = cookiefile
        if self.settings.proxy:
            opts["proxy"] = self.settings.proxy
        if self.settings.ytdlp_args:
            opts.update(self._parse_ytdlp_args(self.settings.ytdlp_args))
        # The single most effective no-cookie fix for a datacenter IP: make the
        # HTTP client *look* like Chrome (TLS/JA3 fingerprint, header order and
        # HTTP/2 settings). yt-dlp does this through curl_cffi, which is why it
        # is in requirements.txt; without the module the option is skipped
        # instead of failing the download.
        target = self._impersonate_target()
        if target:
            opts.setdefault("impersonate", target)
        # `extra` always wins, but extractor_args are merged key-by-key so a
        # client passed by the ladder does not silently drop the operator's
        # own extractor tuning (and vice versa).
        for key, value in extra.items():
            if key == "extractor_args" and isinstance(opts.get(key), dict):
                merged = {name: dict(args) for name, args in opts[key].items()}
                for name, args in value.items():
                    bucket = merged.setdefault(name, {})
                    for flag, setting in args.items():
                        if flag == "player_client":
                            # the ladder's client goes first, then whatever the
                            # operator configured, de-duplicated
                            first = setting if isinstance(setting, list) else [setting]
                            rest = bucket.get(flag) or []
                            rest = rest if isinstance(rest, list) else [rest]
                            bucket[flag] = list(dict.fromkeys([*first, *rest]))
                        else:
                            bucket[flag] = setting
                opts[key] = merged
            else:
                opts[key] = value
        return opts

    @staticmethod
    def _parse_ytdlp_args(raw: str) -> dict[str, Any]:
        """Turn ``YTDLP_ARGS`` into yt-dlp Python options.

        `--extractor-args youtube:player_client=android` is the important one
        for streaming, and it has to become a nested dict — the CLI string form
        is not understood by ``YoutubeDL`` when passed through `params`.
        """
        try:
            tokens = shlex.split(raw)
        except ValueError:
            return {}
        parsed: dict[str, Any] = {}
        index = 0
        while index < len(tokens):
            token = tokens[index]
            index += 1
            if not token.startswith("--"):
                continue
            name, inline = token[2:], None
            if "=" in name:
                name, inline = name.split("=", 1)
            value = inline
            if value is None and index < len(tokens) and not tokens[index].startswith("--"):
                value = tokens[index]
                index += 1
            key = name.strip().replace("-", "_")
            if key == "extractor_args" and value:
                for chunk in value.split(";"):
                    if ":" not in chunk:
                        continue
                    extractor, args = chunk.split(":", 1)
                    bucket = parsed.setdefault("extractor_args", {}).setdefault(
                        extractor.strip(), {}
                    )
                    for pair in args.split(";"):
                        if "=" not in pair:
                            continue
                        flag, setting = pair.split("=", 1)
                        bucket.setdefault(flag.strip(), []).extend(
                            part for part in setting.split(",") if part
                        )
            elif value is not None:
                parsed[key] = value
        return parsed

    def _extract(self, target: str, **extra: Any) -> dict[str, Any]:
        """One yt-dlp extraction, with the *reason* kept when it fails.

        `ignoreerrors` is on (a playlist with one dead video must still yield
        the rest), which means a failure returns ``None`` instead of raising —
        and the reason only exists as a log line. Handing yt-dlp our own logger
        recovers it, so the user is told "Sign in to confirm you're not a bot"
        instead of "nothing could be extracted".
        """
        capture = _Capture()
        options = {"logger": capture}
        options.update(self._opts(**extra))
        capture.verbose = bool(options.get("verbose"))
        with yt_dlp.YoutubeDL(options) as ydl:
            try:
                info = ydl.extract_info(target, download=False)
            except Exception as exc:  # a real raise (network, parse) is better than None
                raise MediaError(_explain(f"{type(exc).__name__}: {exc}", target=target)) from exc
        if not info:
            raise MediaError(_explain(capture.last_error, target=target))
        return info

    async def _async_extract(self, target: str, **extra: Any) -> dict[str, Any]:
        # yt-dlp is CPU-bound Python: on a small host, ten "parallel" searches
        # starve the event loop and every web request in the same second looks
        # slow. Two extractions at a time keeps the bot responsive.
        try:
            async with _extract_slot(getattr(self.settings, "extract_concurrency", 2)):
                return await asyncio.to_thread(self._extract, target, **extra)
        except MediaError:
            raise
        except Exception as exc:  # yt-dlp raises a zoo of exception types
            logger.info("extract failed for %s: %s", target, exc)
            raise MediaError(str(exc)) from exc

    # ── mapping ────────────────────────────────────────────────────────────
    def _track_from_entry(self, entry: dict[str, Any], *, requester: tuple[int, str] = (0, "")) -> Track | None:
        if not entry:
            return None
        vid = str(entry.get("id") or "")
        if not vid:
            return None
        thumb = entry.get("thumbnail")
        if not thumb:
            thumbs = entry.get("thumbnails") or []
            if thumbs:
                thumb = thumbs[-1].get("url")
        if not thumb and _YT_ID_RE.match(f"v={vid}"):
            thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
        return Track(
            id=vid,
            title=str(entry.get("title") or "Unknown title"),
            duration=parse_duration(entry.get("duration")),
            url=entry.get("webpage_url") or entry.get("url") or f"https://youtu.be/{vid}",
            uploader=str(entry.get("uploader") or entry.get("channel") or ""),
            thumbnail=thumb,
            # Auto-detect the media kind. Almost every YouTube item has a video
            # stream *and* an audio stream, so "has video" is not the question:
            # what matters is whether there is anything to listen to. A source
            # is treated as video only when it has no audio at all (a silent
            # clip, a video-only format, a raw .mp4 link) or the extractor says
            # so outright. Flat search rows carry neither field and stay audio.
            is_video=bool(
                entry.get("is_video", False)
                or (
                    str(entry.get("vcodec") or "none") not in {"none", "None"}
                    and str(entry.get("acodec") or "none") in {"none", "None"}
                )
            ),
            is_live=bool(entry.get("is_live")) or entry.get("live_status") == "is_live",
            source=str(entry.get("extractor_key") or entry.get("ie_key") or "youtube").lower(),
            requested_by=requester[0],
            requested_name=requester[1],
            filesize=int(entry.get("filesize") or entry.get("filesize_approx") or 0),
            views=int(entry.get("view_count") or 0),
        )

    # ── public API ─────────────────────────────────────────────────────────
    async def search(
        self,
        query: str,
        limit: int | None = None,
        requester: tuple[int, str] = (0, ""),
        *,
        relaxed: bool = False,
    ) -> list[Track]:
        """Search YouTube and return up to *limit* playable tracks.

        When nothing comes back, one relaxed retry runs (accents, bracketed
        credits, a held final letter). *relaxed* marks that retry so a genuine
        miss still raises instead of looping.
        """
        query = (query or "").strip()
        if not query:
            return []
        count = limit or self.settings.search_results
        # Over-fetch so dedupe/filtering still leaves a full page of results.
        fetch = count if count <= 2 else min(40, count * 2)

        cached = _cache_get(query, count)
        if cached:
            return _stamp(cached, requester)

        tracks: list[Track] = []
        # The two halves of a search, started together. The catalogues answer
        # in well under a second and hand out real audio; YouTube is either
        # fast and unplayable (walled) or twenty seconds of nothing. Racing
        # them is the difference between a picker in one second and a picker
        # after the listener has given up.
        alt_task = asyncio.create_task(
            alternate.search_all(query, count, settings=self.settings),
            name="search:catalogues",
        )
        # YouTube is asked *every* time, wall or no wall. The wall says its
        # streams are refused from this IP; it does not say `ytsearch` cannot
        # name a song, and the stream is fetched by the substitution tier
        # anyway. Skipping it turned one failed stream into a server that
        # answered "No results" to every text query for the next few hours.
        yt_task = asyncio.create_task(
            self._search_youtube(query, fetch, count, requester),
            name="search:youtube",
        )
        try:
            tracks = await self._race(alt_task, yt_task, count, query)
        finally:
            for task in (alt_task, yt_task):
                if task is not None and not task.done():
                    task.cancel()
        if not tracks and not relaxed:
            second = relax_query(query)
            if second:
                logger.info("nothing for %r — retrying as %r", query, second)
                again = await self.search(second, limit=limit, requester=requester, relaxed=True)
                if again:
                    return again
        if not tracks:
            # One last, unguarded pass over the catalogues before giving up: the
            # first round may have lost a race against a slow catalogue, and a
            # second try costs a second while a false "No results" costs the
            # listener their trust in the bot.
            tracks = await alternate.search_all(
                query, count, settings=self.settings, budget=SECOND_CHANCE
            )
        if not tracks:
            raise MediaError(
                "nothing came back for that — the sources may be throttling this "
                "server. Try again in a moment, or send a link."
            )
        ranked = self.rank(query, tracks)[:count]
        _cache_put(query, count, ranked)
        return _stamp(ranked, requester)

    # ── the two engines, and the race between them ─────────────────────────
    async def _search_youtube(
        self,
        query: str,
        fetch: int,
        count: int,
        requester: tuple[int, str],
    ) -> list[Track]:
        """Every YouTube lane we have, and no lane can cancel another.

        In order of freshness: YouTube Music (songs, not "Official Video [4K]"),
        plain `ytsearch`, the public Invidious/Piped instances, and finally the
        stream-source registry. Each one is optional and each one fails on its
        own — a single refused extractor used to throw away the results of the
        lanes that *had* answered, because the exception left this function.
        """
        tracks: list[Track] = []
        # The instance search is started first: it is the lane that still works
        # when YouTube's own endpoints treat this IP as a bot.
        instance_task = asyncio.create_task(
            self._instance_search(query, count + 2, requester), name="search:instances"
        )
        # YT Music and a flat `ytsearch` are two different endpoints answering
        # the same question; asked one after the other, the second one's
        # latency was added to the first's for no reason.
        flat_task = asyncio.create_task(
            self._async_extract(f"ytsearch{fetch}:{query}", extract_flat="in_playlist"),
            name="search:ytsearch",
        )
        try:
            try:
                meta = await self._ytmusic_search(query, fetch)
            except Exception as exc:
                logger.info("YouTube Music search failed for %r: %s", query, exc)
                meta = []
            for entry in meta or []:
                track = self._track_from_entry(entry, requester=requester)
                if track:
                    tracks.append(track)

            if len(tracks) < count:
                try:
                    info = await flat_task
                except Exception as exc:
                    logger.info("ytsearch failed for %r: %s", query, exc)
                    info = {}
                for entry in (info or {}).get("entries") or []:
                    track = self._track_from_entry(entry, requester=requester)
                    if track:
                        tracks.append(track)

            if len(tracks) < count:
                try:
                    tracks.extend(await asyncio.wait_for(instance_task, YOUTUBE_DEADLINE))
                except Exception as exc:
                    logger.info("instance search gave nothing for %r: %s", query, exc)
        finally:
            for task in (instance_task, flat_task):
                if not task.done():
                    task.cancel()

        if not tracks:
            try:
                for track in await sources.fallback_search(query, count, settings=self.settings):
                    track.requested_by, track.requested_name = requester
                    tracks.append(track)
            except Exception as exc:
                logger.info("source registry search failed for %r: %s", query, exc)
        return tracks

    async def _instance_search(
        self, query: str, limit: int, requester: tuple[int, str]
    ) -> list[Track]:
        """Invidious / Piped keyword search — the wall-proof lane."""
        try:
            from vyron.core.public_streams import get_public_streams

            rows = await get_public_streams(self.settings).search(query, limit)
        except Exception as exc:  # pragma: no cover - network variance
            logger.info("public instance search failed for %r: %s", query, exc)
            return []
        tracks: list[Track] = []
        for row in rows:
            tracks.append(
                Track(
                    id=row["id"],
                    title=row["title"],
                    duration=row.get("duration") or 0,
                    uploader=row.get("uploader") or "",
                    thumbnail=row.get("thumbnail"),
                    views=int(row.get("views") or 0),
                    source="youtube",
                    requested_by=requester[0],
                    requested_name=requester[1],
                )
            )
        if tracks:
            logger.info("public instances named %d result(s) for %r", len(tracks), query)
        return tracks

    async def _race(
        self,
        alt_task: "asyncio.Task[list[Track]]",
        yt_task: "asyncio.Task[list[Track]] | None",
        count: int,
        query: str,
    ) -> list[Track]:
        """Whichever engine can fill the page first wins.

        The catalogues get ``CATALOGUE_GRACE`` seconds of exclusivity because
        their results actually play on a datacenter IP. If they come back thin,
        YouTube gets the rest of the budget and the two are merged — a slow but
        real answer still beats an empty one.
        """
        need = max(2, count // 2)
        # While YouTube is refusing this server, nothing it *names* can be
        # streamed from here: the substitution tier fetches the audio, and the
        # catalogue lane is the one whose results actually play. Waiting the
        # full deadline for the other lane only made the picker slower.
        walled = self.walled()
        yt_deadline = 2.5 if walled else YOUTUBE_DEADLINE
        fast: list[Track] = []
        try:
            fast = await asyncio.wait_for(asyncio.shield(alt_task), CATALOGUE_GRACE)
        except asyncio.TimeoutError:
            pass
        except Exception as exc:                       # an engine is never fatal
            logger.info("catalogue search failed for %r: %s", query, exc)

        # A catalogue answers *something* for almost any string — including,
        # famously, the bot's own ".play Wrong", which came back as five songs
        # with "play" in the title. Only results that share a word with the
        # query count towards "the page is full"; the rest are still offered,
        # ranked last, if nothing better arrives.
        relevant = self._relevant(query, fast)
        if fast and walled:
            # The wall is about *streams*, not about naming a song: YouTube can
            # still find songs the catalogues miss, so it gets a glance — not
            # the full deadline it used to get.
            slow: list[Track] = []
            started = time.monotonic()
            if yt_task is not None:
                try:
                    slow = await asyncio.wait_for(asyncio.shield(yt_task), WALLED_GLANCE)
                except Exception:  # a timeout included: its names are a bonus
                    slow = []
            elapsed = time.monotonic() - started
            logger.info(
                "%d result(s) for %r from %s · YouTube is walled, its names took %.1fs (+%d)",
                len(fast),
                query,
                alternate.describe(self.settings),
                elapsed,
                len(slow),
            )
            return _merge(relevant, [*(t for t in fast if t not in relevant), *slow])
        if len(relevant) >= need or yt_task is None:
            if fast:
                logger.info(
                    "%d result(s) for %r from %s in the catalogue lane (%d on topic)",
                    len(fast),
                    query,
                    alternate.describe(self.settings),
                    len(relevant),
                )
            return _merge(relevant, [track for track in fast if track not in relevant])

        if not alt_task.done():
            # Still worth waiting for: it is the lane that can actually play.
            try:
                fast = await asyncio.wait_for(alt_task, yt_deadline)
            except (asyncio.TimeoutError, Exception):
                pass

        try:
            slow = await asyncio.wait_for(asyncio.shield(yt_task), yt_deadline)
        except asyncio.TimeoutError:
            slow = []
            logger.info("YouTube search for %r did not answer in %.1fs", query, yt_deadline)
        except Exception as exc:
            slow = []
            logger.info("YouTube search failed for %r: %s", query, exc)
        return _merge(fast, slow)

    def _relevant(self, query: str, tracks: list[Track]) -> list[Track]:
        """The results that have something to do with what was typed.

        Word overlap against the title *and* the artist, because a cover or a
        remix still names the song in its title while the uploader is somebody
        else entirely.
        """
        wanted = self._words(query)
        if not wanted:
            return list(tracks)
        picked: list[Track] = []
        for track in tracks:
            found = self._words(track.title) | self._words(track.uploader or "")
            if _token_hits(wanted, found):
                picked.append(track)
        return picked

    def _catalogue_enabled(self) -> bool:
        """`MUSIC_SOURCES=off` keeps everything on YouTube-only behaviour."""
        raw = (getattr(self.settings, "music_sources", "") or "").strip().lower()
        return raw not in {"off", "none", "0", "false", "no"}

    async def _ytmusic_search(self, query: str, limit: int) -> list[dict]:
        """YouTube Music results, or ``[]`` when disabled/unavailable."""
        if not getattr(self.settings, "ytmusic_search", True):
            return []
        if not ytmusic.available():
            return []
        return await ytmusic.search(query, limit=limit)

    # ── ranking ────────────────────────────────────────────────────────────
    @staticmethod
    def _words(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 1}

    def rank(self, query: str, tracks: list[Track]) -> list[Track]:
        """Order results the way a person would: relevance, then playability, then reach.

        YouTube's own order is good enough for the top hit and noisy afterwards —
        duplicate uploads, 20-second Shorts and hour-long "1 hour loop" edits all
        creep in. This keeps the top hit honest and pushes the junk down.
        """
        wanted = self._words(query)
        seen_ids: set[str] = set()
        # (score, youtube order, track, dedupe key, artist) — the artist travels
        # with the row: it used to be read from the loop variable, so the dedupe
        # pass compared every track against the *last* result's artist.
        scored: list[tuple[float, int, Track, str, str]] = []

        for position, track in enumerate(tracks):
            key = f"{track.source}:{track.id}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            # Dedupe by song, not by upload: three channels posting "Kesariya"
            # with different brackets are the same song to a listener.
            normalised = " ".join(sorted(self._words(track.title)))
            artist = " ".join(sorted(self._words(track.uploader or "")))[:24]
            song_key = normalised

            score = 0.0
            if wanted:
                title_words = self._words(track.title)
                uploader_words = self._words(track.uploader or "")
                overlap = len(_token_hits(wanted, title_words)) / len(wanted)
                score += overlap * 4.0
                if uploader_words and _token_hits(wanted, uploader_words):
                    score += 0.8
                # and the artist's name in the title is a strong signal too
                if uploader_words and len(_token_hits(wanted, uploader_words)) >= 2:
                    score += 0.6

            # Playable-length preference: skip 20s Shorts, demote 2h "loops".
            seconds = int(track.duration or 0)
            if 40 <= seconds <= 3600:
                score += 0.9
            elif 0 < seconds < 40:
                score -= 1.6
            elif seconds > 5400:
                score -= 0.7
            if not seconds:
                score -= 0.3

            title_low = track.title.lower()
            query_low = query.lower()
            for noise in ("slowed + reverb", "1 hour", "10 hours", "nightcore", "8d audio"):
                if noise in title_low and noise not in query_low:
                    score -= 0.6

            # The upload that is the actual recording beats a re-upload of it.
            # "Artist - Topic" is YouTube's auto-generated label for a label's
            # own audio, which is the single most reliable "this is the song"
            # signal available without an extra API call.
            uploader_low = (track.uploader or "").lower()
            if uploader_low.endswith("- topic"):
                score += 0.9
            elif "official audio" in title_low:
                score += 0.7
            elif "official video" in title_low or "official music video" in title_low:
                score += 0.45
            elif "lyric" in title_low:
                score += 0.3
            # …and a cover, a karaoke track, an instrumental or a reaction is
            # not the song, unless that is exactly what was asked for.
            for wrong in ("cover", "karaoke", "instrumental", "reaction", "tutorial"):
                if wrong in title_low and wrong not in query_low:
                    score -= 0.8
            if ("live" in title_low) and "live" not in query_low:
                score -= 0.35
            if track.views:
                score += min(1.4, (track.views / 2_000_000) ** 0.5)

            # Tiny nudge so a clean tie keeps YouTube's ordering.
            score -= position * 0.01
            scored.append((score, position, track, song_key, artist))

        # Sort first, *then* drop duplicates: the listener wants the best copy
        # of a song, not whichever upload YouTube happened to list first.
        scored.sort(key=lambda item: (-item[0], item[1]))
        kept: list[Track] = []
        seen_versions: dict[str, list[tuple[str, int]]] = {}
        for _score, _position, track, song_key, artist in scored:
            if song_key:
                # Two uploads of the same title are the same song when they are
                # by the same artist or run for the same length. A cover keeps a
                # different artist *and* a different length, so it survives.
                same = False
                for artist_seen, duration_seen in seen_versions.get(song_key, []):
                    if artist_seen and artist_seen == artist:
                        same = True
                        break
                    if duration_seen and track.duration and abs(duration_seen - track.duration) <= 3:
                        same = True
                        break
                if same:
                    continue
                seen_versions.setdefault(song_key, []).append((artist, int(track.duration or 0)))
            kept.append(track)
        return kept

    async def resolve(self, query: str, requester: tuple[int, str] = (0, "")) -> Track:
        """Turn a URL *or* a free-text query into a single playable track."""
        query = (query or "").strip()
        if not query:
            raise MediaError("Give me a song name, a link or reply to an audio file.")
        if query.lower().startswith(("http://", "https://")):
            from vyron.core.urlguard import BlockedURL, check_user_url

            try:
                query = await check_user_url(query, settings=self.settings)
            except BlockedURL as exc:
                raise MediaError(f"That link cannot be used: {exc}.") from exc

        # Direct-stream sources first (Audius, JioSaavn, SoundCloud, Bandcamp):
        # they hand out the audio themselves, so these links play without YouTube
        # being involved. The registry decides which of them are on.
        if looks_like_url(query):
            direct = await sources.resolve_direct(query, settings=self.settings)
            if direct is not None:
                direct.requested_by, direct.requested_name = requester
                return direct

        # A Spotify / Deezer / Apple Music link is metadata, not audio: read the
        # catalogue entry, then let the normal ladder find the song. The
        # catalogue's artwork is usually the best-looking cover, so it wins over
        # the YouTube thumbnail when we have it. (SoundCloud and Bandcamp are
        # handled above: yt-dlp extracts *those* uploads directly.)
        if self._catalogue_enabled() and metasources.is_catalogue_link(query):
            found = await self._from_catalogue(query, requester=requester)
            if found is not None:
                return found

        if looks_like_url(query):
            tried: Exception | None = None
            try:
                info = await self._async_extract(query)
            except Exception as exc:  # a walled IP raises before returning
                info = {}
                tried = exc
                self._note_wall(str(exc))
            if info.get("_type") == "playlist" and info.get("entries"):
                entries = [e for e in info["entries"] if e]
                if not entries:
                    raise MediaError("That playlist is empty or private.")
                info = entries[0]
            track = self._track_from_entry(info, requester=requester)
            if track:
                return track
            # A bare link and no metadata: the mirror knows the title, and the
            # title is all the substitution tier needs to find the same song on
            # a catalogue that will actually play it.
            stub = await self._track_from_public_meta(
                youtube_id(query), requester=requester
            )
            if stub is not None:
                return stub
            if tried is not None:
                raise MediaError(_explain(str(tried), target=query)) from tried
            raise MediaError("That link did not resolve to a playable track.")

        results = await self.search(query, limit=1, requester=requester)
        return results[0]

    async def _track_from_public_meta(
        self, video_id: str | None, *, requester: tuple[int, str] = (0, "")
    ) -> Track | None:
        """A YouTube id → a Track, using a mirror for the title.

        Used when yt-dlp cannot read the video at all (YT-DLP's own wall): the
        id still identifies the song, and everything downstream only needs the
        title, artist and length to play the same song from elsewhere.
        """
        if not video_id:
            return None
        if not getattr(self.settings, "stream_fallback", True):
            return None
        try:
            from vyron.core.public_streams import get_public_streams

            meta = await get_public_streams(self.settings).meta(video_id)
        except Exception as exc:  # pragma: no cover - never fatal
            logger.info("mirror metadata failed for %s: %s", video_id, exc)
            return None
        if meta is None:
            return None
        logger.info("metadata for %s came from a mirror: %r", video_id, meta.title)
        return Track(
            id=video_id,
            title=meta.title,
            duration=meta.duration,
            url=f"https://www.youtube.com/watch?v={video_id}",
            uploader=meta.uploader,
            thumbnail=meta.thumbnail,
            source="youtube",
            requested_by=requester[0],
            requested_name=requester[1],
        )

    async def _from_catalogue(
        self, url: str, *, requester: tuple[int, str] = (0, "")
    ) -> Track | None:
        """Spotify/Deezer/Apple link → the best YouTube match (or a stream)."""
        # First ask the cross-platform matcher: if it knows the exact YouTube
        # entity this link refers to, no title ever gets guessed.
        try:
            video_id = await metasources.match(url)
        except Exception as exc:  # pragma: no cover - matcher is best-effort
            logger.debug("cross-platform match failed: %s", exc)
            video_id = ""
        if video_id:
            try:
                info = await self._async_extract(f"https://www.youtube.com/watch?v={video_id}")
                matched = self._track_from_entry(info, requester=requester)
            except Exception as exc:
                logger.info("exact match %s could not be read (%s)", video_id, exc)
                matched = None
            if matched is not None:
                matched.source = f"{metasources.detect(url).service}·yt" if metasources.detect(url) else "yt"
                return matched

        meta = await metasources.lookup(url)
        if isinstance(meta, metasources.MetaCollection):
            meta = meta.tracks[0] if meta.tracks else None
        if not isinstance(meta, metasources.MetaTrack) or not meta.title:
            return None
        try:
            results = await self.search(meta.query, limit=2, requester=requester)
        except MediaError:
            results = []
        if not results:
            # A catalogue entry we could not match on YouTube: try to stream the
            # same song from a direct source instead of failing the link.
            for track in await sources.fallback_search(
                meta.query, 1, settings=self.settings
            ):
                track.requested_by, track.requested_name = requester
                return track
            return None
        chosen = results[0]
        # Keep the catalogue's identity where it is better than YouTube's.
        if meta.artwork:
            chosen.thumbnail = meta.artwork
        if meta.artist and not chosen.uploader:
            chosen.uploader = meta.artist
        chosen.source = f"{meta.service}·youtube"
        return chosen

    async def resolve_collection(
        self,
        url: str,
        *,
        limit: int = 25,
        requester: tuple[int, str] = (0, ""),
    ) -> tuple[str, list[Track]] | None:
        """A catalogue album/playlist link → ``(title, tracks)``.

        Every entry is matched against YouTube with a bounded number of
        concurrent searches; entries that cannot be matched are skipped rather
        than failing the whole album.
        """
        if not self._catalogue_enabled():
            return None
        meta = await metasources.lookup(url)
        if not isinstance(meta, metasources.MetaCollection) or not meta.tracks:
            return None
        wanted = meta.tracks[:limit]
        semaphore = asyncio.Semaphore(3)

        async def _one(item: metasources.MetaTrack) -> Track | None:
            async with semaphore:
                try:
                    results = await self.search(item.query, limit=1, requester=requester)
                except MediaError:
                    return None
            if not results:
                return None
            track = results[0]
            if item.artwork:
                track.thumbnail = item.artwork
            track.source = f"{meta.service}·youtube"
            return track

        found = await asyncio.gather(*(_one(item) for item in wanted))
        tracks = [track for track in found if track]
        if not tracks:
            return None
        return (meta.title or meta.service.title()), tracks

    async def playlist(self, url: str, limit: int = 50) -> tuple[str, list[Track]]:
        """Load a YouTube playlist / mix.  Returns (title, tracks)."""
        info = await self._async_extract(url, extract_flat=True, noplaylist=False)
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise MediaError("That playlist is empty or private.")
        tracks = [t for t in (self._track_from_entry(e) for e in entries[:limit]) if t]
        if not tracks:
            raise MediaError("No playable items in that playlist.")
        return str(info.get("title") or "Playlist"), tracks

    async def related(self, track: Track, limit: int = 8) -> list[Track]:
        """Autoplay source: an official YouTube mix seeded by the track id."""
        if track.source.startswith("youtube") and track.id and len(track.id) == 11:
            mix_url = f"https://www.youtube.com/watch?v={track.id}&list=RD{track.id}"
            try:
                _, tracks = await self.playlist(mix_url, limit=limit + 1)
                filtered = [t for t in tracks if t.id != track.id]
                if filtered:
                    return filtered[:limit]
            except MediaError:
                pass
        query = f"{track.title} {track.uploader}".strip()
        try:
            results = await self.search(query, limit=limit + 1)
        except MediaError:
            return []
        return [t for t in results if t.id != track.id][:limit]

    async def stream_url(self, track: Track, *, video: bool = False) -> str:
        """Resolve a direct media URL suitable for ntgcalls/ffmpeg."""
        return (await self.stream_info(track, video=video)).url

    async def stream_info(
        self, track: Track, *, video: bool = False, refresh: bool = False
    ) -> StreamInfo:
        """Resolve a direct media URL *and* the headers it must be fetched with.

        YouTube answers different clients differently: `web` is the most
        accurate but the first to demand a PO token, `android_vr`/`ios`/`tv`
        often still hand out a playable URL when `web` returns 403. So the
        resolve walks a client ladder and remembers which one worked — the
        difference between "the web player plays" and "the web player spins".
        """
        key = f"{track.id}:{'v' if video else 'a'}"
        cached = self._stream_cache.get(key)
        if cached and not refresh and cached.expires_at > time.time():
            return cached

        # A JioSaavn/Audius track *is* an audio file: there is nothing to
        # extract, and running yt-dlp over it only adds a timeout.
        if track.source in sources.DIRECT_SOURCES and track.url and not video:
            direct = alternate.info_for(track)
            if direct is not None:
                self._stream_cache[key] = direct
                return direct

        if not refresh:
            blocked_until = self._failures.get(key, 0.0)
            if blocked_until > time.time():
                raise MediaError(self._failure_reasons.get(key) or FAILURE_HINT)
            running = self._inflight.get(key)
            if running is not None:
                # Share the answer instead of running the ladder again.
                return await asyncio.shield(running)

        task = asyncio.ensure_future(self._resolve_stream(track, video=video, refresh=refresh))
        if not refresh:
            self._inflight[key] = task
        try:
            return await asyncio.shield(task)
        except MediaError as exc:
            ttl = max(5, int(getattr(self.settings, "stream_failure_ttl", 60)))
            self._failures[key] = time.time() + ttl
            self._failure_reasons[key] = str(exc)
            raise
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    async def _resolve_stream(
        self, track: Track, *, video: bool = False, refresh: bool = False
    ) -> StreamInfo:
        """The actual work: cached URL → client ladder → public mirror."""
        key = f"{track.id}:{'v' if video else 'a'}"
        target = track.url or track.watch_url
        if not target:
            raise MediaError("Track has no URL to stream.")

        if video:
            height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
                self.settings.video_quality, 720
            )
            selector = (
                f"best[height<={height}][ext=mp4]/best[height<={height}]/bestvideo[height<={height}]+bestaudio/best"
            )
        else:
            selector = "bestaudio[ext=m4a]/bestaudio[acodec!=none]/best"

        # Walled: skip the ladder entirely (it cannot succeed) and go straight
        # to the copy of the song that will actually play.
        if self.walled():
            substituted = await self._substitute(track, video=False, fresh=refresh)
            if substituted is not None:
                self._stream_cache[key] = substituted
                return substituted

        last_error: Exception | None = None
        same_error = 0
        for client in self._client_ladder():
            source = _client_source(client)
            started = time.perf_counter()
            try:
                info = await self._async_extract(target, format=selector, **self._client_opts(client))
                result = self._stream_from_info(info, track, video=video, target=target)
            except Exception as exc:  # MediaError, DownloadError, KeyError…
                message = str(exc)
                HEALTH.record(source, False, error=message)
                # Two identical answers mean the client ladder is not the
                # problem (a dead video, a blocked IP). Stopping there turns a
                # six-client, 24-second stall into a two-client, 4-second one.
                same_error = same_error + 1 if last_error is not None and str(last_error) == message else 1
                last_error = exc
                self._note_wall(message)
                logger.info("resolve via %s failed for %s: %s", client, track.id, exc)
                if same_error >= 2:
                    logger.info("resolve for %s is deterministic, stopping the ladder", track.id)
                    break
                continue
            HEALTH.record(source, True, ms=(time.perf_counter() - started) * 1000)
            self.clear_wall()  # YouTube answered: stop preferring the catalogues
            self._remember_client(client)
            result.source = result.source or "youtube"
            self._stream_cache[key] = result
            self._failures.pop(key, None)
            self._failure_reasons.pop(key, None)
            return result

        # Last tier: a public Invidious/Piped mirror. yt-dlp failing is a
        # YouTube-side problem (PO token, 403, "confirm you're not a bot"), not
        # usually a track-side one, so somebody else's resolver often still has
        # a signed URL for the same video.
        fallback = await self._public_fallback(track, video=video)
        if fallback:
            self._stream_cache[key] = fallback
            return fallback

        # Last tier, and the one that fixes a walled IP: the same song from a
        # catalogue that serves its own audio. The listener asked for a song,
        # not for YouTube specifically.
        #
        # A *video* request lands here too, and deliberately gets audio: the
        # catalogues have no video, and an honest song beats a silent black
        # stream. `Player._start_stream` notices the bytes are audio and drops
        # the video flag again, so ntgcalls is never asked for a video track
        # that does not exist.
        substituted = await self._substitute(track, video=False)
        if substituted is not None:
            if video:
                logger.info(
                    "video for %s is unavailable on this host — streaming the same song as audio",
                    track.id,
                )
            self._stream_cache[key] = substituted
            return substituted

        self._stream_cache.pop(key, None)
        raw = str(last_error) if last_error else ""
        # `_explain` maps yt-dlp's own sentence onto what it means and what
        # fixes it, so the toast in the app is actionable instead of cryptic.
        raise MediaError(_explain(raw, target=track.id))

    async def _public_fallback(self, track: Track, *, video: bool = False) -> StreamInfo | None:
        """Direct URL from Invidious/Piped, or ``None`` when not configured."""
        if not getattr(self.settings, "stream_fallback", True):
            return None
        try:
            from vyron.core.public_streams import get_public_streams

            height = 0
            if video:
                height = {"360p": 360, "480p": 480, "720p": 720, "1080p": 1080}.get(
                    self.settings.video_quality, 720
                )
            direct = await get_public_streams(self.settings).resolve(track.id, height=height)
        except Exception as exc:  # pragma: no cover - never break a resolve
            logger.info("public stream fallback failed for %s: %s", track.id, exc)
            return None
        if not direct:
            return None
        logger.info("stream for %s came from %s", track.id, direct.source)
        from vyron.core.resolvers import HEALTH

        HEALTH.record(direct.source, True, ms=0)
        return StreamInfo(
            url=direct.url,
            expires_at=time.time() + self.settings.stream_cache_ttl,
            headers=dict(direct.headers),
            ext=direct.ext,
            mime=direct.mime or ("video/mp4" if video else "audio/mp4"),
            title=track.title,
            source=direct.source,
        )

    # ── stream plumbing ────────────────────────────────────────────────────
    def _impersonate_target(self):
        """A ready ``ImpersonateTarget``, or ``""`` when unavailable."""
        return impersonate_target(self.settings)

    @staticmethod
    def _client_opts(client: str | None) -> dict[str, Any]:
        if not client:
            return {}
        return {"extractor_args": {"youtube": {"player_client": [client]}}}

    # ── the IP wall ────────────────────────────────────────────────────────
    # What YouTube says when the *server* is the problem. Not per-video: two
    # different ids in the production log produce the identical sentence.
    WALL_SIGNS = (
        "failed to extract any player response",
        "sign in to confirm you",
        "not a bot",
        "confirm you're not a bot",
        "confirm your age",
        "http error 403",
        "this content isn't available, try again later",
        "the uploader has not made this video available",
    )

    def _note_wall(self, message: str) -> None:
        """Remember that YouTube is refusing this server, not just this video."""
        text = (message or "").lower()
        if not any(sign in text for sign in self.WALL_SIGNS):
            return
        window = max(30, int(getattr(self.settings, "youtube_wall_window", 900)))
        self._wall_until = time.time() + window
        if not self._wall_logged:
            self._wall_logged = True
            # An expired cookie jar is the most likely cause of this wall, so
            # re-read COOKIES_URL now instead of waiting for the next sweep.
            if str(getattr(self.settings, "cookies_url", "") or ""):
                try:
                    from vyron.core import cookies

                    asyncio.create_task(
                        cookies.refresh(self.settings, force=True),
                        name="cookies:after-wall",
                    )
                except RuntimeError:  # pragma: no cover - no running loop
                    pass
            logger.warning(
                "YouTube is refusing this server (%s) — serving %s for the next %ds",
                (message or "")[:90],
                alternate.describe(self.settings),
                window,
            )

    def stream_source(self, track: Track) -> str:
        """Which engine the last answer for *track* came from ("" if unknown)."""
        for key in (f"{track.id}:a", f"{track.id}:v"):
            info = self._stream_cache.get(key)
            if info is not None and info.expires_at > time.time():
                return info.source
        return ""

    def walled(self) -> bool:
        """True while the substitution tier should be tried first."""
        return getattr(self, "_wall_until", 0.0) > time.time()

    def wall_seconds_left(self) -> int:
        return max(0, int(self._wall_until - time.time()))

    def clear_wall(self) -> None:
        self._wall_until = 0.0
        self._wall_logged = False

    async def _substitute(
        self, track: Track, *, video: bool = False, fresh: bool = False
    ) -> StreamInfo | None:
        """The same song from a catalogue that hands out real audio.

        Video is deliberately not substituted: an audio file under a video
        request would be a silent, black video stream.
        """
        if video:
            return None
        try:
            return await alternate.stream_info(track, settings=self.settings, fresh=fresh)
        except Exception as exc:  # pragma: no cover - never break a resolve
            logger.info("substitution failed for %s: %s", track.id, exc)
            return None

    def _client_ladder(self) -> list[str | None]:
        """Player clients to try, best-known-first for this deployment.

        Order is experience, not documentation: `tv_simply` and `web_embedded`
        are the clients that still hand out a signed URL to an IP YouTube does
        not like, `android_vr`/`ios` cover the ones that need a mobile header
        set, and plain `web` is last because it is the first to demand a PO
        token. Clients in a cooldown (they failed twice in a row) are skipped
        instead of costing every track another timeout.
        """
        hint = self._client_hint
        ladder: list[str | None] = [
            None,
            "tv_simply",
            "web_embedded",
            "android_vr",
            "ios",
            "tv",
            "web_safari",
            "mweb",
        ]
        if hint:
            ladder = [hint] + [client for client in ladder if client != hint]
        return [client for client in ladder if HEALTH.available(_client_source(client))]

    def _remember_client(self, client: str | None) -> None:
        if client:
            self._client_hint = client

    def _stream_from_info(
        self, info: dict[str, Any] | None, track: Track, *, video: bool, target: str
    ) -> StreamInfo:
        if not info:
            raise MediaError("Could not resolve a stream for that track.")

        chosen: dict[str, Any] | None = info if info.get("url") else None
        url = info.get("url")
        if not url:
            candidates = [f for f in (info.get("formats") or []) if f.get("url")]
            if video:
                candidates.sort(key=lambda f: (f.get("height") or 0), reverse=True)
                progressive = [f for f in candidates if f.get("vcodec") not in (None, "none")]
                candidates = progressive or candidates
            else:
                candidates.sort(key=lambda f: (f.get("abr") or f.get("tbr") or 0), reverse=True)
                audio_only = [f for f in candidates if f.get("acodec") not in (None, "none")]
                candidates = audio_only or candidates
            if not candidates:
                raise MediaError("No downloadable formats available.")
            chosen = candidates[0]
            url = chosen["url"]

        ext = str((chosen or info).get("ext") or "").lower()
        # googlevideo URLs carry their own mime; trust it over a guessed default
        # so HEAD probes and <audio> get a Content-Type the browser accepts.
        mime = MIME_BY_EXT.get(ext, "")
        if not mime:
            found = re.search(r"[?&]mime=([^&]+)", url or "")
            if found:
                candidate = unquote(found.group(1)).lower()
                if candidate.startswith(("audio/", "video/")):
                    mime = candidate

        headers = {
            str(name): str(value)
            for name, value in ((chosen or info).get("http_headers") or {}).items()
            if str(name).lower() not in {"host", "content-length", "accept-encoding"}
        }
        return StreamInfo(
            url=url,
            is_live=bool(info.get("is_live")),
            expires_at=time.time() + self.settings.stream_cache_ttl,
            headers=headers,
            ext=ext,
            mime=mime or ("video/mp4" if video else "audio/mp4"),
            title=str(info.get("title") or track.title),
        )

    def invalidate(self, track: Track) -> None:
        self._stream_cache.pop(f"{track.id}:a", None)
        self._stream_cache.pop(f"{track.id}:v", None)

    # ── helpers used by cards ──────────────────────────────────────────────
    async def suggestions(self, seed: str, limit: int = 5) -> list[str]:
        try:
            tracks = await self.search(seed, limit=limit)
        except MediaError:
            return []
        return [truncate(t.title, 34) for t in tracks]

    def dump(self, data: dict) -> str:  # pragma: no cover - debugging helper
        return json.dumps(data, indent=2, default=str)[:2000]


__all__ = ["MediaError", "StreamInfo", "YouTube", "looks_like_url", "youtube_id"]
