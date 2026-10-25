# Changelog

Two version numbers move independently:

* **the bot** (`vyron.__version__`) — user-facing: commands, playback, the Mini App;
* **the API** (`API_VERSION`) — the contract at `/v1`, documented live at `/v1/docs`.

## Bot

### 1.9.5 — 2026-10-25

* **The now-playing message is the mock, line for line.** Exactly four facts,
  one per paragraph, in plain title case — no decoration above them, no number
  in front::

      ✨ Now playing

      Chris Grey - LET THE WORLD BURN (Official Lyric Video)

      ⏱ Duration: 2:44

      👥 Requested by: user

  The live block (bar, `📡 streaming · 1:03 · 39% · 2:44`, `🔊 100%`) follows
  underneath it, and `up next` after that when something is queued.
* **`Requested by:` always has a value.** An uncredited track says `user`
  instead of dropping the line, so the card does not change height between
  songs.
* **Autoplay is no longer printed on the card.** It is on by default, so the
  badge was a line that never changed anything; `/autoplay` still reports it.
* **Fixed: the now-playing helpers were defined twice.** 1.9.4 shipped two
  copies of the heading/header/flags helpers; the second silently won.
* Version 1.9.5.

### 1.9.4 — 2026-10-25

* **The now-playing card is the card people already know.** One look at the
  message the user pasted, and the shape became::

      1
      ✨ Now playing
      Chris Grey - LET THE WORLD BURN (Official Lyric Video)
      ⏱ Duration: 2:44
      👥 Requested by: Rinu

  Then the live block — bar, `📡 streaming · 1:03 · 39% · 2:44`, `🔊 100%` —
  then loop/autoplay and what plays next. No rule masthead above it: the ✨ line
  is the heading, so the card is six short lines instead of a decorated page.
* **Artist - Title, in that order.** The title alone told you the song but not
  who sang it; the line is now "Chris Grey - LET THE WORLD BURN", still linked
  so a tap opens the video, with no URL on screen.
* **Duration and requester are fields, not a sentence.** `⏱ Duration:` and
  `👥 Requested by:` are labels you scan, and the requester appears once
  instead of twice (it used to be in the header *and* under the bar).
* **The poster caption is the same card.** It is built from the same lines, so
  the picture message and the text fallback can never drift apart; the only
  difference is that the caption translates "streaming"/"paused" through the
  chat's catalog.
* Version 1.9.4.

### 1.9.3 — 2026-10-25

* **Search → play is one step when the answer is obvious.** Play bots split
  into "plays the first hit and is often wrong" and "always shows five choices
  and costs a tap every time". VYRON now measures how well the top result
  matches the query (`match_confidence`): a full match starts immediately, a
  partial one or a variant (slowed, nightcore, cover, 10-hour loop) opens the
  picker. The started card carries **other results**, so a wrong guess is one
  tap from the list.
* **Every result is three choices.** The picker's buttons are titled, numbered
  the way the list is, and offer **play**, **next** (jump the queue) and
  **queue** (leave the current song alone) — `/play` no longer has to interrupt
  what is playing to add something.
* **`/play` with no arguments explains itself** with a card and real buttons
  instead of a blockquote of examples.
* **The live card is a player, not a sentence.** The progress line was one
  run-on row of clock, percent and volume; it is now the block people already
  know from a music bot — the bar alone on its line, then
  `📡 streaming · 1:03 · 39% · 2:44`, then `👤 requester`, then `🔊 100%`.
  The bar itself is solid blocks with a ring playhead (`██████◉▬▬▬▬`), which
  survives being a few millimetres tall on a phone where a thin rule did not.
  The poster caption uses the same shape so the two never disagree.

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
* **The progress bar reads like music, not a download.** `1:03 ━━━━♡────────
  2:44`: played is a heavy rule, what is left is light, and the heart is the
  playhead. The caption is now three short lines (position, state + volume,
  queue/requester) with "up next" last.
* **A walled server still plays — and still makes the video.** A video request
  used to skip the substitution tier entirely, so a blocked YouTube meant
  silence; the resolver now asks the catalogues for audio even when video was
  requested, and the player drops the video flag when the bytes are audio
  (rather than failing the whole play) and says so in the card. `/song` and the
  app's video download gained a third engine: the same song from a catalogue,
  the poster as the picture, muxed to a 720p MP4.
* **MP3 downloads are 320 kbps** (the AAC inside a generated video is 256).
* **No more minute-long stalls on a walled host.** The downloader asks the
  resolver whether YouTube is refusing this server; when it is, the four-client
  yt-dlp ladder (49 s in production, all four refused) is skipped and the
  download goes straight to a mirror. Two *identical* refusals now end the
  ladder early instead of walking the rest of it.
* **"Connection pool is full" is gone.** ytmusicapi built a default session
  whose urllib3 pool holds ten connections, and search/charts/autoplay talk to
  music.youtube.com at once. It now gets a 64-connection pool with retries and
  a 5/20 s timeout.
* **`/play` video.** The started card carries a "Play as video" button for
  YouTube tracks: it re-streams the same track from where it is (not from 0:00)
  with its picture. If the server has no video for it, the answer is a toast,
  not a broken stream.
* **Downloads keep the container they actually are.** A JioSaavn/Audius stream
  is written with its real extension and transcoded to MP3 at 320 kbps when
  ffmpeg is present — the old code renamed every AAC stream to `.mp3`, which
  strict players refused.
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
