<div align="center">

<img src="assets/banner.png" alt="VYRON" width="100%" />

# VYRON

**A Telegram voice-chat music bot that actually looks good.**

Rich cards · premium emoji · instant search · zero-clutter controls

[![Python](https://img.shields.io/badge/python-3.11%20|%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Kurigram](https://img.shields.io/badge/kurigram-2.2.26-2CA5E0?style=for-the-badge&logo=telegram&logoColor=white)](https://github.com/KurimuzonAkuma/kurigram)
[![PyTgCalls](https://img.shields.io/badge/py--tgcalls-2.2.11-8A2BE2?style=for-the-badge)](https://github.com/pytgcalls/pytgcalls)
[![License](https://img.shields.io/badge/license-MIT-22c55e?style=for-the-badge)](LICENSE)

[Quick start](#-quick-start) · [Commands](#-commands) · [Deploy](#-deploy) · [Premium emoji](#-premium-emoji) · [Architecture](#-architecture)

</div>

---

## ✨ What it does

| | |
|---|---|
| 🎧 **Voice-chat streaming** | Lossless-feeling audio (or video) in any group voice chat, auto-started by the assistant account. |
| 🔎 **Search-first UX** | `/play faded` shows the top 5 results with durations — tap one to stream. Links play instantly. |
| 📜 **Real queue** | Add, remove, reorder, jump, shuffle, loop-off/one/all, autoplay related tracks when the queue empties. |
| 💾 **Downloads** | `/song` and `/video` deliver real MP3/MP4 files with cover art, metadata and a disk cache. |
| 📝 **Lyrics** | Synced or plain lyrics pulled from LRCLIB for whatever is playing. |
| ❤️ **Favourites & history** | Per-user, persistent, shown as tidy tables. |
| ⚙️ **Per-chat settings** | Volume, loop mode, autoplay and 24/7 — saved to Mongo or a JSON file. |
| 🛡️ **Admin-first** | Only group admins (and sudo users) can touch playback; everyone can watch. |
| 🚪 **Self-cleaning** | Leaves idle voice chats, expires stream URLs, purges the download cache, survives restarts. |
| 🛡️ **Group management** | ban · kick · mute · warn (auto-ban at the limit) · purge · pin · promote/demote · welcome & goodbye with placeholders. |
| 🔒 **Content locks + anti-flood** | lock media, links, forwards, stickers, bots, commands, NSFW; flood offenders get deleted and muted. |
| 🎛️ **Audio effects** | bass, treble, nightcore, vaporwave, 8D, echo, karaoke, loudness, speed — as a rich toggle panel. |
| 📡 **Channel play** | `/cplay` streams into the linked channel's voice chat. |
| 🔎 **Inline mode** | `@VyronMusicBot <song>` returns shareable results in any chat. |
| 🌐 **Mini App** | A Spotify-style web player served by the bot: local playback with queue/shuffle/repeat, synced lyrics, a ⌘K command palette and full control of the voice-chat stream. |
| 🔌 **Music API** | An Eldian-compatible `/v1` API on the same URL: downloads, streaming, search, metadata, lyrics and metrics, with hashed keys, scopes, expiry, rotation and per-key rate limits. |

### Built on the *new* Telegram Bot API

VYRON renders its static cards as **rich messages** — real headings, tables and
collapsible sections, not walls of bold text:

```html
<h2>🎧 ᴠʏʀᴏɴ — ɴᴏᴡ ᴘʟᴀʏɪɴɢ</h2>
<blockquote>🎶 <b>Track title</b> · 🎤 Artist</blockquote>
<table>
  <tr><td>🔊 Volume</td><td><b>100%</b></td></tr>
  <tr><td>🔁 Loop</td><td><b>Queue</b></td></tr>
</table>
<footer>page 1/3 · autoplay on</footer>
```

- **Rich messages** with automatic downgrade to classic HTML if a server rejects them.
- **Editable rich cards** — paginated queues keep their formatting instead of degrading to text.
- **Premium emoji** rendered as real `custom_emoji` entities (`<tg-emoji emoji-id="…">`).
- **Ephemeral cards** support (messages only one user sees) for per-user feedback in groups.

---

## 🚀 Quick start

### 1 · Collect four credentials

| Value | Where |
|---|---|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `API_ID` / `API_HASH` | [my.telegram.org](https://my.telegram.org) → API development tools |
| `OWNER_ID` | [@userinfobot](https://t.me/userinfobot) |

### 2 · Create the assistant session *(optional)*

The **assistant** is a normal Telegram account (not a bot) — it is the one that
joins voice chats. Run this once when you want voice streaming:

```bash
python -m vyron.tools.session
```

It prints a `STRING_SESSION=…` line. Keep it secret — it is full account access.

**You can skip it to try the bot first.** Without a session VYRON still boots:
`/play`, the search picker and quick actions fall back to **sending the audio
file** into the chat, and everything non-voice (search, cards, lyrics, settings,
playlists, moderation, the Mini App) works normally. Add the session later and
restart to switch streaming on — nothing else changes.

### 3 · Configure

```bash
git clone https://github.com/Beasgohan-code/VYRON.git
cd VYRON
cp .env.example .env
# edit .env → BOT_TOKEN, API_ID, API_HASH (STRING_SESSION + OWNER_ID optional)
```

### 4 · Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt install ffmpeg -y        # required by yt-dlp / ntgcalls

# Mini App (React + Vite) — only needed once, the bundle is committed
cd frontend && npm install && npm run build && cd ..

python main.py
```

Health check → <http://localhost:8080/health> · Mini App → <http://localhost:8080/app/>

> **Group checklist:** add the bot **and** the assistant account, give the bot
> *manage voice chats* + *delete messages*, start the voice chat, then `/play`.

---

## 💬 Commands

### Playback

| Command | What it does |
|---|---|
| `/play <song \| link>` | search & stream audio (or play a link instantly) |
| `/vplay <song \| link>` | stream video |
| `/song <song \| link>` | send the MP3 to the chat |
| `/video <song \| link>` | send the MP4 to the chat |
| `/playlist <url>` | queue up to 50 tracks from a playlist / mix |
| `/search <text>` | browse results without playing |
| `/pause` · `/resume` | hold / continue |
| `/skip [n]` | jump forward |
| `/stop` | end the session and leave the voice chat |
| `/seek 1:30` · `/forward` · `/rewind` | move inside the track |
| `/volume 80` · `/volume +10` | assistant volume (1–200) |
| `/loop [off\|one\|all]` | repeat mode |
| `/shuffle` · `/autoplay` | queue behaviour |
| `/np` | now-playing card (rendered artwork when Pillow is installed) |
| `/suggest [query]` | tracks similar to what's playing — tap to queue |
| `/next <query>` | insert a track at the front of the queue |
| `/qinfo` | queue health: length, remaining time, loop, effects |

### Queue

`/queue [page]` · `/remove 3` · `/move 3 1` · `/jump 2` · `/clear`

### Convenience

| Command | What it does |
|---|---|
| `/timer 30` · `/timer 1h30m` · `/timer off` | stop playback and leave the VC when the timer ends |
| `/random [mood or query]` | play a surprise track from trending, a mood, or a search |
| `/exportpl <name>` | send the playlist as a portable JSON file |
| `/importpl [name]` | reply to that file to restore the playlist |
| `/replay` | start the current track over |
| `/daemons` | housekeeping, watchdog, keep-alive and timer status (owner) |

### Tools

`/lyrics` · `/fav` · `/favs` · `/history` · `/settings` · `/247` · `/stats` · `/ping` · `/id` · `/emojis`
`/whoami` · `/song` · `/vsong` · `/repo`

Videl/Fallen aliases are accepted everywhere they make sense: `/music` (`/start`),
`/listpl`, `/loadpl`, `/rmplaylist`, `/deleteplaylist`, `/delpl`, `/spt`,
`/reboot`, `/gblock`, `/gunblock`, `/ublock`, `/uunblock`.

### Groups & voting

| Command | What it does |
|---|---|
| `/voteskip set <n>` | require *n* votes before a skip (admins; `0` disables) |
| `/vskip` · `/skipvotes` | cast your vote — or tap the **Vote to skip** button (admins skip instantly) |
| `/setvoteskip` | show the current threshold |
| `/cplayset <id\|@name>` | bind a channel for `/cplay` (`off` reverts to the linked chat) |
| `/suggest [query]` | tracks similar to what's playing — tap to queue |
| `/savepl [name]` | save the current track / queue into a playlist |

### Playlists

| Command | What it does |
|---|---|
| `/savepl [name]` | save the current track (or the whole queue, or a replied audio file) into a playlist |
| `/playlists` | list your saved playlists |
| `/pl <name>` | queue a saved playlist |
| `/pldel <name>` | delete one |

Playlists are per-user, capped at 40 lists × 200 tracks, and the same store
feeds the Library view of the web app. (YouTube imports stay on `/playlist`.)

### Diagnostics & owner console

| Command | What it does |
|---|---|
| `/speedtest` | Bot API latency, media-CDN throughput, voice-chat readiness, uptime |
| `/sudoers` | owner + `SUDO_USERS` with resolved names |
| `/eval <code>` | run Python inside the bot process (owner, async aware) |
| `/vars` | configuration snapshot — secrets masked, DM'd in groups |
| `/dbstats` | storage backend, chats, counters, cache size, uptime |
| `/clearcache` | wipe downloads and temp files, report space freed |
| `/dbcleanup 30` | prune history and favourites older than N days |
| `/addsudo` · `/delsudo` | grant or revoke bot access (persisted across restarts) |
| `/sudolist` | owner, env sudoers and runtime grants |
| `/assistant` | profile card of the account that joins voice chats |
| `/setname <first> [last]` | rename the assistant account |
| `/setbio <text>` | change its bio (70 chars) |
| `/setpfp` (reply to a photo) | replace its profile picture |
| `/delpfp` | clear its profile pictures |
| `/gblock` · `/gunblock` · `/ublock` · `/uunblock` | aliases of `/block` & `/unblock` |

Effect shortcuts: `/bass` `/bassoff` `/nightcore` `/nightcoreoff` `/vaporwave` `/vaporwaveoff`
`/effecton <name>` · `/effectoff <name|all>`

The bot also announces itself politely when added to a group (with Play / Web app /
Help buttons) and logs when it is removed.

### Group management

`/ban` · `/unban` · `/kick` · `/mute` · `/unmute` · `/warn` · `/warns` · `/resetwarns`
`/setwarnlimit 3` · `/purge` (reply) · `/pin` · `/unpin` · `/promote` · `/demote`
`/setwelcome …` · `/setgoodbye …` · `/admins`

Placeholders: `{mention}` `{first}` `{chat}` `{id}` `{count}`

### Locks & effects

`/locks` — panel with coloured toggles for media, links, forwards, stickers, bots,
commands and NSFW, plus anti-flood (`/antiflood 7`, `/setflood on|off`).
`/lock media` · `/unlock links`
`/effects` — toggle bass, treble, nightcore, vaporwave, 8D, echo, karaoke,
loudness, mono, double/half speed (max 3 at once, applied from the next track).

### Owner only

`/broadcast <text>` · `/gcast <text>` · `/block <id>` · `/unblock <id>` · `/blocklist`
`/activevc` · `/sysstats` · `/leaveall` · `/cleanup` · `/emojireload` · `/restart`

Everything above also works from the inline buttons on the now-playing card.

---

## 🔌 Music API — v2, on the same URL

A professional music API for *other* bots and apps, served by the same aiohttp
process as `/health` and the Mini App — **one deploy, one URL, no second
service**. The legacy wire format from
[`Eldian-Network/eldian-music-api`](https://github.com/Eldian-Network/eldian-music-api)
still works (`POST /v1/track/by-video-id` + `X-API-Key` returns audio), and the
canonical routes add metadata, streaming, scopes, expiry and metrics.

| Method | Path | What it does | Scope |
| --- | --- | --- | --- |
| `POST` | `/v1/tracks` | download audio by id, URL or query | `download` |
| `GET` | `/v1/tracks/{video_id}` | metadata, no download | `read` |
| `GET` | `/v1/tracks/{video_id}/stream` | inline stream, HTTP Range | `download` |
| `GET·POST` | `/v1/search?q=` | search YouTube | `search` |
| `GET·POST` | `/v1/lyrics?title=` | lyrics + synced lines (LRCLIB) | `read` |
| `GET` | `/v1/me` | your key, scopes, usage, quota | — |
| `GET·POST` | `/v1/admin/keys` | list / mint keys (raw key returned once) | `admin` |
| `DELETE` | `/v1/admin/keys/{id}` | revoke by id or prefix | `admin` |
| `POST` | `/v1/admin/keys/{id}/rotate` | swap a key, old one dies instantly | `admin` |
| `GET` | `/v1/metrics` | traffic, volume, latency (JSON or Prometheus) | `admin` |
| `GET` | `/v1/health` · `/v1/version` | status, versions | — |
| `GET` | `/v1/docs` · `/v1/openapi.json` | docs page · OpenAPI 3.1 | — |
| `POST` | `/v1/track/by-video-id` | **legacy** Eldian download | `download` |
| `POST` | `/v1/track/by-query` | **legacy** download by query | `download` |
| `GET` | `/v1/info/by-video-id` | **legacy** metadata | `read` |
| `GET` | `/v1/key` | **legacy** key info | — |

```bash
curl -X POST "$WEBAPP_URL/v1/tracks" \
  -H "X-API-Key: vyrn_xxxxxxxx" -H "Content-Type: application/json" \
  -d '{"video_id":"dQw4w9WgXcQ"}' --output track.mp3
```

- **Keys** — `vyrn_` + 40 url-safe characters, stored **hashed** (SHA-256) with a
  12-char prefix for display, so a database dump cannot be replayed. Mint,
  rotate and revoke them with `/getapi [label] [scopes=…] [days=N]`,
  `/listkey`, `/rotatekey`, `/revoke` and `/apiusage`, or from the Mini App's
  **Music API** tab.
- **Scopes** — `read`, `search`, `download`, `admin` (`admin` implies all).
  Defaults are the first three; anything missing returns `403 forbidden_scope`.
- **Limits** — 25 active keys per owner, optional per-key expiry (`days=30`) and
  a per-key rate override (`rate=60`), all visible in `/listkey` and the app.
  Downloads are queued behind a two-slot semaphore so API traffic never starves
  voice-chat playback.
- **Headers** — `X-RateLimit-Limit/Remaining/Reset`, `X-Key-Scopes`,
  `X-API-Version`, `X-Request-Id`, `X-Response-Time`, `Retry-After` on `429`.
- **Errors** — one envelope for everything:
  `{"ok": false, "error": …, "code": "rate_limited", "hint": …, "request_id": …}`
  with codes `missing_key`, `invalid_key`, `revoked_key`, `expired_key`,
  `forbidden_scope`, `invalid_video`, `not_ready`, `rate_limited`,
  `upstream_failed`.
- **Docs** — a branded, self-contained page at `/v1/docs` (endpoint table,
  copy-paste snippets, live status check) plus `/v1/openapi.json` for generated
  clients.
- **Bring your old keys** — keys live in the `api_keys` collection, exactly like
  the upstream project, so pointing `MONGO_DB=eldian_music` at an existing
  Eldian database keeps every key already handed out working (legacy plaintext
  records are accepted and migrated on first use).

### 🔑 Owner access — web app + API

The deployment owner (`OWNER_ID`) can get into both the player and the API from
**any browser**, without a Telegram session:

```text
/apitoken        # bot → signed owner token (30 days, rotated any time)
```

| Where | How |
| --- | --- |
| Web app | open `<WEBAPP_URL>/app/?ot=<token>` (or send `X-Owner-Token`) |
| API | `X-Owner-Token: <token>` — or `X-API-Key: vown_…`; every scope, 120 req/min |
| Mini App | owner sees **Owner tools**, can mint/rotate/revoke keys |

Tokens are HMAC-signed with `BOT_TOKEN`, so changing the bot token revokes every
owner token at once. `/start`, `/app`, `/api` and `/stats` also grow direct
owner links automatically.

```bash
MUSIC_API=true       # serve /v1 on this deployment (default on)
MUSIC_API_OPEN=false # dev only: no key required
MUSIC_API_RATE=30    # requests per minute, per key
MUSIC_API_CORS=true  # allow browser clients from other origins
```

## 🌐 Web app (Telegram Mini App)

A real frontend, not a static page: **React 18 + TypeScript + Vite**, built to
`webapp/dist` and served by the same aiohttp process that answers `/health`.

```bash
WEBAPP_URL=https://your-deployment        # Render/Koyeb URL
# then: /app in chat, or tap the bot's menu button
```

- **Frontend** — `frontend/` (React + TS, `lucide-react` icons, hand-written
  design system in `src/styles.css`). Seven routed views: Home, Search, Library,
  Queue, Playlists, Rooms, Profile — plus a persistent now-playing rail on
  desktop and a mini player + floating tabbar on mobile.
- **Design system** — 3 themes (Beat / Telegram / System) × 6 accents, all
  persisted locally and driven by CSS custom properties; glass panels, ranked
  trending cards, "made for you" mix shelves, mood chips, cover mosaics,
  skeleton loaders and micro-animations.
- **In-app player** — a real audio engine (`src/lib/audio.tsx`): queue, shuffle,
  repeat-one/all, seek, volume with mute, Media Session metadata (lockscreen and
  Android/desktop media keys), plus a persistent desktop dock (`PlayBar`) and a
  full-screen *now playing* view with blurred cover art, synced lyrics and an
  "up next" list. `Space` toggles, `←`/`→` seek 5 s, `n` skips, `m` mutes.
- **Two outputs, one app** — every row can `▶` locally or 📻 into the voice chat;
  the Queue view has *This device* / *Voice chat* tabs so a group stream and your
  own playback can be inspected side by side.
- **Backend** — `vyron/web/` (`aiohttp`) exposes `/api/state`, `/api/action`,
  `/api/home`, `/api/search`, `/api/mix`, `/api/rooms`, `/api/playlists`,
  `/api/lyrics` and streaming audio at `/api/stream/{id}` (HTTP Range, so seeking
  works) over the *same* `Player` the bot uses, so chat and app never disagree.
- **Auth** — Telegram `initData` (HMAC-verified) or a signed chat token, so the
  app can control a *group* player opened from a `/app` link.
- **Swap the UI** — `frontend/` is self-contained; any bundle dropped in
  `webapp/dist` (or set `WEBAPP_DIR`) is served instead. Contract:
  [`webapp/README.md`](webapp/README.md).

```bash
# dev loop with hot reload (API proxied to the preview server)
cd frontend && npm run dev            # → http://localhost:5173
python -m vyron.tools.preview --port 8099   # API + demo data
```

Preview the built bundle without any credentials:

```bash
python -m vyron.tools.preview --port 8080   # → http://localhost:8080/app/
```

Outside Telegram the page renders read-only demo data — with local gradient
covers, so the whole layout (shelves, moods, rooms, playlists) is visible even
with no network access. Regenerate those covers after palette changes:

```bash
python -m vyron.tools.covers
```

---

## 🎨 Premium emoji

VYRON ships a full unicode fallback set, so it looks good with **zero setup**.
To light up the animated custom-emoji look, build a pack:

```bash
python -m vyron.tools.emoji_fetch --pack your_emoji_pack
# ✔ 34/57 glyphs matched · wrote emoji.json
```

The tool matches the pack's emoji characters against VYRON's glyph map
(`vyron/ui/theme.py`), so a partially-covering pack is fine — anything missing
silently falls back to unicode. Restart, or send `/emojireload`.

Custom `emoji.json` elsewhere? Set `PREMIUM_EMOJI_FILE=/path/to/emoji.json`.
Disable entirely with `PREMIUM_EMOJI=false`.

---

## 📦 Deploy

### Docker (recommended)

```bash
docker compose up -d --build
docker compose logs -f
```

Two stages: `node:22-alpine` builds the Mini App, then `python:3.12-slim-bookworm`
installs ffmpeg + deps, copies the bundle into `webapp/dist`, runs as a non-root
user and ships a healthcheck. No local Node install is required for deploys.

### Render

1. **New → Blueprint**, pick this repo (it reads `render.yaml`).
2. Fill the secrets (`BOT_TOKEN`, `API_ID`, `API_HASH`; `STRING_SESSION` and
   `OWNER_ID` can stay empty for a file-only test deploy).
3. Deploy — the service is a **web service** so Render keeps it alive and
   `/health` is polled automatically.

### Koyeb / Railway / Fly

Any of them: build from the `Dockerfile`, set the same env vars, expose
`$PORT` (8080 by default), and mount a volume at `/app/data`.

### Plain VPS

```bash
pip install -r requirements.txt
python main.py            # or: systemd unit + Restart=always
```

---

## 🧱 Architecture

```
VYRON/
├── main.py                     # entrypoint
├── vyron/
│   ├── __main__.py             # bootstrap, signal handling, graceful shutdown
│   ├── config.py               # every env knob, typed + validated
│   ├── clients.py              # bot + assistant clients, VC bootstrap
│   ├── runtime.py              # shared service container
│   ├── database.py             # MongoDB or JSON, one async interface
│   ├── core/
│   │   ├── queue.py            # Track, ChatState, LoopMode, QueueManager
│   │   ├── player.py           # streaming engine + now-playing ticker
│   │   ├── search.py           # yt-dlp search / stream resolution / autoplay
│   │   ├── downloader.py       # MP3/MP4 cache
│   │   ├── lyrics.py           # LRCLIB client
│   │   ├── charts.py           # trending / mixes / moods (TTL-cached)
│   │   ├── votes.py            # group vote-skip tallies
│   │   ├── acl.py              # runtime sudo roster (/addsudo)
│   │   ├── maintenance.py      # periodic downloads + DB sweep
│   │   ├── keepalive.py        # self-ping so free hosts stay awake
│   │   ├── watchdog.py         # reconnects a dropped bot/assistant client
│   │   ├── timers.py           # /timer parsing + per-chat sleep timers
│   │   ├── playlists.py        # per-user saved playlists
│   │   └── pending.py          # short-lived picker state
│   ├── ui/
│   │   ├── theme.py            # premium-emoji engine + glyph map
│   │   ├── rich.py             # rich ↔ HTML delivery lanes, escaping, fallbacks
│   │   ├── cards.py            # every screen, declaratively
│   │   ├── keyboards.py        # all inline buttons
│   │   └── progress.py         # bars, durations, human formatting
│   ├── modules/                # start, play, controls, queue, settings, tools, effects,
│   │                           # channel, moderation, locks, admin, extras, inline, callbacks,
│   │                           # smartqueue, savedplaylists, diagnostics, power,
│   │                           # assistant_tools, convenience
│   ├── web/                    # Mini App: auth, JSON API, /v1 music API
│   ├── utils/                  # helpers, filters, net, health server, artwork renderer
│   └── tools/                  # session generator, emoji pack builder, cover generator, preview
├── frontend/                   # React + TS + Vite Mini App (src/views · src/components · src/lib)
├── webapp/dist/                # built bundle served at /app (regenerate with npm run build)
└── tests/                      # 160 offline tests
```

**Design rules**

1. **The UI never crashes a command.** Every send has a plain-HTML fallback and every
   button is wrapped by a router that swallows exceptions and reports them to the user.
2. **Nothing blocks the loop.** yt-dlp, pymongo and file work run in worker threads.
3. **The queue is pure.** `core/queue.py` has no Telegram imports — which is why it is
   fully unit-tested.
4. **State survives restarts.** Per-chat settings live in Mongo/JSON; caches are rebuilt lazily.

---

## ⚙️ Configuration

Only three values block startup (`BOT_TOKEN`, `API_ID`, `API_HASH`). These two
are optional and only switch a feature off:

| Variable | Without it |
|---|---|
| `STRING_SESSION` | **file-only mode** — `/play` sends the audio file instead of streaming into the voice chat |
| `OWNER_ID` | no owner — owner commands (`/eval`, `/vars`, `/sudoers`) stay locked; group admins keep control of their own chats |

The interesting optional ones:

| Variable | Default | Purpose |
|---|---|---|
| `AUDIO_QUALITY` | `high` | `low` / `medium` / `high` |
| `VIDEO_QUALITY` | `720p` | `360p` … `1080p` |
| `DEFAULT_VOLUME` | `100` | 1–200 |
| `MAX_QUEUE_SIZE` | `100` | per chat |
| `IDLE_LEAVE_SECONDS` | `300` | leave an idle VC (`0` = never) |
| `AUTOPLAY` | `true` | related tracks when the queue ends |
| `COOKIES_FILE` | – | `cookies.txt` for age-restricted videos |
| `PROXY` | – | `http://…` / `socks5://…` for yt-dlp |
| `MONGO_URL` | – | persistence (JSON file otherwise) |
| `PREMIUM_EMOJI_FILE` | `./emoji.json` | custom emoji pack |
| `RICH_MESSAGES` | `true` | rich cards (set `false` for plain HTML) |
| `KEEPALIVE_MINUTES` | `10` | ping our own `/health` + `/app/` so free hosts don't sleep (`0` = off) |
| `KEEPALIVE_URL` | `RENDER_EXTERNAL_URL` | public URL to ping on Koyeb/Railway |
| `WATCHDOG_SECONDS` | `60` | reconnect the bot/assistant if the socket drops (`0` = off) |
| `MAINTENANCE_HOURS` | `6` | prune downloads + old DB rows every N hours (`0` = off) |
| `MAINTENANCE_DAYS` | `30` | history/favourites older than this are pruned |
| `PORT` | `8080` | health server |

Full list with comments: [`.env.example`](.env.example).

---

## 🧪 Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests -q      # 160 passed

cd frontend && npm test        # 5 component tests (vitest + jsdom)
```

Covered offline: duration parsing, progress bars, loop semantics, queue
add/dedupe/limit/remove/move/shuffle/rotate, elapsed-time maths, pending-picker
TTL, rich↔HTML conversion, escaping, card rendering, keyboard wiring, coloured
button markup, effect filter chains, lock panels, welcome placeholders,
Mini App auth (initData HMAC + signed tokens), the whole JSON API surface
(state/home/search/mix/rooms/playlists/actions), playlist storage round-trips,
chart caching, generated artwork, handler registration and client construction.
The Mini App has its own component suite (render, navigation, search, accent
persistence, modals, file-mode badge, keyboard shortcuts). CI runs both on
Python 3.11/3.12 and Node 22, and builds + smoke-tests the Docker image.

---

## 🫀 Staying alive

Two background loops keep a long deployment honest:

- **Keep-alive** — every `KEEPALIVE_MINUTES` the bot GETs `{public}/health` and
  `{public}/app/`. Render sets `RENDER_EXTERNAL_URL` for you; on Koyeb or
  Railway set `KEEPALIVE_URL=https://your-service`. This stops a free instance
  from sleeping (and waking to a cold-start delay in Telegram).
- **Watchdog** — every `WATCHDOG_SECONDS` it checks that the bot client is
  connected, calls `get_me()`, and reconnects (`stop()` → `start()`) if the
  socket died. Two consecutive timeouts trigger a reconnect. The assistant is
  only checked while streaming is enabled.

Both report into `GET /health` (`watchdog`, `keepalive` objects) and into the
owner-only `/daemons` card.

---

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| `Start a voice chat in this group first` | The group has no active VC — start one (or `/vplay` after starting). |
| Bot sends files instead of streaming | Expected without `STRING_SESSION` (file-only mode) — add a session and restart to stream. |
| Assistant joins but is silent | The **assistant** needs *manage voice chats*; give the bot admin too. |
| `Could not resolve that track` | YouTube changed something → `pip install -U yt-dlp`; for age-gated videos set `COOKIES_FILE`. |
| Bot replies "already in use" | Two instances with the same `STRING_SESSION` — run only one. |
| Docker build: `error: No such file or directory: 'gcc'` | TgCrypto has no cp312 wheel; the image compiles it in its own stage. Rebuild without cache (`docker compose build --no-cache`). |
| MongoDB falls back to JSON | `MONGO_URL` must start with `mongodb://` or `mongodb+srv://`; whitelist the host in Atlas → Network Access. The bot keeps running on JSON storage meanwhile. |
| `PEER_ID_INVALID` on boot | The owner never opened a chat with the bot — send `/start` once; the boot card then arrives next time. |
| Mini App asleep / slow first load | Keep-alive is off — set `KEEPALIVE_URL` (or deploy on Render, where it is automatic). |
| `ntgcalls` import error | Python must be 3.10–3.14 on x86-64/arm64; Docker image handles this. |
| Nothing renders as rich | Server/Kurigram build too old → set `RICH_MESSAGES=false`; everything still works. |
| Health check fails on Render | Keep `PORT=8080` and `runtime: docker` (Render routes to it automatically). |

---

## 📄 License

MIT © [Beasgohan-code](https://github.com/Beasgohan-code) — fork it, improve it, ship it.

<div align="center">

**VYRON** · built for the voice chat you actually use

</div>
