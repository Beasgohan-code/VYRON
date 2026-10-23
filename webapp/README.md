# VYRON Player — Mini App bundle

`webapp/dist` is the **built** Mini App, served by `vyron/web/server.py` at `/app/`.
The source lives in [`../frontend`](../frontend) — React 18 + TypeScript + Vite,
no UI framework, no CSS framework, one hand-written design system.

```
frontend/                     # source of truth
├── index.html                # shell (mounts #root, loads telegram-web-app.js)
├── vite.config.ts            # base /app/static/ · outDir ../webapp/dist
└── src/
    ├── main.tsx              # React root + AppProvider
    ├── App.tsx               # shell: sidebar · views · rail · modal · toast
    ├── styles.css            # tokens, themes, accents, components, breakpoints
    ├── lib/
    │   ├── api.ts            # typed fetch client, Telegram bridge, haptics
    │   ├── store.tsx         # context: data, polling, actions, UI prefs
    │   ├── types.ts          # every API payload
    │   └── format.ts         # durations, greeting, cover hashing
    ├── components/           # Sidebar, Topbar, NowPlayingRail, MobileChrome,
    │                         # TrackCard, ResultRow, Panel, Modal, SessionGate,
    │                         # Cover (procedural SVG art), WaveSeek (scrubber)
    └── views/                # Home, Search, Player, Library, Queue, Playlists,
                              # Rooms, Profile, Api

webapp/
├── dist/                     # ← what is served (committed so plain `python main.py` works)
└── README.md                 # this file
```

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 with HMR (API proxied to :8099)
npm run build    # typecheck + bundle → ../webapp/dist
npm run typecheck
```

The Docker image builds the frontend in a `node:22-alpine` stage, so deployments
never need Node locally.

---

## Views

| View | What it shows |
|---|---|
| **Home** | greeting hero with live stats, 🔥 Trending (ranked cards), ✨ Made For You mix shelves, mood chips, quick-search panel, download panel with quality radios, Listen Together panel, library + recently played, CTA strips |
| **Search** | search bar, filter tabs (All / Songs / Playlists / Artists), result rows with play · queue · menu, artist grid, recent searches |
| **Library** | stat tiles, Liked / Playlists / Recently played tabs, liked-hero card, JSON export, playlist shelf |
| **Queue** | now-playing row, queued rows with jump/remove, autoplay switch, shuffle/clear actions, state hint |
| **Playlists** | cover mosaic cards, detail panel with play-all/delete, empty states |
| **Rooms** | live voice chats with cover, listeners, volume/effects chips, open-in-Telegram, how-it-works |
| **Music API** | base URL, live status, key list with usage, create/revoke, endpoint table, cURL/Python/Node snippets, links to `/v1/docs` and OpenAPI |
| **Profile** | avatar card, theme cards (Beat / Telegram / System), accent dots, playback switches, loop + volume, effects chips, keyboard shortcuts, developers card, Telegram integration, local-data reset |

Desktop is a 3-column grid (`sidebar · content · rail`) with a sticky now-playing
card and an always-on player dock; below 1240 px the rail folds away, below
860 px the sidebar becomes a floating tabbar plus a mini player.

Keyboard: `⌘K`/`Ctrl+K` command palette · `?` shortcuts · `/` search ·
`Space` play/pause · `←`/`→` seek · `N` next · `M` mute · `Esc` close.

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

1. `X-Owner-Token: <vown_…>` — signed owner token from `/apitoken`, valid 30 days.
   Works from any browser (`/app/?ot=…` links) and unlocks the API console.
2. `X-Vyron-Token: <token>` — HMAC-signed `{chat, user, exp}` (from `/app` links).
   Lets the Mini App steer a **group** player.
3. `X-Init-Data: <Telegram.WebApp.initData>` — standard Mini App verification.
4. `WEBAPP_ALLOW_ANON=true` — development only.

`/apitoken` also grants every scope on the public API: send the same value as
`X-Owner-Token` (or `X-API-Key`) against `/v1/*`. Changing `BOT_TOKEN` revokes
every owner token at once.

| Method | Path | Body / query | Returns |
|---|---|---|---|
| `GET` | `/api/info` | – | `name`, `bot`, `version`, `auth_required`, `streaming` |
| `GET` `POST` | `/api/state` | – | `user`, `chat`, `now`, `queue[]`, `settings`, `favorites[]`, `history[]`, `playlists[]`, `version`, `bot` |
| `GET` | `/api/home` | – | `hero`, `trending[]`, `shelves[]`, `moods[]` |
| `POST` | `/api/search` | `{query, limit}` | `results[]` |
| `GET` | `/api/mix` | `?key=daily\|chill\|…` | `tracks[]` |
| `GET` | `/api/rooms` | – | `rooms[]` (`chat_id`, `title`, `username`, `listeners`, `playing`, `paused`, `track`, `volume`, `effects`) |
| `GET` | `/api/playlists` | – | `playlists[]` (`id`, `name`, `count`, `duration`, `covers[]` (real thumbnail URLs from the playlist), `tracks[]`) |
| `POST` | `/api/action` | `{action, value}` | action result |
| `POST` | `/api/auth` | – | `{token}` scoped to the current chat |
| `POST` | `/api/lyrics` | `{title, artist, duration}` | `{text, synced, lines[{time, text}]}` |
| `GET` | `/api/stream/{id}` | Range supported | audio bytes (`audio/mpeg`/`audio/mp4`, Range-aware; falls back to a real cached download when the upstream URL refuses) |
| `GET` `POST` | `/api/keys` | `{action: "create"\|"rotate"\|"revoke", label?, id?, scopes?, days?, rate_limit?}` | `keys[]`, `stats`, `metrics`, `base`, `docs`, `openapi`, `scopes`, `is_owner`, `created` — owner only |

The public music API (`/v1`, keys, `/v1/docs`, OpenAPI) is documented in the
root [README](../README.md#-music-api-v2-on-the-same-url); the Mini App only
needs `base`, `docs`, `openapi`, `keys`, `stats`, `metrics`, `scopes` and
`is_owner` from `/api/keys`.

Every track object has the same shape everywhere:

```json
{
  "id": "dQw4w9WgXcQ", "title": "…", "uploader": "…", "duration": 213,
  "thumbnail": "https://…", "source": "youtube", "url": "https://youtu.be/…",
  "query": "title uploader", "index": 3
}
```

`thumbnail` may be empty, and thumbnails that fail to load are ignored: the UI
draws its own cover art (deterministic SVG mesh gradient seeded from the track
id), so the layout never depends on an image request succeeding.

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

Unknown actions return **400** with the list of accepted names, and a missing
player returns **503** — the UI surfaces both as a toast.

---

## Replacing this UI

1. Build any frontend and drop the output in `webapp/dist` (or point
   `WEBAPP_DIR` at your folder). `index.html` is served for `/app/` and any
   `/app/*` deep link.
2. Read `/api/state` (poll every ~5 s while visible) and call `/api/action`.
   Add `/api/home`, `/api/rooms`, `/api/playlists` for discovery, rooms and lists.
3. Include `telegram-web-app.js` and send `Telegram.WebApp.initData` in
   `X-Init-Data` so authentication keeps working.
4. In non-Telegram browsers there is no `initData`, so the API answers `401`
   (or `503` when a service is not configured) and the app shows a locked state.
   `python -m vyron.tools.preview` runs the same server with the real resolver,
   so a replacement UI can be developed against it.

Nothing else in the bot needs to change.
