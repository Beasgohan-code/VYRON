# VYRON Player — Mini App

This folder is the entire web UI. **Swap it freely** — the backend only needs the
API contract below to keep working.

```
webapp/
├── index.html          # shell: sidebar · views · now-playing rail · mobile tabbar
├── styles.css          # design tokens, 3 themes, 6 accents, 3 breakpoints
├── app.js              # routing, rendering, actions, Telegram bridge
├── assets/covers/      # 10 procedural covers (fallback artwork)
└── README.md           # this file
```

Served at **`/app`** by the same aiohttp server that exposes `/health`
(`vyron/web/server.py`). No build step, no framework, no bundler, no network
needed for the demo mode.

---

## Views

| View | Anchors | What it shows |
|---|---|---|
| **Home** | `#view-home` | greeting hero, 🔥 Trending (ranked cards), ✨ Made For You mixes, mood chips, quick-search panel, download panel with quality radios, Listen Together panel, library + recently played |
| **Search** | `#view-search` | search bar, filter tabs (all/songs/artists/playlists), result rows with play / queue / menu, recent searches |
| **Library** | `#view-library` | stat tiles, tabs (liked/playlists/history), export to JSON |
| **Queue** | `#view-queue` | now-playing row, queued rows, autoplay switch, jump/remove per row |
| **Playlists** | `#view-playlists` | 2×2 cover mosaic cards, detail panel, play-all, create/delete |
| **Rooms** | `#view-rooms` | live voice chats: cover, listeners, playing state, open-in-Telegram |
| **Profile** | `#view-profile` | avatar card, theme cards (Beat / Telegram / System), accent dots, playback switches, loop, volume, effects chips, integration + about |

Desktop layout is a 3-column grid (`sidebar · content · rail`); the rail holds
the Now Playing card, transport, waveform and quick actions. Below 1180 px the
rail folds away, below 820 px the sidebar becomes a floating tabbar plus a mini
player. Everything is keyboard-accessible: `/` focuses search, `Space` toggles
playback, `N` skips, `Esc` closes the modal.

---

## How a user reaches it

| Entry point | Result |
|---|---|
| `/app` command in a chat | card with an **Open player** button containing a signed chat token |
| Bot menu button | opens `WEBAPP_URL/app/` for that user |
| Inline buttons on cards | navigation inside the app |

Set `WEBAPP_URL=https://your-domain` in `.env` (Render/Koyeb give you one).
Without it the bot stays in chat-only mode and `/app` explains what to set.

---

## API contract

All endpoints return JSON. Authentication, in order of preference:

1. `X-Vyron-Token: <token>` — HMAC-signed `{chat, user, exp}` (from `/app` links).
   Lets the Mini App steer a **group** player.
2. `X-Init-Data: <Telegram.WebApp.initData>` — standard Mini App verification.
3. `WEBAPP_ALLOW_ANON=true` — development only.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/api/info` | – | `name`, `bot`, `version`, `auth_required`, `streaming` |
| `GET` `POST` | `/api/state` | – | `user`, `chat`, `now`, `queue[]`, `settings`, `favorites[]`, `history[]`, `playlists[]`, `version`, `bot` |
| `GET` | `/api/home` | – | `hero`, `trending[]`, `shelves[]`, `moods[]` |
| `POST` | `/api/search` | `{query, limit}` | `results[]` |
| `GET` | `/api/mix` | `?key=daily\|chill\|…` | `tracks[]` |
| `GET` | `/api/rooms` | – | `rooms[]` (`chat_id`, `title`, `username`, `listeners`, `playing`, `paused`, `track`, `volume`, `effects`) |
| `GET` | `/api/playlists` | – | `playlists[]` (`id`, `name`, `count`, `duration`, `covers[]`, `tracks[]`) |
| `POST` | `/api/action` | `{action, value}` | action result |
| `POST` | `/api/auth` | – | `{token}` scoped to the current chat |

Every track object has the same shape everywhere:

```json
{
  "id": "dQw4w9WgXcQ", "title": "…", "uploader": "…", "duration": 213,
  "thumbnail": "https://…", "source": "youtube", "url": "https://youtu.be/…",
  "query": "title uploader", "index": 3
}
```

`thumbnail` may be empty — the UI then maps the track to one of
`assets/covers/*.jpg`. Images that fail to load fall back the same way, which is
what makes demo mode (no network) look complete.

### `now` object

```json
{
  "id": "dQw4w9WgXcQ", "title": "…", "uploader": "…", "duration": 213,
  "thumbnail": "https://…", "source": "youtube", "requested_by": "Bob",
  "url": "https://youtu.be/…", "elapsed": 74.2, "progress": 0.348,
  "paused": false, "volume": 100, "loop": "off"
}
```

### Actions

| `action` | `value` | Notes |
|---|---|---|
| `play` | `"query or url"` | resolves and streams, or queues |
| `play_now` / `play_next` | `"query or url"` | start immediately / insert at #1 |
| `pause` / `resume` / `toggle` | – | transport |
| `skip` | `number` (default 1) | |
| `stop` | – | ends session, leaves VC |
| `seek` | seconds | |
| `volume` | `1…200` | |
| `loop` | `off` \| `one` \| `all` | |
| `shuffle` / `clear` | – | queue ops |
| `remove` | index (1-based) | |
| `move` | `{from, to}` | |
| `jump` | index (1-based) | plays immediately |
| `autoplay` / `always` | – | toggles |
| `effects` | `["bass", …]` | max 3, returns `labels` |
| `favorite` | – | saves the current track |
| `favorite_track` / `unfavorite` | track object / media id | library |
| `playlist_create` | `"name"` | returns `playlist` |
| `playlist_delete` | `"id"` | |
| `playlist_add` | `{playlist_id, track}` | |
| `playlist_remove` | `{playlist_id, id}` | |
| `playlist_play` | `"id"` | queues up to 60 tracks |
| `search` | `"query"` | returns `results[]` |
| `download` | `{query, kind}` | `kind`: `audio` \| `video`; the bot sends the file |

Unknown actions return **400** with the full list of accepted names, and a
missing player returns **503** — the UI shows both as a toast.

---

## Replacing this UI

1. Replace `index.html`, `styles.css`, `app.js` (any framework, just keep the
   files or point `WEBAPP_DIR` at another folder).
2. Read `/api/state` (poll it — the app polls every 5 s while visible) and
   `/api/action` for commands. Add `/api/home`, `/api/rooms`, `/api/playlists`
   when you want discovery, rooms and playlists.
3. Include `telegram-web-app.js` and send `Telegram.WebApp.initData` in
   `X-Init-Data` so authentication keeps working.
4. In non-Telegram browsers the page falls back to read-only demo data — handy
   for previewing a design without deploying (`python -m vyron.tools.preview`).

Nothing else in the bot needs to change.
