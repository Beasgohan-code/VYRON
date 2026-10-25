# Changelog

Two version numbers move independently:

* **the bot** (`vyron.__version__`) — user-facing: commands, playback, the Mini App;
* **the API** (`API_VERSION`) — the contract at `/v1`, documented live at `/v1/docs`.

## Bot

### 1.10.5 — 2026-10-25

"What I typed did work yesterday." Three separate faults in one report:

* **A misspelt name is not a failed search.** `.play wrong cheris grey` (Chris
  Grey) and `.play let the world burn` both answered "No results" although the
  right row was in the results: relevance was exact word overlap, so "cheris"
  never matched "chris" and the filter threw the song away before it was ever
  offered. Words now match within one typo (same first letter, ≥78% similar) in
  the confidence score, the relevance gate and the ranking — "love" still does
  not become "live".
* **One refused lane no longer discards the others.** A refused `ytsearch`
  raised out of the YouTube half and took YouTube Music's results with it. Each
  lane fails on its own now, and there is a fourth one: Invidious/Piped keyword
  search, which answers even on an IP whose *streams* YouTube refuses — no new
  dependency, the same instances VYRON already uses for streams.
* **A file on disk beats a URL that can expire.** A cached or prefetched file
  is streamed instead of the resolved URL, and the prefetch behind the current
  song now fetches the *next track's file* inside its existing budget, so the
  hand-off after a song or a skip is instant and cannot 403 halfway through.

