# Changelog

Two version numbers move independently:

* **the bot** (`vyron.__version__`) — user-facing: commands, playback, the Mini App;
* **the API** (`API_VERSION`) — the contract at `/v1`, documented live at `/v1/docs`.

## Bot

### 1.10.18 — 2026-10-25

**A walled deployment stops re-proving the wall on every track.** The Render log
showed the same shape four times over: the IP is refused, so each track walked
two yt-dlp clients (~15 s of socket timeouts), gave up, and *then* asked a mirror
that answered in one second. While the wall is known, the two lanes that can
actually succeed — somebody else's resolver (same video, signed URL) and a
catalogue copy (same song, its own audio) — are now asked **together**, and the
first real answer wins. The yt-dlp ladder still runs if both fail, but it is no
longer the default path on a blocked host. A tap that took 15 s resolves in one
or two.

**A stale button tap is not a crash.** `QUERY_ID_INVALID` means the tap was older
than Telegram's answer window — normal in a busy group, and it was filling the
journal with tracebacks plus a second answer attempt that also failed. Every
`cq.answer` now goes through one helper that treats it as a debug line, and the
callback router no longer reports it as an exception.

### 1.10.17 — 2026-10-25

**A cookie jar that keeps itself fresh.** `COOKIES_FILE` is a snapshot: the
session behind it expires and YouTube's "confirm you're not a bot" wall comes
back, usually in the middle of a queue where it looks like the bot broke. With
`COOKIES_URL` set, the jar is re-read every six hours, **and immediately when the
wall is detected**, and the retry uses the new one.

Only a real Netscape jar is ever installed. A placeholder
(`paste your cookies here`), an HTML error page, a JSON export or an oversized
body is refused and the previous file is kept — a mistyped URL can never
downgrade a working deployment, and the failure is logged instead of surfacing as
"cookies are invalid". `COOKIES_FILE` still wins over everything and is never
rewritten. `/doctor` reports which jar is in use, where it came from and how old
it is; `/clearcache`-style housekeeping now includes the refresh.

### 1.10.16 — 2026-10-25

**The comparison, written down.** [`docs/COMPARISON.md`](docs/COMPARISON.md)
audits VYRON against ShizuMusic (49 files / 51 commands), Videl (45 / 78) and
FallenMusic (39 / 44): every file and every command name, with a verdict and a
one-line reason — including the ones deliberately not copied (the force-play
family, `/speedtest`, and the dozen pure aliases).

Two findings from the audit are already shipped: the missing chat cleanup
(1.10.15) and the download-side browser impersonation (1.10.13).

### 1.10.15 — 2026-10-25

**A group that removes the bot gets its resources back.** Until now, being
kicked mid-song left three things behind: the queue in memory, a snapshot of it
on disk, and a per-chat settings record (volume 40, loop, 24/7, mood) that
outlived the group. Telegram itself usually ends the call, but nothing told the
player. A `my_chat_member` handler now catches its own removal, stops playback,
leaves what is left of the call, drops the chat from the player and deletes its
stored settings — so the next time that chat id appears, it starts from the
defaults instead of inheriting a stranger's volume.

**And a group that adds the bot gets an answer.** The same handler sends the
group setup card on join: rights, streaming state, what is missing. Shizu and
Videl both greet on join; VYRON stayed silent until somebody typed `/start`.

Both backends learned `delete_chat_settings` (JSON/embedded and MongoDB) to make
the cleanup real rather than cosmetic.

### 1.10.14 — 2026-10-25

**Revoked API keys delete themselves after seven days.** A revoked key used to
live in the store forever — a hash of a dead secret, growing a list nobody
prunes. It is now kept for `REVOKED_GRACE_DAYS` (7) so `/apikeys` can still
answer "did I rotate that one, or did it just stop working?", and then deleted
outright: at boot, on every housekeeping sweep, and on demand from
`/dbcleanup`. A revocation with no timestamp is never guessed at — it is left
alone until something writes one.

Both storage backends learned `delete_api_key` (JSON/embedded and MongoDB), the
`/apikeys` card says how long a revoked key is kept, and `/dbstats` reports how
many the last sweep removed.

### 1.10.13 — 2026-10-25

**Everything faster: the download, the fallback, and the search behind them.**

*Six connections instead of one.* The Python tier of the download accelerator
was a single-connection `aiohttp` stream — fine for a cover, wrong for a song.
It now asks the server how big the file is, splits it into ranges and pulls them
at once over the shared keep-alive session (`accelerator.ranged_fetch`), falling
back to one connection only when a signed URL refuses ranges. On a CDN that
throttles per connection that is the whole difference between twenty seconds and
three, and it needs no `aria2c` binary — which is why it is the default tier on
Render. `aria2` still wins when it is installed.

