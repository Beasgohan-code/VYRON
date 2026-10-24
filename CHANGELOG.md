# Changelog

Two version numbers move independently:

* **the bot** (`vyron.__version__`) — user-facing: commands, playback, the Mini App;
* **the API** (`API_VERSION`) — the contract at `/v1`, documented live at `/v1/docs`.

## Bot

### 1.9.2 — 2026-10-24

* **Every reply is a card.** A one-line `B.note` answer was the last thing that
  did not look like VYRON. Welcome, playlists, favourites, queue moves, volume,
  loop, shuffle, autoplay, effects, playlist export/import, channel linking,
  moderation, owner tools and the transient "working…" placeholders now share
  one shape: `━ masthead ━`, `◈ fields`, context, buttons, footer. The order is
  the order a person reads on a phone — greeting, status, what it does, how to
  start, then the buttons.
* **The welcome card is rewritten** around that order, with a real uptime
  clock (`3d 9h 0m 34s`), reach, version, a feature list and a collapsed
  three-step setup guide.
* **One vocabulary for settings.** `/volume`, `/loop`, `/shuffle`, `/autoplay`
  and `/effects` show the value, what it means, and the buttons that change it,
  instead of a bold line that disappears up the chat.
* **Small caps are display only.** `to_plain_text` folds them back to ASCII,
  so toasts, logs and the plain lane read normally; labels inside cards align
  under `◈` instead of guessing table column widths.
* **Fixed: reactions never fired.** Kurigram has no `ReactionTypeEmoji`; the
  `ImportError` was swallowed by a bare `except`, so 👍/❤️ were silently lost on
  every command. `send_reaction` is called directly now.
* **Fixed: `/sudoers` never showed names.** `client.get_users` is awaitable,
  not an async iterator, so the loop body never ran.
* **Fixed: `/pview` read an undefined variable** when a track was removed, and
  its empty state rendered a headerless table.

### 1.9.1 — 2026-10-24

* **A walled server still plays music.** `Failed to extract any player response`
  on every client means YouTube has blocked this host's IP, which no extractor
  option fixes. When that happens VYRON now plays the *same song* from a
  catalogue that serves its own audio — JioSaavn, then Audius, then SoundCloud —
  matching on title, artist and length, and refusing anything that looks like a
  different cut. `ALTERNATE_SOURCES=off` turns it off.
* **It stops retrying a known wall.** Two identical refusals arm a circuit
  breaker (`YOUTUBE_WALL_WINDOW`, 15 min by default) so playback and search go
  straight to the catalogues instead of spending ~20 s per tap re-proving it. A
  successful YouTube resolve clears it immediately.
* **Search works while walled.** Results come from the direct sources (with real
  audio URLs) instead of timing out, and Home shelves are built from them.
* **Shared links still work.** When yt-dlp cannot read a video id, the title is
  read from an Invidious/Piped mirror, which is enough for the substitution
  tier to find that song somewhere that plays.
* **`/song` downloads substitute too**, and `/api/audio` reports `served_by` so
  the app can say which engine is actually streaming.
* **Small caps fixed.** `q` rendered as a literal `Q`, so every card read `ᴘQʀ`.
* **Search tolerates how people type.** When a query returns nothing, one
  relaxed retry runs: accents stripped, bracketed credits dropped, a held final
  letter squeezed (`Kesariyaa` → `Kesariya`). Real words are never mangled.
* **Lint and types.** `pyright` is part of the release sweep; the real bugs it
  found are fixed (an unbound `artist` that broke duplicate detection in the
  ranker, and a missing `rich.blockquote`).
* **Repo hygiene.** Unreferenced `assets/raw/` originals removed (2.3 MB).

### 1.9.0 — 2026-10-24

* **Queue warming.** The next two tracks are prepared ahead of time, inside a
  wall-clock budget, and only while something is actually playing.
* **Better matches.** Official audio, "– Topic" and lyric versions are preferred;
  covers, karaoke and reaction videos are demoted; duplicates are removed after
  ranking, not before.
* **Autoplay that does not loop.** The next track avoids the seed artist and the
  last two artists played.
* **Catalogue links play the right recording.** Spotify/Deezer/Apple links are
  matched through song.link to an exact YouTube id instead of a title search.
* **One streamer per voice chat.** A second instance runs as a standby, says so
  in `/doctor`, and refuses to start a stream instead of fighting the first one.
* **MongoDB is a real backend.** Three attempts with backoff on boot, tuned pool,
  a live ping and size report in `/dbstats`, and a one-time import of an existing
  `vyron.json` so switching never empties the bot.
* **Installable Mini App.** Web app manifest with real icons, an offline shell
  that keeps the app openable without a network, an offline banner, and a reload
  chip when a new build is waiting.
* **Cheaper first paint.** three.js loads once, after the shell is idle, and is
  skipped entirely on Save-Data or 2G. The lock screen shows a real scrubber.

### 1.8.0

* Short-lived browser tokens (`POST /v1/token`), idempotent downloads
  (`Idempotency-Key`), a real readiness probe, and a documented `API_TOKEN_SECRET`.

### 1.7.0

* Persisted source health with Prometheus gauges, `/v1/sources?probe=1`, mid-song
  recovery, and a single-source registry behind every fallback.

### 1.6.0

* Audius as a self-hosting audio source, plus the Spotify/Deezer/Apple/SoundCloud
  catalogue readers and YouTube Music links.

### 1.5.0

* JioSaavn, one registry that backs every source, and `/v1` key management that
  can edit a key instead of revoking it.

### 1.4.0

* `/play`, `/cplay` and `/song` collapsed into one surface with automatic media
  detection — the media kind is detected, never commanded.

## API

### 2.3

* `GET /v1/ready` — 503 with `Retry-After` until the voice engine and downloader
  are up; `/v1/health` stays 200 throughout.
* Per-key daily/monthly quotas on requests **and** bytes; exceeding one answers
  `429 quota_exceeded` naming the cap.
* `POST /v1/token` — short-lived, scoped browser tokens.
* `Idempotency-Key` on `POST /v1/downloads`.

### 2.2

* Measured source probing (`?probe=1`), health that survives a restart, and
  Prometheus gauges for it.

### 2.1

* `/v1/sources` and `/v1/sources/{name}`, richer `/v1/me`, key detail and
  non-destructive `PATCH`.

### 2.0

* Hashed keys, scopes, expiry, rotation, admin endpoints, metrics, canonical REST
  routes, OpenAPI 3.1, a single error envelope and request ids.

### 1.0

* The original download, search, metadata, lyrics, keys and docs.

## Documentation

* `/v1/docs` is generated from the running deployment: endpoint table, scopes,
  error table, rate limits, metrics, a troubleshooting page and this changelog —
  always the version that is actually serving.
* `README.md` — setup, deploy targets, commands, troubleshooting.
* `TROUBLESHOOTING.md` — the long form, with the commands that answer each symptom.
