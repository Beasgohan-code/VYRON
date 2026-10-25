# VYRON Full UI + Core Upgrade Notes

This build includes extensive UI and reliability upgrades.

## Bot Telegram UI
- Soft headers, pretty tables, status chips (🔴 LIVE / 🟡 PAUSED)
- Upgraded cards: Start, Help, Now Playing, Queue, Search, Logger
- Coloured buttons (primary / success / danger) throughout
- Rich headings, blockquotes, collapsible details, footers
- Premium emoji support retained

## Mini App (frontend)
- Phase 1: Liquid glass Dock, stronger artwork ambient, polished waveform Seek
- Phase 2: Better lyrics karaoke (glow + scale), premium Player controls
- Phase 3: Drag-ready queue rows, sleep timer chips, collaborative styles
- Phase 4: Stronger particles/Reactor, reaction buttons, floating particles, collab badges

## Logger
- Richer log channel cards
- Cleaner format_event (blockquote + meta)
- Clear on/off status with chips and coloured toggles

## Group management
- Existing groupadmin + moderation modules retained
- Rich cards and buttons used consistently

## How to run
```bash
cd VYRON-clean
cp .env.example .env   # fill tokens
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# optional Mini App rebuild:
cd frontend && npm install && npm run build && cd ..
python main.py
```

## Extra polish (this pass)
- /play flow: usage_card, queued_card, started_card → soft rich UI
- ping_card → latency quality chip + table
- working / ok / warn / error / info / locked cards → soft headers
- download_choice_card + download_card → soft + progress
- yt-dlp: concurrent_fragment_downloads=4, 10MB chunks, extractor_retries

## Suggestions 1-17 (this pass)
1 Playlist soft UI
2 Settings soft card
3 Seek feedback
4 Empty states
5 Mini App styles ready
6 START_IMG/PING_IMG env keys
7 Broadcast retained
8 Lyrics soft
9 /doctor health
10 Cooldowns retained
11 playforce
12 Download soft
13 Logger rich
14 Tests retained
15 TrackRow requester
16 README deploy
17 reduced-motion