*yt-dlp was asked to fetch in the slowest possible way.* Four concurrent
fragments for DASH audio, 8 MB HTTP chunks for progressive m4a, a 1 MB buffer —
and, the big one, **no re-encode**: an AAC-in-m4a download is copied, not
transcoded to a 320 kbps MP3. Encoding a four-minute song after the download had
already finished was eight to twelve seconds of pure CPU on every single `/song`
and every first play of a YouTube track.

*A slow extraction no longer holds the fallbacks hostage.* yt-dlp keeps a six
second head start (`HEAD_START`); if it is still working, the mirror and the
catalogue race it and the first real file wins. A walled or throttled extraction
used to spend its entire deadline — two clients times the socket timeout —
before the mirror was even asked. The raced extraction writes to a private path,
so a loser finishing late can never move its file over the winner's, and a raced
copy keeps its real container instead of being renamed `.mp3`.

*One more mirror tier that needs no JSON.* When every Invidious/Piped/Cobalt API
is rate-limited, `/latest_version?id=…&itag=140` still answers with a media URL.
It is probed with a single ranged byte over the first three healthy hosts at
once — a `302` to a CDN is proof, a `404` is not — so it costs one round trip
and is never handed to a player unproven.

*A direct m4a is moved, not re-encoded.* The same rule as the YouTube path: an
AAC-in-m4a catalogue stream is served as it arrives, and only the containers
Telegram's player is picky about (webm/opus, ogg) go through ffmpeg.

*`/sources` now names the download tier* (files or ranges), so "which one is
actually doing the work" is answerable from inside the bot.

*The rest of the network went through the same session.* Lyrics, Deezer/Spotify/
Apple metadata, Deezer short-link redirects and the Telegram-avatar proxy all
opened their own `ClientSession` — one TLS handshake each, per call. They use the
shared session now (and `net.session()` rebuilds itself if the event loop
changed, instead of failing with "Event loop is closed"). Autoplay's second and
third lane searches run together rather than one after the other.

### 1.10.12 — 2026-10-25

**Search and download got their seconds back.** Three separate things were each
costing the listener a timeout, and they added up to the seven-second picker and
the "this song will not download" card.

*Every catalogue call opened its own HTTP session.* JioSaavn, Audius, the public
mirrors and the artwork proxy each built a `ClientSession`, which on a cold
container is a fresh TCP handshake and a fresh TLS handshake — per lane, per
keystroke, per retry. They all go through one keep-alive session now
(`utils/net.py`): connections are reused, the DNS answer is cached for five
minutes, and the connect timeout is 3.5 s rather than "however long the kernel
feels".

*The substitution tier waited for its slowest lane.* `search_all` gathered every
engine and returned when the last one finished, so a SoundCloud lane extracting
a page per result set the price of every substitution at the full timeout. Lanes
are gathered **as they complete** now, deduped, and the stragglers are cancelled
the moment the page is full; the per-engine timeout is 4 s instead of 7. When no
engine answers at all, `find` no longer asks a second identical query — it says
so and stops, and a *miss* is remembered for two minutes instead of an hour, so
one throttled minute cannot mark a song unplayable for the rest of the session.

*Downloads never impersonated the browser the search did.* `IMPERSONATE` was
applied to the resolver's yt-dlp options and not to the downloader's, so a
datacenter IP was allowed to *name* a video as Chrome and then refused when it
asked for the bytes. The options builder is shared now
(`search.impersonate_target`), so both halves of a play carry the same TLS/JA3
fingerprint and header order — the one no-cookie fix that actually helps a
walled host.

*The wall made YouTube the most expensive thing in a search.* Its streams are
refused from a walled IP, but its *names* are still worth having — so a walled
YouTube now gets a 0.6 s glance (`WALLED_GLANCE`) instead of the six-second
deadline, and the catalogue page is returned immediately. The picker answers in
about a second while the wall is up, and still merges in whatever YouTube named
in time.

### 1.10.11 — 2026-10-25

**A group `/start` now answers the question a group actually has.** The private
card explains what the bot is; pasted into a group it was the wrong card — four
features and a setup guide for something already installed. `/start` in a group
now greets the chat by name, credits whoever ran it, and reads the bot's *real*
rights there: manage voice chats, delete messages, invite users, pin messages,
each one ✓ or ○ with the reason it matters, and a single line naming what is
still missing so an admin knows exactly what to tick. If the probe cannot run,
the card says so instead of claiming four failures.

