# ---------------------------------------------------------------------------
#  VYRON — configuration
#  Every runtime knob lives here, sourced from the environment (or .env).
# ---------------------------------------------------------------------------
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _flag(key: str, default: bool = False) -> bool:
    raw = _env(key).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on", "y"}


def _int(key: str, default: int) -> int:
    raw = _env(key)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _split_ints(value: str) -> list[int]:
    out: list[int] = []
    for chunk in value.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            out.append(int(chunk))
    return out


@dataclass(frozen=True)
class Settings:
    # ── Telegram credentials ────────────────────────────────────────────────
    bot_token: str = field(default_factory=lambda: _env("BOT_TOKEN"))
    api_id: int = field(default_factory=lambda: _int("API_ID", 0))
    api_hash: str = field(default_factory=lambda: _env("API_HASH"))
    session_string: str = field(default_factory=lambda: _env("STRING_SESSION") or _env("SESSION_STRING"))

    # ── Identity ────────────────────────────────────────────────────────────
    bot_username: str = field(default_factory=lambda: _env("BOT_USERNAME", "VyronMusicBot"))
    bot_name: str = field(default_factory=lambda: _env("BOT_NAME", "𓆩 𝐕𝐘𝐑𝐎𝐍 𓆪"))
    owner_id: int = field(default_factory=lambda: _int("OWNER_ID", 0))
    sudo_users: list[int] = field(default_factory=lambda: _split_ints(_env("SUDO_USERS")))
    support_chat: str = field(default_factory=lambda: _env("SUPPORT_CHAT", "https://t.me/BeasgohanSupport"))
    updates_channel: str = field(default_factory=lambda: _env("UPDATES_CHANNEL", "https://t.me/BeasgohanSupport"))

    # ── Persistence ─────────────────────────────────────────────────────────
    mongo_url: str = field(default_factory=lambda: _env("MONGO_URL") or _env("MONGO_DB_URL") or _env("MONGO_URI"))
    mongo_db: str = field(default_factory=lambda: _env("MONGO_DB", "vyron"))
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", str(ROOT / "data"))))
    downloads_dir: Path = field(default_factory=lambda: Path(_env("DOWNLOADS_DIR", str(ROOT / "downloads"))))

    # ── Playback ────────────────────────────────────────────────────────────
    audio_quality: str = field(default_factory=lambda: _env("AUDIO_QUALITY", "high").lower())
    video_quality: str = field(default_factory=lambda: _env("VIDEO_QUALITY", "720p").lower())
    default_volume: int = field(default_factory=lambda: min(200, max(1, _int("DEFAULT_VOLUME", 100))))
    max_queue_size: int = field(default_factory=lambda: max(1, _int("MAX_QUEUE_SIZE", 100)))
    max_track_minutes: int = field(default_factory=lambda: max(0, _int("MAX_TRACK_MINUTES", 0)))
    #: Comma-separated words no request may contain (`BLOCKED_WORDS`).
    #:
    #: Empty by default on purpose: a blanket filter also refuses "Sex on Fire"
    #: and "Sextape", which are songs. Shizu ships a hard-coded list; here it is
    #: an operator decision, and the comparison is on whole words, so
    #: "essex live" still works when "sex" is blocked.
    blocked_words: str = field(default_factory=lambda: _env("BLOCKED_WORDS"))

    @property
    def blocked_word_list(self) -> tuple[str, ...]:
        return tuple(
            word.strip().lower()
            for word in self.blocked_words.split(",")
            if word.strip()
        )
    idle_leave_seconds: int = field(default_factory=lambda: max(0, _int("IDLE_LEAVE_SECONDS", 300)))
    # Radio mode is an opt-in, per chat: `/autoplay on`. On a free host the
    # assistant should leave when the queue someone built ends.
    autoplay_default: bool = field(default_factory=lambda: _flag("AUTOPLAY", False))
    autoleave_24_7: bool = field(default_factory=lambda: _flag("ALWAYS_ON", False))
    stream_cache_ttl: int = field(default_factory=lambda: max(60, _int("STREAM_CACHE_TTL", 1800)))
    # How long a track that just failed stays "known bad" — long enough to stop
    # a tap-happy listener from re-running the whole resolver, short enough that
    # a transient 403 heals by itself.
    stream_failure_ttl: int = field(default_factory=lambda: max(5, _int("STREAM_FAILURE_TTL", 60)))
    # No cookies? Impersonating a real browser is the next best thing: it fixes
    # the TLS/JA3 fingerprint YouTube uses to spot a datacenter IP.
    impersonate: str = field(default_factory=lambda: _env("IMPERSONATE", "chrome"))
    # Charts are per-country: ZZ is the global list, IN the India Top 50.
    charts_country: str = field(
        default_factory=lambda: (_env("CHARTS_COUNTRY", "ZZ") or "ZZ").strip().upper()[:2]
    )
    # Which characters may start a command. `/` is always included; an empty
    # entry enables prefix-less commands (`play x`) — opt-in only.
    command_prefixes: str = field(default_factory=lambda: _env("COMMAND_PREFIXES"))
    # YouTube breaks old extractors first. Checking PyPI once a day and
    # upgrading in place is what keeps a deployment playing without cookies.
    ytdlp_autoupdate: bool = field(default_factory=lambda: _flag("YTDLP_AUTOUPDATE", True))
    # Extra catalogue sources: a Spotify/Deezer/Apple link is read for its
    # metadata and matched on YouTube. `off` disables the whole tier.
    # Direct-stream fallbacks (Audius, JioSaavn, SoundCloud, Bandcamp) are not
    # governed by this: they serve their own audio, and they back YouTube up
    # automatically when it returns nothing.
    music_sources: str = field(
        default_factory=lambda: (_env("MUSIC_SOURCES", "spotify,deezer,apple") or "").lower()
    )
    # When YouTube refuses the server itself ("Failed to extract any player
    # response" from every client), no extractor fix helps. VYRON then plays the
    # same song from a catalogue that hands out real audio. Order matters: the
    # first engine is asked first. `off` disables the substitution entirely.
    alternate_sources: str = field(
        default_factory=lambda: (_env("ALTERNATE_SOURCES", "jiosaavn,audius,soundcloud") or "").lower()
    )
    # How long "YouTube is refusing this server" is trusted. While it lasts,
    # playback and search go straight to the catalogues instead of spending
    # twenty seconds per request re-proving it. A successful YouTube resolve
    # clears it early.
    youtube_wall_window: int = field(default_factory=lambda: max(30, _int("YOUTUBE_WALL_WINDOW", 900)))
    # YouTube Music search (ytmusicapi) is a better *search* than ytsearch for
    # music: songs with artist + album instead of "Official Video" uploads.
    ytmusic_search: bool = field(default_factory=lambda: _flag("YTMUSIC_SEARCH", True))
    # auto → aria2 (16 connections) → curl → aiohttp. `none` stays pure Python.
    download_accelerator: str = field(
        default_factory=lambda: (_env("DOWNLOAD_ACCELERATOR", "auto") or "auto").lower()
    )
    # Optional: the HMAC secret behind short-lived browser tokens (`/v1/token`).
    # Empty means "derive it from the bot token", which survives restarts and
    # dies when the credentials change.
    api_token_secret: str = field(default_factory=lambda: _env("API_TOKEN_SECRET"))
    # How many upcoming tracks are resolved ahead of time. Warming the next
    # *two* removes the dead air after a skip, but each one is a yt-dlp run, so
    # the worker is bounded by both this number and PREHEAT_SECONDS.
    preheat_depth: int = field(default_factory=lambda: max(0, _int("PREHEAT_DEPTH", 2)))
    # Wall-clock budget for one preheat pass: a slow first extraction must not
    # keep a background task alive, competing with the song that is playing.
    preheat_seconds: float = field(default_factory=lambda: max(0.0, float(_int("PREHEAT_SECONDS", 25))))
    # The HTTP port opens before the bot finishes booting (a host that never
    # sees the port assumes the deploy failed). A request that lands during that
    # window waits this long for the engine instead of getting a 503: a free
    # host waking from sleep needs about ten seconds.
    boot_wait: float = field(default_factory=lambda: max(0.0, float(_int("BOOT_WAIT_SECONDS", 15))))
    # yt-dlp is CPU-bound: two extractions at a time keeps the event loop (and
    # therefore the Mini App) responsive on a small host.
    extract_concurrency: int = field(default_factory=lambda: max(1, _int("EXTRACT_CONCURRENCY", 2)))
    # Download the track first, then stream the local
    # file. Immune to 403s, expiring URLs and mid-song drops — the usual reason
    # a hosted deployment "plays nothing". Costs the first few seconds.
    play_from_disk: bool = field(default_factory=lambda: _flag("PLAY_FROM_DISK", True))
    download_cache_hours: int = field(default_factory=lambda: max(1, _int("DOWNLOAD_CACHE_HOURS", 24)))
    maintenance_hours: int = field(default_factory=lambda: _int("MAINTENANCE_HOURS", 6))
    keepalive_minutes: int = field(default_factory=lambda: max(0, _int("KEEPALIVE_MINUTES", 10)))
    keepalive_url: str = field(
        default_factory=lambda: (
            _env("KEEPALIVE_URL") or _env("RENDER_EXTERNAL_URL") or _env("PUBLIC_URL")
        )
    )
    watchdog_seconds: int = field(default_factory=lambda: max(0, _int("WATCHDOG_SECONDS", 60)))
    maintenance_days: int = field(default_factory=lambda: max(1, _int("MAINTENANCE_DAYS", 30)))
    max_download_mb: int = field(default_factory=lambda: max(1, _int("MAX_DOWNLOAD_MB", 200)))

    # ── yt-dlp ──────────────────────────────────────────────────────────────
    cookies_file: str = field(default_factory=lambda: _env("COOKIES_FILE"))
    # Paste-able alternative for hosts where you cannot upload a file: the
    # Netscape cookie text is written to COOKIES_FILE (or a temp file) at boot.
    cookies_text: str = field(
        default_factory=lambda: _env("YOUTUBE_COOKIES") or _env("COOKIES_TEXT")
    )
    # A cookie file someone uploaded is only good until the session expires,
    # and the wall comes back mid-queue. Point this at a plain-text copy and
    # the bot re-reads it every few hours (and immediately after YouTube says
    # "confirm you're not a bot"), refusing anything that is not a cookie jar.
    cookies_url: str = field(
        default_factory=lambda: _env("COOKIES_URL") or _env("YOUTUBE_COOKIES_URL")
    )
    proxy: str = field(default_factory=lambda: _env("PROXY"))
    # ── Download API (/vyron; engine in vyron/engine/) ─────────────────────
    vyron_api: bool = field(default_factory=lambda: _flag("VYRON_API", True))
    yt_dlp_format: str = field(default_factory=lambda: _env("YT_DLP_FORMAT", "bestaudio/best"))
    yt_dlp_socket_timeout: int = field(default_factory=lambda: max(5, _int("YT_DLP_SOCKET_TIMEOUT", 20)))
    yt_dlp_retries: int = field(default_factory=lambda: max(1, _int("YT_DLP_RETRIES", 3)))
    download_cleanup_seconds: int = field(
        default_factory=lambda: max(60, _int("DOWNLOAD_CLEANUP_SECONDS", 900))
    )
    youtube_proxy: str = field(default_factory=lambda: _env("YOUTUBE_PROXY") or _env("YT_DLP_PROXY"))
    youtube_proxy_file: str = field(default_factory=lambda: _env("YOUTUBE_PROXY_FILE"))
    youtube_cookies_file: str = field(
        default_factory=lambda: _env("YOUTUBE_COOKIES_FILE") or _env("YT_DLP_COOKIES_FILE")
    )
    ytdlp_args: str = field(default_factory=lambda: _env("YTDLP_ARGS"))
    # When every yt-dlp client fails, ask Invidious/Piped for a direct URL.
    # Set STREAM_FALLBACK=off for a yt-dlp-only deployment, or override the
    # instance list with STREAM_FALLBACK_HOSTS=a.example,b.example.
    stream_fallback: bool = field(default_factory=lambda: _flag("STREAM_FALLBACK", True))
    stream_fallback_hosts: str = field(default_factory=lambda: _env("STREAM_FALLBACK_HOSTS"))
    # Self-hosted / extra Cobalt instances (comma separated). Empty = built-in
    # public list; "off" disables the tier.
    cobalt_urls: str = field(default_factory=lambda: _env("COBALT_URLS") or _env("COBALT_URL"))
    disable_cobalt: bool = field(default_factory=lambda: _env("COBALT_URLS").lower() in {"off", "none", "0"})
    stream_fallback_timeout: int = field(
        default_factory=lambda: max(3, _int("STREAM_FALLBACK_TIMEOUT", 9))
    )
    search_results: int = field(default_factory=lambda: min(10, max(3, _int("SEARCH_RESULTS", 5))))

    # ── UI / new Bot API features ───────────────────────────────────────────
    premium_emoji_file: str = field(default_factory=lambda: _env("PREMIUM_EMOJI_FILE"))
    premium_emoji_enabled: bool = field(default_factory=lambda: _flag("PREMIUM_EMOJI", True))
    rich_messages: bool = field(default_factory=lambda: _flag("RICH_MESSAGES", True))
    bot_profile: bool = field(default_factory=lambda: _flag("BOT_PROFILE", True))
    ephemeral_cards: bool = field(default_factory=lambda: _flag("EPHEMERAL_CARDS", True))
    np_refresh_seconds: int = field(default_factory=lambda: max(5, _int("NP_REFRESH_SECONDS", 12)))
    # Every track gets a generated poster (cover + vinyl + waveform). Turn off
    # for a text-only bot or when Pillow is not installed.
    np_poster: bool = field(default_factory=lambda: _flag("NP_POSTER", True))
    # Mirror what the Mini App starts into the listener's DM.
    np_dm: bool = field(default_factory=lambda: _flag("NP_DM", True))

    # ── Group management ────────────────────────────────────────────────────
    logger_id: int = field(default_factory=lambda: _int("LOGGER_ID", 0))
    default_warn_limit: int = field(default_factory=lambda: max(1, _int("WARN_LIMIT", 3)))
    default_flood_limit: int = field(default_factory=lambda: max(2, _int("FLOOD_LIMIT", 7)))
    flood_window: int = field(default_factory=lambda: max(3, _int("FLOOD_WINDOW", 9)))
    welcome_default: str = field(default_factory=lambda: _env("WELCOME_TEXT"))

    # ── Web app (Telegram Mini App) ─────────────────────────────────────────
    webapp: bool = field(default_factory=lambda: _flag("WEBAPP", True))
    start_img: str | None = None
    ping_img: str | None = None
    webapp_url: str = field(default_factory=lambda: _env("WEBAPP_URL").rstrip("/"))
    webapp_allow_anon: bool = field(default_factory=lambda: _flag("WEBAPP_ALLOW_ANON", False))
    webapp_title: str = field(default_factory=lambda: _env("WEBAPP_TITLE", "VYRON Player"))
    webapp_dir: Path = field(default_factory=lambda: Path(_env("WEBAPP_DIR", str(ROOT / "webapp"))))
    #: Resolve a bare YouTube id for /api/stream even when this deployment never
    #: showed it to anyone. Off by default — on is what makes the endpoint an
    #: open audio proxy, so it is only for a private instance.
    webapp_direct_ids: bool = field(
        default_factory=lambda: _flag("WEBAPP_DIRECT_IDS", False)
    )

    # ── Music API (served on the same URL, one deploy) ────────────────────
    music_api: bool = field(default_factory=lambda: _flag("MUSIC_API", True))
    music_api_open: bool = field(default_factory=lambda: _flag("MUSIC_API_OPEN", False))
    music_api_rate: int = field(default_factory=lambda: max(1, _int("MUSIC_API_RATE", 30)))
    music_api_cors: bool = field(default_factory=lambda: _flag("MUSIC_API_CORS", True))

    # ── Runtime ─────────────────────────────────────────────────────────────
    port: int = field(default_factory=lambda: _int("PORT", 8080))
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO").upper())
    session_name: str = field(default_factory=lambda: _env("SESSION_NAME", "vyron"))
    git_repo: str = field(default_factory=lambda: _env("GIT_REPO", "https://github.com/Beasgohan-code/VYRON"))

    # ── helpers ─────────────────────────────────────────────────────────────
    @property
    def owners(self) -> set[int]:
        ids = set(self.sudo_users)
        if self.owner_id:
            ids.add(self.owner_id)
        return ids

    @property
    def emoji_map(self) -> dict[str, dict[str, str]]:
        """Load the premium-emoji pack, if one has been configured."""
        if not self.premium_emoji_enabled:
            return {}
        for candidate in (
            self.premium_emoji_file,
            str(ROOT / "emoji.json"),
            str(self.data_dir / "emoji.json"),
        ):
            if not candidate:
                continue
            path = Path(candidate)
            if path.is_file():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(raw, dict):
                    continue
                clean: dict[str, dict[str, str]] = {}
                for key, value in raw.items():
                    if isinstance(value, dict) and value.get("id"):
                        clean[key] = {
                            "id": str(value["id"]),
                            "fallback": str(value.get("fallback") or value.get("emoji") or "✨"),
                        }
                    elif isinstance(value, str) and value.isdigit():
                        clean[key] = {"id": value, "fallback": "✨"}
                if clean:
                    return clean
        return {}

    def validate(self) -> list[str]:
        """Blocking problems — without these the bot cannot work at all."""
        errors: list[str] = []
        if not self.bot_token:
            errors.append("BOT_TOKEN is missing — create a bot with @BotFather.")
        if not self.api_id:
            errors.append("API_ID is missing — get it from https://my.telegram.org.")
        if not self.api_hash:
            errors.append("API_HASH is missing — get it from https://my.telegram.org.")
        if not self.session_string:
            errors.append(
                "STRING_SESSION is required — it is the assistant account that joins "
                "voice chats, so without it /play cannot stream. Generate one with "
                "`python -m vyron.tools.session` and restart."
            )
        return errors

    def warnings(self) -> list[str]:
        """Non-fatal gaps: the bot still boots and answers, one feature is off."""
        notes: list[str] = []
        if not self.owner_id and not self.sudo_users:
            notes.append(
                "OWNER_ID (or SUDO_USERS) is missing — nobody has admin access "
                "(group admins can still control their own chats)."
            )
        if self.webapp and not self.webapp_url:
            notes.append("WEBAPP=true but WEBAPP_URL is empty — the Mini App button stays hidden.")
        if self.music_api_open:
            notes.append(
                "MUSIC_API_OPEN=true — /v1 accepts requests without an API key. "
                "Only do this on a private deployment."
            )
        return notes

    @property
    def render_external_url(self) -> str:
        """Render publishes the public URL of the service under this name."""
        return _env("RENDER_EXTERNAL_URL")

    @property
    def webapp_ready(self) -> bool:
        return bool(self.webapp and self.webapp_url)

    @property
    def api_base(self) -> str:
        """Public base URL for the music API (same host as the Mini App)."""
        return self.webapp_url or self.render_external_url

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.downloads_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
