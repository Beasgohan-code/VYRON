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

### 2 · Create the assistant session

The **assistant** is a normal Telegram account (not a bot) — it is the one that
joins voice chats. Run this once:

```bash
python -m vyron.tools.session
```

It prints a `STRING_SESSION=…` line. Keep it secret — it is full account access.

### 3 · Configure

```bash
git clone https://github.com/Beasgohan-code/VYRON.git
cd VYRON
cp .env.example .env
# edit .env → BOT_TOKEN, API_ID, API_HASH, STRING_SESSION, OWNER_ID
```

### 4 · Run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt install ffmpeg -y        # required by yt-dlp / ntgcalls
python main.py
```

Health check → <http://localhost:8080/health>

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
| `/np` | refresh the now-playing card |

### Queue

`/queue [page]` · `/remove 3` · `/move 3 1` · `/jump 2` · `/clear`

### Tools

`/lyrics` · `/fav` · `/favs` · `/history` · `/settings` · `/247` · `/stats` · `/ping` · `/id` · `/emojis`

### Owner only

`/broadcast <text>` · `/leaveall` · `/cleanup` · `/active` · `/emojireload`

Everything above also works from the inline buttons on the now-playing card.

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

The image is multi-stage-slim, runs as a non-root user, includes ffmpeg, and
has a built-in healthcheck.

### Render

1. **New → Blueprint**, pick this repo (it reads `render.yaml`).
2. Fill the secrets (`BOT_TOKEN`, `API_ID`, `API_HASH`, `STRING_SESSION`, `OWNER_ID`).
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
│   │   └── pending.py          # short-lived picker state
│   ├── ui/
│   │   ├── theme.py            # premium-emoji engine + glyph map
│   │   ├── rich.py             # rich ↔ HTML delivery lanes, escaping, fallbacks
│   │   ├── cards.py            # every screen, declaratively
│   │   ├── keyboards.py        # all inline buttons
│   │   └── progress.py         # bars, durations, human formatting
│   ├── modules/                # start, play, controls, queue, settings, tools, admin, callbacks
│   ├── utils/                  # helpers, filters, net, health server
│   └── tools/                  # session generator, emoji pack builder
└── tests/                      # 44 offline tests
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

Only five values are required (`BOT_TOKEN`, `API_ID`, `API_HASH`, `STRING_SESSION`,
`OWNER_ID`). The interesting optional ones:

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
| `PORT` | `8080` | health server |

Full list with comments: [`.env.example`](.env.example).

---

## 🧪 Tests

```bash
pip install pytest pytest-asyncio
python -m pytest tests -q      # 44 passed
```

Covered offline: duration parsing, progress bars, loop semantics, queue
add/dedupe/limit/remove/move/shuffle/rotate, elapsed-time maths, pending-picker
TTL, rich↔HTML conversion, escaping, card rendering, keyboard wiring,
handler registration and client construction.
CI runs the same suite on Python 3.11 and 3.12.

---

## 🩺 Troubleshooting

| Symptom | Fix |
|---|---|
| `Start a voice chat in this group first` | The group has no active VC — start one (or `/vplay` after starting). |
| Assistant joins but is silent | The **assistant** needs *manage voice chats*; give the bot admin too. |
| `Could not resolve that track` | YouTube changed something → `pip install -U yt-dlp`; for age-gated videos set `COOKIES_FILE`. |
| Bot replies "already in use" | Two instances with the same `STRING_SESSION` — run only one. |
| `ntgcalls` import error | Python must be 3.10–3.14 on x86-64/arm64; Docker image handles this. |
| Nothing renders as rich | Server/Kurigram build too old → set `RICH_MESSAGES=false`; everything still works. |
| Health check fails on Render | Keep `PORT=8080` and `runtime: docker` (Render routes to it automatically). |

---

## 🙏 Credits

- [Kurigram](https://github.com/KurimuzonAkuma/kurigram) — Pyrogram fork with the new Bot API surface
- [PyTgCalls](https://github.com/pytgcalls/pytgcalls) + [ntgcalls](https://github.com/pytgcalls/ntgcalls) — the actual voice engine
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — extraction that (mostly) keeps working
- [LRCLIB](https://lrclib.net) — free lyrics API
- UI ideas and the rich-message groundwork from [Videl](https://github.com/Beasgohan-code/Videl) and the broader music-bot ecosystem

## 📄 License

MIT © [Beasgohan-code](https://github.com/Beasgohan-code) — fork it, improve it, keep the credits.

<div align="center">

**VYRON** · built for the voice chat you actually use

</div>