Same photo, same buttons (three in a group), same one builder: the **Home**
button in a group now rebuilds the group card too, so a tapped button and a
typed command can never disagree. In a group the `/start` message itself is
deleted — the card is the message — while in a private chat it still replies to
the command. A `FloodWait` on the photo is waited out and retried instead of
leaving the chat silent, and the owner journal gets one line the first time a
group or a listener says hello, not a page per `/start`.

### 1.10.10 — 2026-10-25

**The first `/play` in a group streamed with no now-playing card at all.** When
the assistant had to be invited before it could stream, the retry path returned
from `_start_stream()` *before* the bookkeeping — so `state.current` was never
set. Audio started, and the chat got no poster, no elapsed clock and no play
counted, because as far as the rest of the bot was concerned nothing was
playing. The retry now falls through to the same success path as every other
play, which also means the first play in a new group is counted, saved and
mirrored like the rest. A test pins it: with the old code the state was empty
after a successful invite.

**Joining is spelled the way every client accepts.** An exported invite link of
the `t.me/+Hash` form is rewritten to `t.me/joinchat/Hash` before the assistant
tries it, and a `USER_BANNED` failure is reported as a ban in the owner journal
instead of the generic "could not join" that sent people hunting for a network
fault.

### 1.10.9 — 2026-10-25

**Autoplay stopped drifting out of the lane, and stopped being slow.** Two
separate bugs, one cause: the pool it chose from was too narrow and the order
it chose in was not the order it had just computed.

* **related videos are a source now, not the winner.** A prefetched *related*
  track used to sit in front of the queue and start at the end of a song, so a
  Malayalam room got whatever YouTube's graph liked — the exact drift
  `autoplay.py` exists to prevent. The pool is now related **plus** the lane's
  searches, merged and de-duplicated, and the pick happens once over all of it.
  The prefetch warms that lane pick instead of a raw related one.
* **the lane rank survives the shuffle.** Picking used to shuffle the top three
  candidates, which could put a non-matching track ahead of a perfect match.
  Ties are still shuffled — that is what keeps a queue from walking the same
  chain — but only *inside* a rank, never across one.
* **mood and language are matched on the candidate itself**, from its title and
  channel, as a preference rather than a filter. A hard filter looks tidier and
  is worse in practice: on a query that returns nothing in the lane it empties
  the pool, and an empty pool is an autoplay that stops.

