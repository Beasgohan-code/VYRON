# VYRON Player — Mini App

This folder is the entire web UI. **Swap it freely** — the backend only needs the
API contract below to keep working.

```
webapp/
├── index.html      # shell + tabs (Player · Queue · Search · Settings)
├── styles.css      # dark glass theme, violet→cyan accent
├── app.js          # state polling, actions, Telegram theme/haptics
└── README.md       # this file
```

Served at **`/app`** by the same aiohttp server that exposes `/health`
(`vyron/web/server.py`). No build step, no framework, no bundler.

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

| Method | Path | Body | Returns |
|---|---|---|---|
| `GET` | `/api/info` | – | app name, version, auth requirement |
| `POST` | `/api/state` | – | `user`, `chat`, `now`, `queue[]`, `settings`, `favorites[]` |
| `POST` | `/api/action` | `{action, value}` | action result |
| `POST` | `/api/auth` | – | `{token}` scoped to the current chat |

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
| `favorite` | – | saves the current track |
| `search` | `"query"` | returns `results[]` |

---

## Replacing this UI

1. Replace `index.html`, `styles.css`, `app.js` (any framework, just keep the
   files or point `WEBAPP_DIR` at another folder).
2. Call `POST /api/state` for data and `POST /api/action` for commands.
3. Include `telegram-web-app.js` and send `Telegram.WebApp.initData` in
   `X-Init-Data` so authentication keeps working.
4. In non-Telegram browsers the page falls back to read-only demo data — handy
   for previewing a design without deploying.

Nothing else in the bot needs to change.