**The poster is automatic, and it is the picture people wanted.** The card
showed a repost account as the artist ("Alone_BoYtm - Chris Grey – LET THE
WORLD BURN"), linked the name to an Audius stream URL, wrapped `2:43` in a code
box, and the artwork — when it appeared at all — had four empty boxes where the
listener's name goes.

* one naming rule (`vyron/utils/naming.py`): the artist already in the title
  wins, a repost handle is never the artist, "(Official Video)" is not part of
  a name, and "Artist - Topic" becomes the artist;
* the card links the name only when there is a *page* behind it — a YouTube
  video — never a CDN stream URL, and it no longer invents `tg://user?id=0`;
* the poster asks the CDN for the biggest cover (`maxresdefault`, `1000x1000`)
  instead of the 480 px one it used to blur to 1280 wide;
* display names are flattened before they are drawn: mathematical bold, small
  caps and Greek homoglyphs become Latin, scripts we ship no font for are
  dropped rather than printed as tofu, and the "requested by" chip shrinks its
  type instead of clipping to "BEAST GOH…";
* the backdrop keeps the artwork's own colour, so a warm sleeve gives a warm
  poster instead of a purple wash;
* **`/thumbnail` is gone** — with its settings-panel button and its command
  menu entry. Nobody chose a per-group backdrop; the poster is the song's own
  art now. `/cthumbnail` for a channel is unchanged.

**A player panel, drawn the way only a rich message can be drawn.** The bots
this one is measured against put a fact table and coloured controls *inside*
the message; VYRON's `/np` sent a caption-shaped card. When there is no picture
to caption — `/np`, the **Now playing** button, a chat with the poster off —
the bot now sends a real panel: `<h2>` masthead, a two-column fact table
(title · artist · length · asked by · source), the live bar, a collapsible
**up next** section and four rows of coloured controls (primary = move,
success = forward, danger = stop). The classic lane gets the same five facts as
the aligned field block, the buttons stripped, and the reply keyboard it always
had.

Also fixed for both lanes:

* a table flattened by `to_html` no longer ends every line in a stray "·";
* `<img>` is dropped on the rich-lane retry. A remote cover URL is the single
  likeliest thing for Telegram to refuse, and losing the picture beats losing
  the heading, the table and the buttons with it;
* `/np` and the Now playing button show the song the way it is actually named
  (`Chris Grey - LET THE WORLD BURN`, not a repost handle).

Also in this build: mastheads are real headings in the rich lane and a quoted
line (not a wall of `━`) in the classic one, a refused rich card is retried
without its optional tags instead of falling back to plain HTML, `/doctor` says
whether rich cards are working, the download card shows live progress, and the
mirror and the catalogue copy download in parallel instead of one after the
other.

### 1.10.4 — 2026-10-25

The bug that made the bot look broken: **`.play Wrong` searched for the literal
string ".play Wrong"**.

* **Arguments are parsed for every prefix, not just `/`.** The filter accepted
  `.play`, `!play`, `?play` and the rest — that is a feature the bot advertises —
  but the argument parser only stripped `/command`. So in any chat that typed a
  dot, the query reached the search engine with the command still attached:
  five results whose titles happened to contain "play", a header reading
  "results · .play", and nothing that was actually asked for. `command_args()`
  now strips whichever configured prefix was typed, with or without
  `@botname`, in any case, and only when the word after it is a real command —
  so a query that legitimately starts with punctuation (`#1 hit`) is left
  alone. `".play .play"` still plays the song called ".play".
* **The `commands` moderation lock covers every prefix.** It tested
  `text.startswith("/")`, so a locked group could still be driven with `.play`.
* **Off-topic catalogue pages no longer win the search race.** A catalogue
  answers *something* for any string — the five "play" songs above are the
  proof — so "the page is full" now means "full of results that share a word
  with the query". The rest are still offered, ranked last, but they no longer
  stop YouTube from being asked.
* Version 1.10.4.

### 1.10.3 — 2026-10-25

Three complaints, three causes, all in the parts that decide what plays and
when.

* **Playback came back.** Two separate bugs kept the voice chat silent after
  YouTube started refusing this host:
  * the downloader treated "YouTube is walled" as "yt-dlp is useless" and
    skipped the ladder for *every* track — including the SoundCloud substitute
    it had just found, which yt-dlp downloads perfectly. The wall now only
    skips YouTube tracks.
  * a substitute's `url` is a *page* for SoundCloud and Bandcamp, not audio.
    It was being fetched as bytes and written into a `.mp3`, so the failure
    arrived later, on the listener's side, looking like the bot refusing to
    play. Direct catalogues stream, pages are extracted.
* **A standby no longer stays a standby for ever.** Render overlaps a redeploy
  for a few seconds, so the incoming instance saw a fresh lease belonging to
  the process that was shutting down, stood down for its own voice chat, and —
  because `claim` only ran once at boot — never asked again. A deployment could
  answer every command and play nothing until the *next* deploy. The lease is
  now renewed on the same 30-second beat: a lapsed lease is taken over, 24/7
  playback resumes on promotion, and the journal says so.
* **Searches answer in about a second.** The catalogue lane (JioSaavn, Audius,
  SoundCloud — the ones that hand out real audio) now starts at the same moment
  as YouTube instead of after it, and wins whenever it can fill the page:
  it gets 1.3 s of exclusivity, YouTube gets the rest of a 6 s budget, and a
  thin catalogue is merged rather than preferred. Results are cached for five
  minutes per query, so the picker, a retry and "other results" are free.
* **A track plays as soon as it is asked for.** Direct catalogue tracks stream
  from their URL instead of being downloaded first; a walled YouTube track asks
  the resolver (one cached step) instead of re-walking the download ladder; and
  if every resolver fails, a file on disk is tried before the chat is told it
  failed.
* **The working card looks like the app.** `/play` used to answer with
  "⏱️ Searching YouTube…" over an italic "give it a moment — VYRON is on it" —
  two lines of orange text in a product where every other reply is a shaped
  card, and it named the wrong engine. It is now the same masthead, marked
  fields and footer as everything else, showing what is being looked for and
  what is happening to it, with live stage updates at 1.5 s and 3.5 s that stop
  the instant the answer is written.
* **Failures say what a listener can do.** "Could not stream that" plus the
  engine chain is developer text. The three real cases — no voice chat, another
  instance holding it, nothing playable — each get a sentence that ends in an
  action.

### 1.10.2 — 2026-10-25

Sized for the phone it actually runs in, and two failures from the log.

* **A new splash, and one that fits.** The boot picture is redrawn for a phone
  (glow in the top third, deliberately empty below it) and every measurement on
  that screen now scales with the viewport instead of assuming a desktop —
  `clamp()` for the logo, the name and the gaps, safe-area padding at the foot,
  and a short-screen rule that drops the stage list before anything is cut off.
  The old oversized drift transform is gone, so the artwork keeps its own
  proportions instead of being cropped by 8%. In a light client the splash no
  longer writes dark ink on a dark picture.
* **Home is denser.** At 390 px the hero used its first screen on a 29 px
  headline and three full-size buttons, so "Trending now" — the reason to open
  the app — started below the fold. Phone sizes now: 21–27 px headline, tighter
  padding and gaps, smaller CTAs and stats, 132 px tiles; a second step at
  370 px keeps the CTA row and the three stats on one line on an SE.
* **`/api/state` cannot 500 the whole app any more.** The payload is a fan-out —
  chat title, favourites, history, playlists, counters — and one raising call
  used to answer 500 to every poll, which made the Mini App unopenable (the log
  was full of `GET /api/state crashed`). Each part now degrades on its own and
  says so in the journal, malformed rows are skipped, and the response is
  written with `default=str`, so a bson ObjectId or a datetime in a stored
  document is a stringified field instead of a dead endpoint.
* **The log line names the failure.** `GET /api/state crashed: TypeError: …`,
  because Render's stream shows messages only and a bare "crashed" forced a trip
  to `/api/logs` before anyone knew what had happened.
* **A clean install builds again.** The three font packages were in
  `package-lock.json` but not in `package.json`, so `npm ci` (CI, and the
  Docker image) installed nothing to import and every build failed. Declared
  properly now.
* **The journal stops restoring its own summaries.** "restored 21 warning(s)"
  was mirrored, restored by the next boot, mirrored again — the tail grew a row
  per restart and the count climbed 3 → 10 → 29 across deploys. Summaries are
  bookkeeping now: not mirrored, ignored on restore, and de-duplicated.

### 1.10.1 — 2026-10-25

The last four items from the review, and a floor under the whole app.

* **A crashed screen no longer means a blank one.** React unmounts the entire
  tree when a render throws, which inside Telegram is a white rectangle with no
  message and no way out. An error boundary now catches it, says in plain words
  that the bot and the queue are unaffected, and offers a reload — and posts the
  message and stack to the owner journal through `POST /api/client-error`, so
  the next report is a diagnosis instead of a guess.
* **No third-party font requests.** Bricolage Grotesque, Inter Tight and
  JetBrains Mono are self-hosted as variable woff2 (`@fontsource-variable`),
  latin subsets only — three fewer connections before first paint, no Google
  request on every launch, and type that still renders when a webview blocks
  the stylesheet. The display picture is preloaded with it.
* **Search has a floor and a "show more".** The window starts at twelve rows
  and widens to 48 in place, so a vague query no longer means retyping it more
  cleverly.
* **The track sheet grew the actions people actually reach for**: share through
  Telegram's own sheet, copy the link, and jump to everything else by the same
  artist.

### 1.10.0 — 2026-10-25

The Mini App now behaves like a client of Telegram rather than a page inside
one, and it stops hammering the server for data that has not changed.

* **Back goes back.** The Android back gesture used to leave the Mini App — and
  leaving it stops the song. It now walks the stack (keyboard overlay → player →
  sheet → home) and steps out only at the top. `Escape` runs the same function,
  so the two cannot drift.
* **Swiping away asks first, while it would cost something.** Closing
  confirmation is on only while audio plays; the player also takes over the
  vertical gesture, so "drag down to close the player" no longer closes the app.
* **The client's own colours.** "Telegram" as a theme used to mean four
  variables; it now maps the whole palette (`bg`, `secondary_bg`, `text`,
  `hint`, `link`, `button`, `accent`, `destructive`, `section`) from the
  `--tg-theme-*` variables the client injects, flips the surface overlays for a
  light client, and re-syncs on `themeChanged` without a reload. The header and
  bottom bar are painted through `setHeaderColor` / `setBottomBarColor`.
* **The keyboard stops covering the app.** `viewportChanged` (and
  `visualViewport` in a browser) now publish the visible height as CSS
  variables; when the keyboard opens the dock and tabs step aside instead of
  sitting on top of the search field.
* **Deep links.** `t.me/<bot>?startapp=playlist_<id>`, `mix_<key>`,
  `search_<words>` and a plain view name are honoured once, after the first
  state arrives — the only way a bot message can open the app on something
  without printing a URL.
* **Covers come from our own origin.** Every `<img>` pointed at
  `i.ytimg.com`: a third party saw every listener's IP, the first paint waited
  on an outside TLS handshake, and a deleted video became a grey tile. New
  `GET /api/art/<id>?s=96|300|600` serves the picture from the app's own host —
  resized to WebP with Pillow, cached in memory, `immutable` for 30 days, `304`
  on a repeat, and a `srcset` in the UI so a phone downloads 96 px, not 600.
  Collection sleeves (a playlist, an artist card) go through the same route by
  URL, restricted to a fixed list of picture CDNs — never an open proxy.
* **The poll got cheap.** `/api/state` rebuilt favourites, history, playlists
  and counters every five seconds — 700+ documents an hour per open app for
  data that changes on a tap. `/api/now` answers with the live half only and a
  `304` when even that has not moved; the app merges it into what it already
  has instead of replacing the screen.
* **Dialogs trap focus.** `Sheet` and `Player` move focus in, keep Tab inside,
  and put focus back on the trigger when they close.
* **Screen readers hear the track change.** The dock is a picture and two
  truncated lines; a polite live region now announces "Now playing: title by
  artist".
* **Contrast.** `--dim` (every 11–13 px meta line) was 4.24:1 on the page and
  3.86:1 on a panel; it is 5.3:1 / 4.9:1 now.
* **Pinch-zoom is back.** `maximum-scale=1` was taking it away from anyone who
  needs it; `touch-action: manipulation` keeps the fast taps it was added for.
* **Less blur when asked.** `prefers-reduced-transparency` flattens the dock,
  topbar and sheets.
* Version 1.10.0.

### 1.9.6 — 2026-10-25

* **The Mini App shows your Telegram profile picture.** It used to draw a
  generic logo (or your initials) because a browser cannot request a picture
  with `X-Init-Data` on an `<img>`. The server resolves it now: `/api/avatar`
  takes the signed `photo_url` Telegram puts in `initData`, falls back to the
  bot's own `get_chat`, and returns the bytes — cached for six hours, with a
  ten-minute negative cache so a user who hides their picture is not asked
  again on every screen.
* **One avatar everywhere.** A new `Avatar` component draws the picture over
  the person's initials (deterministic colour per name), fades it in when it
  arrives, and keeps the initials if the image fails — there is never an empty
  circle waiting on a network. It sits in the topbar (the way to *You* on a
  phone) and on the profile card, where the picture is now a ringed squircle
  with a live status dot.
* **Instant on reopen.** The last picture is kept on the device, so a Mini App
  that Telegram killed (which is every time you leave the chat) paints your face
  before the first request finishes — and still shows it with no network.
* **Fixed: a stale version literal.** `runtime.version` defaulted to `1.3.0`,
  so the app footer and `/health` reported a version from months ago whenever
  the process did not come through `__main__` (the preview server, tooling).
  It now reads the package version, and the footer says 1.9.6.
* Version 1.9.6.

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