The first two lookups (related + the lane's first query) run together and
further queries are only spent while the pool is thin, so the common case is
still one round trip.

### 1.10.8 — 2026-10-25

**A filter you switch on is a filter you hear.** ntgcalls takes the `-af` chain
when a stream *starts*, so turning bass or nightcore on mid-song used to do
nothing until the next track — which reads as a button that does not work. The
stream now re-opens at the second it is sitting on (same track, same card, the
play counter untouched). The `-af` chain, the chat's stored setting and the
live re-open all go through one helper, so the `/effects` card, the button
board and the Mini App cannot disagree.

**The Mini App's DM card follows the song, not every tap.** Mirroring skipped a
song that is already on the card, so pressing play twice or skipping onto the
track that just started no longer deletes the card and posts it again, and
`stop` removes it instead of leaving "now playing" in a chat where nothing is.

### 1.10.7 — 2026-10-25

Taking the two things people actually complained about, plus what ShizuMusic
does that VYRON did not.

**"The thumbnail is not there when it plays."** The poster was being sent — and
then `/play` edited its working card into a text "started" card underneath it,
so the chat got a picture *and* a text twin of it, and on the next track the
poster was edited in place while the text card stayed. A text message cannot
become a photo in Telegram, so the rule is now explicit: the picture is the
now-playing message.

* the working card is deleted the moment the poster is on screen (`_settle`),
  including from the search picker, so one play is one message;
* an existing text now-playing card is *replaced* by the picture instead of
  being edited into another text card;
* the previous poster is deleted when a new one lands, and so is a session's
  poster when the session ends;
* the Mini App's DM mirror keeps one card per listener instead of leaving a
  poster per song in their private chat;
* a picture that cannot be uploaded now says why in the owner journal
  (`art`) instead of only at debug level.

**A song with no cover art gets a sleeve instead of a bullseye.** Catalogue
results sometimes arrive without artwork and a CDN fetch can fail on a
datacenter IP; the tile now draws the song's initials in the brand font over an
accent wash — "LET THE WORLD BURN" becomes `LTW`, not an empty ring.

**"When the queue finishes the assistant should leave."** It did call leave —
but radio mode defaulted to *on*, so autoplay always found something and the
bot never let go of the call. Radio is now an opt-in (`/autoplay on`, env
`AUTOPLAY`), a stored `"autoplay": true` written by the old default is treated
as a default rather than a decision (a stored `false` still wins), and the end
of a session posts a designed card — tracks played, the last song, whether the
assistant left — with three buttons: **Play again**, **Radio**, **Close**.

**From ShizuMusic:**

* the command message is deleted once it has been answered (groups only, never
  fatal), done *after* its card exists so nothing is ever sent as a reply to a
  deleted message;
* `BLOCKED_WORDS` filters a request before it runs — empty by default, and
  matched as whole words, because "Sex on Fire" is a song and "essex" is not
  "sex";
* the locked-content and resolver-probe notices are proper cards now, in the
  same rhythm as the rest of the bot.

### 1.10.6 — 2026-10-25

A boot log from Render, read line by line. Every fault below happened on a real
deployment, and most of them were invisible to the person using the bot:

* **`/song` lost the whole file whenever the cover downloaded.** The artwork was
  passed to the upload as raw bytes; the client's upload path accepts a path or
  a *binary file object*, and nothing else. The rejection happened inside
  `send_audio`, so the audio went down with the picture. One conversion
  (`vyron.utils.net.as_file`) is now the only way bytes reach Telegram.
* **`Peer id invalid: 0`.** A token minted without a chat context resolves to
  peer 0, which is not a peer at all — groups and channels are negative. Cards
  are no longer addressed to it (nothing can arrive, so nothing is attempted),
  and the chat-title lookup neither asks for it nor re-pays a 3-second timeout
  on every poll.
* **`/api/state` can no longer answer 500.** The whole Mini App is built from
  that one document; an outer guard now returns a degraded payload (with the
  reason in the owner journal) instead of a blank screen.
* **A client hanging up is not a crash.** aiohttp's `ClientConnectionResetError`
  is not a `ConnectionResetError` subclass, so every existing `except` missed
  it: each seek and each locked phone wrote a red line into `/logs` and buried
  the entries that mattered. The stream copy loop, the log SSE route and the
  middleware now treat a dead reader as the normal end of a request.
* **`/api/audio/{id}` took 29.7 s.** A lookup that failed was repeated for
  every hit — a storage round trip plus an 8-second catalogue call each time.
  Answers are cached per user (misses for a minute), the storage half of a
  lookup is cut off at 4 s, and a track in the registry always beats a cached
  miss.
* **The download ignored `YOUTUBE_PROXY`.** Only `PROXY` was read, so a
  deployment that proxied its *metadata* still downloaded from the blocked
  datacenter IP. Downloads honour `YOUTUBE_PROXY` / `YT_DLP_PROXY` / the proxy
  list now, in the same order the resolver does.
* **A walled IP says so.** "no mirror had a downloadable URL" explained
  nothing; when the resolver knows YouTube is refusing this server, the failure
  names that and points at `YOUTUBE_PROXY`.
* **The boot log summarises the last run instead of reprinting it.** Restoring
  60 rows verbatim pushed this run's own lines off a phone-sized `/logs`; it is
  now one line per distinct message with a `×N`, capped at a dozen.
* **yt-dlp has a modern floor.** YouTube rotates its player response every few
  weeks and an old extractor answers "Failed to extract any player response"
  for *every* video, which reads like a network fault.

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

**Six buttons, not twelve.** The now-playing message arrived under four rows of
keyboard — pause, skip, stop, −15s, volume, +15s, loop, shuffle, queue, save,
lyrics, close — which on a phone is a keyboard with a card attached to it. It
is now the shape Videl and Shizu ship: `[Pause][Skip][Stop]` /
`[Loop off][Queue][Close]`. Everything that moved is still a command — `/seek`,
`/volume`, `/shuffle`, `/fav`, `/lyrics` — and the rich panel carries the same
six coloured buttons inside the message.

The progress bar was drawn with `█` and `▬`, which iOS renders as a solid
highlight and a hairline: one bright square, a dot, then a long grey rule. It
is now `━` / `─` / `●`, which reads as a bar on every client. And when the
poster cannot be drawn (no Pillow, no font, a render bug), the chat gets the
song's **cover art** as the picture instead of dropping to a text card.

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
