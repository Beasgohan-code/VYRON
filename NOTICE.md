# Third-party notices

VYRON is its own codebase, but it stands on a lot of open source. This file
records what was studied or adapted, and it exists because the MIT licence
requires the original copyright notices to travel with derived work — branding
stays VYRON, credit stays with the people who wrote the code we learned from.

## Adapted / studied

| Project | Licence | What VYRON took |
| --- | --- | --- |
| [ShizuMusic](https://github.com/Badmunda05/ShizuMusic) — © 2026 Bad Munda | MIT | Autoplay behaviour (mood/language lanes, candidate de-duplication), voice-chat update handling, channel-play semantics and several command layouts. Rewritten for VYRON's queue/player, not copied module-for-module. |
| [Eldian Music API](https://github.com/Eldian-Network/eldian-music-api) — © 2026 Eldian Network | MIT | The public API contract kept at `/v1/track/by-video-id`, `/v1/info/by-video-id` and `/v1/key`, plus the "one key, one audio file" flow. VYRON's engine around it (client ladder, mirror fallback, job API, cache) is its own. |
| [Videl](https://github.com/Beasgohan-code/Videl) | see repository | Command vocabulary and bot UX that VYRON was originally based on. |

## Dependencies

| Project | Licence |
| --- | --- |
| [Pyrogram](https://github.com/pyrogram/pyrogram) | LGPL-3.0 |
| [py-tgcalls](https://github.com/pytgcalls/pytgcalls) | LGPL-3.0 |
| [richgram](https://github.com/Badmunda05/richgram) | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Unlicense |
| [aiohttp](https://github.com/aio-libs/aiohttp) | Apache-2.0 |
| [Pillow](https://github.com/python-pillow/Pillow) | HPND |
| [Motor](https://github.com/mongodb/motor) / [PyMongo](https://github.com/mongodb/mongo-python-driver) | Apache-2.0 |
| [React](https://github.com/facebook/react) / [Vite](https://github.com/vitejs/vite) / [three.js](https://github.com/mrdoob/three.js) / [anime.js](https://github.com/juliangarnier/anime) | MIT |

If you fork VYRON, keep this file — and keep the upstream `LICENSE` files of
anything you vendor in full.
