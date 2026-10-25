# VYRON vs ShizuMusic vs Videl vs FallenMusic

A file-by-file and command-by-command comparison, as of **2026-10-25**
(VYRON 1.10.17). Every file in the other three repositories is listed below with
its purpose, the VYRON file that answers it, and a verdict. Every command they
register is listed with its VYRON equivalent. Nothing is skipped, including the
things judged unnecessary — the point of the exercise is that nothing is quietly
missing.

| repo | files | lines | command names |
|---|---|---|---|
| **VYRON** | 124 | 40,306 | 163 |
| ShizuMusic | 49 | 10,232 | 51 |
| Videl | 45 | 10,169 | 78 |
| FallenMusic | 39 | 3,447 | 44 |

### Verdicts

| verdict | meaning |
|---|---|
| **same** | the same capability, at least as deep |
| **better** | VYRON does what the file does, and more |
| **merged** | VYRON folds several of their files into one (fewer moving parts) |
| **absent (deliberate)** | the capability is refused on purpose — reason given |
| **n/a** | packaging/boilerplate with nothing to port |

Standing owner rules applied throughout: **no new commands** (extend existing
commands, buttons and the Mini App), ≤6 buttons per card, no `█`/`▬` progress
glyphs, every message is a Rich card, no credits or footers, the assistant
leaves when the queue ends.

---

# 1. ShizuMusic (49 files, 10,232 lines)

## 1.1 Files

| file | lines | what it does | VYRON counterpart | verdict |
|---|---|---|---|---|
| `main.py` | 3 | calls `ShizuMusic.__main__` | `main.py` | n/a |
| `config.py` | 70 | env → module constants, fail fast | `config.py` (349) — typed settings, sane defaults, never crashes on a missing optional | better |
| `ShizuMusic/__init__.py` | 57 | bot + assistant clients, logger | `clients.py` (134) + `runtime.py` (177) — both clients, ordered shutdown | better |
| `ShizuMusic/__main__.py` | 254 | boot, keep-alive server, `/health`, owner message on start | `__main__.py` (535) + `core/keepalive.py` + `utils/health.py` | better |
| `ShizuMusic/core/__init__.py` | 13 | package marker | — | n/a |
| `ShizuMusic/core/autoplay.py` | 1938 | next-song picking: mood/language filters, buffer refill, history dedupe | `core/autoplay.py` (487) + `core/charts.py` (327) + `core/ytmusic.py` (280) + the `prefetched` lane in `core/player.py` | same — same idea (lane filters, dedupe, refill); theirs is longer only because it inlines its own YouTube search |
| `ShizuMusic/core/call.py` | 184 | join/leave helpers, start/stop stream, mute | `core/player.py` (1481) `_ensure_call` / `leave` / `play_track` | better — also unblocks a call it did not start and re-invites an assistant that was kicked |
| `ShizuMusic/core/channels.py` | 93 | channel ↔ group coupling, `/setchannel` | `modules/channel.py` (735) + `core/chatcfg.py` (138) | better — full `/c*` command family, not just linking |
| `ShizuMusic/core/player.py` | 510 | now-playing card, progress edits, `MediaStream` construction | `core/player.py` (1481) + `ui/nowplaying.py` (276) + `ui/progress.py` (176) | better — poster message, recovery mid-song, prefetch |
| `ShizuMusic/core/queue.py` | 85 | lists of dicts per chat | `core/queue.py` (303) — `Track`/`ChatState` dataclasses, loop, shuffle, move, snapshot | better |
| `ShizuMusic/core/watcher.py` | 21 | one `watchdog()` loop | `core/watchdog.py` (150) + `core/lease.py` (227) + `core/maintenance.py` (111) | better — watchdog, single-owner lease, housekeeping are separate concerns |
| `ShizuMusic/database.py` | 79 | Mongo client singleton | `database.py` (912) — Mongo **and** JSON/embedded, migrations, retention | better |
| `ShizuMusic/modules/__init__.py` | 39 | imports every handler module | `modules/__init__.py` (90) + `core/commandlist.py` (63) | better — a module that fails to import is reported, not fatal |
| `ShizuMusic/modules/autoplay.py` | 150 | `/autoplay`, `/cautoplay` | `modules/controls.py` (402) + `modules/channel.py` | same |
| `ShizuMusic/modules/block.py` | 277 | `/gblock` `/gunblock` `/ublock` `/uunblock` `/blocklist` | `modules/extras.py` (318) | same |
| `ShizuMusic/modules/bot.py` | 193 | greet on add, goodbye on remove, owner log on boot | `modules/presence.py` (125) + `modules/logs_cmd.py` | better — on removal VYRON also stops playback, leaves the call and **deletes the chat's stored settings** |
| `ShizuMusic/modules/broadcast.py` | 289 | `/broadcast` `/gcast` with flags | `modules/admin.py` (278) | better — confirmed, batched, resumable |
| `ShizuMusic/modules/callbacks.py` | 372 | every `v:`-style button | `modules/callbacks.py` (1036) | better |
| `ShizuMusic/modules/channel.py` | 208 | `/addchannel` `/delchannel` `/setchannel` `/removechannel` | `modules/channel.py` (735) | better — `/cplay` `/cplayset` `/cskip` `/cseek` `/cvolume` … (14 commands) |
| `ShizuMusic/modules/effects.py` | 444 | `/effects` speed/bass/8D, applied by re-downloading | `modules/effects_cmd.py` (262) + `core/effects.py` (132) | better — presets applied to the live stream (re-opened at the current second), not re-fetched |
| `ShizuMusic/modules/language.py` | 111 | `/language` `/lang` `/setlang` | `modules/language.py` (99) + `core/i18n.py` (298) | same |
| `ShizuMusic/modules/logtoggle.py` | 86 | `/logger` on/off | `modules/logs_cmd.py` (234) + `core/journal.py` (551) | better — ring buffer, `/logs`, scopes, export |
| `ShizuMusic/modules/misc.py` | 134 | `/id` `/repo` | `modules/start.py` (451) | same |
| `ShizuMusic/modules/pause.py` | 60 | `/pause` `/cpause` | `modules/controls.py` | merged |
| `ShizuMusic/modules/ping.py` | 163 | `/ping` `/speedtest` `/spt` | `modules/start.py` `/ping` + `modules/doctor.py` (395) | better for `/ping`; `/speedtest` absent (deliberate) |
| `ShizuMusic/modules/play.py` | 341 | search → download → play, one edited status card | `modules/play.py` (1032) | better — links, playlists, replied files, candidates, `/song` upload |
| `ShizuMusic/modules/playforce.py` | 166 | `/playforce` family (skips permissions) | — | **absent (deliberate)**: owner deleted force-play |
| `ShizuMusic/modules/playlist.py` | 488 | `/pcreate` `/padd` `/pplay` `/premove` `/pview` `/pdelete` `/cpplay` | `modules/savedplaylists.py` (374) + `core/playlists.py` (150) + `modules/convenience.py` (242) | better — plus `/exportpl` `/importpl` |
| `ShizuMusic/modules/resume.py` | 60 | `/resume` `/cresume` | `modules/controls.py` | merged |
| `ShizuMusic/modules/seek.py` | 275 | `/seek` `/seekback` with a local position tracker | `modules/controls.py` `/seek` + `utils/helpers.parse_seek` (144) | better — parses `90`, `1:30`, `+15`, `-10`, `+1:30`; no separate tracker to drift |
| `ShizuMusic/modules/skip.py` | 115 | `/skip` `/cskip`, skip-to-index | `modules/controls.py` + `modules/channel.py` + `/voteskip` | better — plus vote-skip |
| `ShizuMusic/modules/start.py` | 204 | `/start` `/help` | `modules/start.py` (451) + `ui/cards.py` | better — group-aware card, Mini App button |
| `ShizuMusic/modules/stats.py` | 147 | `/stats` | `modules/admin.py` `/stats` + `modules/extras.py` `/sysstats` + `modules/power.py` `/dbstats` | better |
| `ShizuMusic/modules/stop.py` | 109 | `/stop` `/end` `/clear` `/cclear` `/reboot` | `modules/controls.py` `/stop`, `modules/queue_cmd.py` `/clearqueue`, `modules/admin.py` `/restart` | same (aliases `end`/`clear`/`reboot` deliberately not registered) |
| `ShizuMusic/modules/thumbnail.py` | 87 | `/thumbnail` — custom art per chat | `modules/channel.py` `/cthumbnail` + `utils/thumbnails.py` (766) + `modules/thumbnail_cmd.py` | same — VYRON draws the poster from the track's own cover; there is no per-chat upload |
| `ShizuMusic/strings/__init__.py` | 123 | per-language string packs | `core/i18n.py` (298) | better |
| `ShizuMusic/utils/__init__.py` | 21 | re-exports | — | n/a |
| `ShizuMusic/utils/assistant.py` | 85 | is the assistant in the call, invite it | `core/player.py` (`_ensure_call`, invite) + `modules/assistant_tools.py` (259) | better |
| `ShizuMusic/utils/buttons.py` | 309 | button bars, emoji, styles | `ui/keyboards.py` (261) + `ui/blocks.py` (443) + `ui/theme.py` (208) | better — ≤6 buttons per card, no bar glyphs |
| `ShizuMusic/utils/db.py` | 903 | ~60 Mongo helpers | `database.py` (912) | better — the same surface across two backends, `forget_user`, retention |
| `ShizuMusic/utils/decorators.py` | 49 | block-check wrapper | `modules/extras.py` + `modules/play.py` blocklist | merged |
| `ShizuMusic/utils/formatters.py` | 121 | time/duration formatting, progress bars | `ui/progress.py` (176) + `utils/helpers.py` | better — no `█`/`▬` glyphs by rule |
| `ShizuMusic/utils/helpers.py` | 24 | `delete_file` | `utils/helpers.py` (339) | merged |
| `ShizuMusic/utils/language.py` | 26 | `chat_strings(chat_id)` | `core/i18n.py` | better |
| `ShizuMusic/utils/logs.py` | 20 | logger on/off switch | `core/logsink.py` (137) + `core/journal.py` | better |
| `ShizuMusic/utils/permissions.py` | 53 | admin/authorised checks | `core/acl.py` (104) + `utils/helpers.py` + `utils/filters.py` | better — owner, sudo, per-chat admin, DM-only rules |
| `ShizuMusic/utils/routes.py` | 51 | tiny router for panels | `modules/callbacks.py` + `ui/panels.py` (31) | merged |
| `ShizuMusic/utils/thumbnail.py` | 37 | default thumbnail + HTML | `utils/thumbnails.py` + `utils/brandart.py` (269) | better |
| `ShizuMusic/utils/youtube.py` | 585 | yt-dlp wrapper, `download_song`, `resolve_stream`, search | `core/search.py` (1661) + `core/downloader.py` (1121) + `core/accelerator.py` (574) + `core/sources.py` (471) + `core/public_streams.py` (729) | better — multi-tier ladder, mirrors, ranges, impersonation |

## 1.2 Commands

| Shizu command(s) | VYRON | verdict |
|---|---|---|
| `/autoplay` `/cautoplay` | same | same |
| `/gblock` `/gunblock` `/ublock` `/uunblock` `/blocklist` | same | same |
| `/broadcast` `/gcast` | `/broadcast` (+`/gcast`) | same |
| `/addchannel` `/delchannel` `/setchannel` `/removechannel` | `/addchannel` `/delchannel` `/cplayset` (+`/setchannel`) `/delchannel` (+`/removechannel`) | same |
| `/language` `/lang` `/setlang` | `/language` `/lang` (+`/setlang <code>`) | same — `/setlang` also takes a code |
| `/logger` | `/logger` `/logs` | better |
| `/repo` `/id` | same | same |
| `/pause` `/cpause` | same | same |
| `/ping` | same (+`/doctor`) | better |
| `/speedtest` `/spt` | — | **absent (deliberate)** |
| `/playforce` `/vplayforce` `/cplayforce` `/cvplayforce` | — | **absent (deliberate)** |
| `/pcreate` `/padd` `/premove` `/pview` `/pplay` `/cpplay` `/pdelete` | `/pcreate` `/padd` `/premove` `/pview` `/pplay` `/pdelete` | same |
| `/resume` `/cresume` | same | same |
| `/skip` `/cskip` | same (+`/next`, `/voteskip`, `/skipvotes`) | better |
| `/start` `/help` | same | same |
| `/stats` | `/stats` `/sysstats` `/dbstats` | better |
| `/stop` `/cstop` | same | same |
| `/end` `/cend` `/clear` `/cclear` `/reboot` | `/stop` (+`/end`) `/cstop` (+`/cend`) `/clearqueue` (+`/clear`) `/cclear` `/restart` | same (different names, old ones kept as aliases) |
| `/seek` `/seekback` | `/seek` | same |
| `/thumbnail` `/cthumbnail` | `/cthumbnail` | same |

---

# 2. Videl (45 files, 10,169 lines)

## 2.1 Files

| file | lines | what it does | VYRON counterpart | verdict |
|---|---|---|---|---|
| `main.py` | 3 | entry | `main.py` | n/a |
| `config.py` | 62 | env constants | `config.py` | better |
| `videl/__init__.py` | 48 | clients + logger | `clients.py` + `runtime.py` | better |
| `videl/__main__.py` | 294 | boot, keep-alive web server, `/health` | `__main__.py` + `core/keepalive.py` + `utils/health.py` | better |
| `videl/api/__init__.py` | 1 | marker | `api/__init__.py` | n/a |
| `videl/api/eldian_routes.py` | 236 | HTTP download API with an optional key | `api/routes.py` (777) + `api/openapi.py` (616) + `api/docs.py` (521) + `api/security.py` (136) | better — versioned contract, keys with scopes/quotas, OpenAPI + live docs |
| `videl/core/__init__.py` | 5 | marker | — | n/a |
| `videl/core/autoplay.py` | 147 | next song by query refill | `core/autoplay.py` + `core/charts.py` | better — lane filters, charts, prefetch |
| `videl/core/call.py` | 212 | join/promote/leave helpers | `core/player.py` | same |
| `videl/core/player.py` | 749 | player, now playing, loop/pause flags | `core/player.py` | better |
| `videl/core/queue.py` | 67 | dict queues | `core/queue.py` | better |
| `videl/core/watcher.py` | 127 | cleanup loop, `/watchdog` | `core/watchdog.py` + `core/maintenance.py` | same |
| `videl/database.py` | 55 | Mongo singleton | `database.py` | better |
| `videl/modules/__init__.py` | 29 | module loader | `modules/__init__.py` | better |
| `videl/modules/admin.py` | 925 | 26 group-admin commands | `modules/moderation.py` (742) + `modules/groupadmin.py` (889) | better — 44 commands incl. locks, captcha, approvals |
| `videl/modules/autoplay.py` | 120 | `/autoplay` | `modules/controls.py` | same |
| `videl/modules/block.py` | 269 | blocklists | `modules/extras.py` | same |
| `videl/modules/bot.py` | 185 | add/remove watcher | `modules/presence.py` | better — removal drops the queue and stored settings |
| `videl/modules/broadcast.py` | 277 | broadcast | `modules/admin.py` | better |
| `videl/modules/callbacks.py` | 525 | buttons | `modules/callbacks.py` | better |
| `videl/modules/cplay.py` | 347 | channel playback | `modules/channel.py` | better |
| `videl/modules/effects.py` | 427 | audio effects | `modules/effects_cmd.py` + `core/effects.py` | same |
| `videl/modules/locks.py` | 245 | `/locks` `/antiflood` content locks | `modules/locks.py` (283) | same |
| `videl/modules/lyrics.py` | 152 | LRCLIB `/lyrics` | `core/lyrics.py` (152) + `modules/tools.py` `/lyrics` | same |
| `videl/modules/misc.py` | 174 | `/repo` `/id` `/cleanup` `/dbcleanup` | `modules/start.py` + `modules/power.py` `/dbcleanup` | same |
| `videl/modules/pause.py` | 46 | `/pause` | `modules/controls.py` | merged |
| `videl/modules/ping.py` | 155 | `/ping` `/speedtest` | `modules/start.py` `/ping` | same; `/speedtest` absent (deliberate) |
| `videl/modules/play.py` | 601 | play, replied files, documents | `modules/play.py` | better |
| `videl/modules/playlist.py` | 260 | saved playlists | `modules/savedplaylists.py` | better |
| `videl/modules/resume.py` | 46 | `/resume` | `modules/controls.py` | merged |
| `videl/modules/seek.py` | 256 | `/seek` `/seekback` | `modules/controls.py` `/seek` | same |
| `videl/modules/skip.py` | 95 | `/skip` | `modules/controls.py` | merged |
| `videl/modules/smartqueue.py` | 189 | `/voteskip` `/setvoteskip` `/queue` `/q` | `modules/smartqueue.py` (200) + `core/votes.py` (88) | same |
| `videl/modules/start.py` | 250 | `/start` `/help` | `modules/start.py` | better |
| `videl/modules/stats.py` | 136 | `/stats` | `modules/admin.py` `/stats` | better |
| `videl/modules/stop.py` | 91 | `/stop` `/clear` `/reboot` | `modules/controls.py` `/queue_cmd.py` `/admin.py` | same |
| `videl/utils/__init__.py` | 12 | re-exports | — | n/a |
| `videl/utils/assistant.py` | 104 | assistant join helpers | `core/player.py` | same |
| `videl/utils/db.py` | 974 | ~60 Mongo helpers | `database.py` | better |
| `videl/utils/decorators.py` | 52 | block-check wrapper | `modules/extras.py` + `modules/play.py` | merged |
| `videl/utils/formatters.py` | 126 | time/emoji formatting | `ui/progress.py` + `utils/helpers.py` | better |
| `videl/utils/helpers.py` | 15 | `delete_file` | `utils/helpers.py` | merged |
| `videl/utils/permissions.py` | 44 | authorisation | `core/acl.py` | better |
| `videl/utils/rich_ui.py` | 7 | tiny rich helper | `ui/rich.py` (733) | better |
| `videl/utils/youtube.py` | 1029 | yt-dlp + Eldian/Shruti/Piped, proxy list, cookies | `core/search.py` + `core/downloader.py` + `core/public_streams.py` + `core/accelerator.py` + `core/cookies.py` (new) | better — same ladder shape, plus ranges, impersonation, self-refreshing cookies |

## 2.2 Commands

| Videl command(s) | VYRON | verdict |
|---|---|---|
| `/ban` `/dban` `/unban` `/kick` `/dkick` `/mute` `/tmute` `/unmute` `/promote` `/demote` | same | same |
| `/warn` `/dwarn` `/warns` `/resetwarns` `/rmwarns` `/unwarn` `/setwarnlimit` | `/warn` `/warns` `/resetwarns` (+`/rmwarns`) `/unwarn` `/warnlimit` | same |
| `/purge` `/pin` `/unpin` | same | same |
| `/setwelcome` `/welcome` `/welcomemode` `/setgoodbye` `/admins` `/adminlist` | `/setwelcome` `/welcome` (+`/welcomemode`) `/setgoodbye` `/admins` (+`/adminlist`) | same |
| `/locks` `/lockpanel` `/contentlocks` `/antiflood` `/setflood` | `/locks` `/lockpanel` `/antiflood` `/lock` `/unlock` | same |
| `/lyrics` `/ly` `/lyric` | `/lyrics` | same |
| `/repo` `/id` | same | same |
| `/cleanup` `/dbcleanup` | `/dbcleanup` (+`/cleanup`) | same |
| `/saveplaylist` `/savepl` `/playlist` `/loadplaylist` `/loadpl` `/playlists` `/myplaylists` `/listpl` `/deleteplaylist` `/delpl` `/rmplaylist` | `/savepl` (+`/saveplaylist`) `/playlists` (+`/myplaylists`, `/listpl`) `/pplay` (+`/loadpl`, `/loadplaylist`) `/pdelete` (+`/delpl`, `/rmplaylist`, `/deleteplaylist`) `/pcreate` `/padd` `/pview` `/premove` | same |
| `/voteskip` `/setvoteskip` `/skipvotes` `/queue` `/q` | `/voteskip` (+`/skipvotes`) `/setvoteskip` `/queue` (+`/q`) | same |
| `/gblock` `/gunblock` `/ublock` `/uunblock` `/blocklist` | same | same |
| `/channelplay` `/cplayset` `/setchannel` | `/cplay` (+`/channelplay`) `/cplayset` (+`/setchannel`) `/addchannel` | same |
| `/pause` `/resume` `/skip` `/stop` `/end` `/clear` `/reboot` `/ping` (`/ping@` is `/ping` addressed to the bot, not a separate command) | `/pause` `/resume` `/skip` `/stop` `/clearqueue` `/restart` `/ping` | same |
| `/speedtest` `/spt` | — | **absent (deliberate)** |

---

# 3. FallenMusic (39 files, 3,447 lines)

## 3.1 Files

| file | lines | what it does | VYRON counterpart | verdict |
|---|---|---|---|---|
| `config.py` | 27 | env constants | `config.py` | better |
| `main.py` (in `FallenMusic/__main__.py`) | 92 | boot | `__main__.py` | better |
| `FallenMusic/__init__.py` | 118 | client, sudoers, logger | `clients.py` + `runtime.py` | better |
| `FallenMusic/Helpers/__init__.py` | 32 | re-exports | — | n/a |
| `FallenMusic/Helpers/active.py` | 60 | active-chat set | `core/queue.py` + `player._in_call` | merged |
| `FallenMusic/Helpers/admins.py` | 91 | admin checks | `core/acl.py` + `utils/helpers.py` | merged |
| `FallenMusic/Helpers/clear.py` | 32 | wipe downloads | `core/maintenance.py` + `/clearcache` | same |
| `FallenMusic/Helpers/dossier.py` | 81 | start/help text constants | `ui/cards.py` (2658) | better — generated cards, not string blobs |
| `FallenMusic/Helpers/downloaders.py` | 52 | one `YoutubeDL`, `audio_dl` | `core/downloader.py` | better — tiers, ranges, mirrors, no re-encode |
| `FallenMusic/Helpers/errors.py` | 29 | two exception classes | `core/player.StreamError`, `core/downloader.DownloadError`, `api/errors.py` | better |
| `FallenMusic/Helpers/formatters.py` | 45 | time formatting | `ui/progress.py` + `utils/helpers.py` | same |
| `FallenMusic/Helpers/gets.py` | 57 | reply/url extraction, file names | `utils/naming.py` (150) + `modules/play.py` | better |
| `FallenMusic/Helpers/inline.py` | 110 | inline keyboards/results | `modules/inline.py` (171) | same |
| `FallenMusic/Helpers/queue.py` | 48 | `asyncio.Queue` wrapper | `core/queue.py` | better |
| `FallenMusic/Helpers/thumbnails.py` | 327 | PIL poster/thumbnail generation | `utils/thumbnails.py` (766) + `utils/brandart.py` | better |
| `FallenMusic/Helpers/utils/__init__.py` | 21 | adb wrapper | — | n/a |
| `FallenMusic/Modules/__init__.py` | 40 | module loader | `modules/__init__.py` | better |
| `FallenMusic/Modules/activevc.py` | 55 | `/activevc` | `/vc` (`extras.py`) + `/active` (`admin.py`) | same |
| `FallenMusic/Modules/assistant.py` | 97 | assistant profile (pfp/bio/name) | `modules/assistant_tools.py` (259) + `core/botprofile.py` (168) | better |
| `FallenMusic/Modules/broadcast.py` | 65 | `/broadcast` | `modules/admin.py` | better |
| `FallenMusic/Modules/callback.py` | 253 | button callbacks | `modules/callbacks.py` | better |
| `FallenMusic/Modules/cleaner.py` | 49 | `/clearcache` `/rmdownloads` | `/clearcache` (`power.py`) | same |
| `FallenMusic/Modules/eval.py` | 195 | `/eval` `/sh` | `/eval` (`power.py`) | same — `/sh` absent by design (no shell from chat) |
| `FallenMusic/Modules/inline.py` | 92 | inline query | `modules/inline.py` | same |
| `FallenMusic/Modules/leaveall.py` | 63 | `/leaveall` | `/leaveall` (`admin.py`) | same |
| `FallenMusic/Modules/pause.py` | 48 | `/pause` | `modules/controls.py` | merged |
| `FallenMusic/Modules/ping.py` | 68 | `/ping` | `modules/start.py` | same |
| `FallenMusic/Modules/play.py` | 258 | `/play` | `modules/play.py` | better |
| `FallenMusic/Modules/resume.py` | 45 | `/resume` | `modules/controls.py` | merged |
| `FallenMusic/Modules/search.py` | 67 | `/search` | `/search` (`play.py`) + inline | better |
| `FallenMusic/Modules/skip.py` | 77 | `/skip` | `modules/controls.py` | merged |
| `FallenMusic/Modules/song.py` | 119 | `/song` `/vsong` | `/song` (`play.py`, also uploads to DM) | same |
| `FallenMusic/Modules/speedtest.py` | 67 | `/speedtest` | — | **absent (deliberate)** |
| `FallenMusic/Modules/start.py` | 103 | `/start` | `modules/start.py` | better |
| `FallenMusic/Modules/stop.py` | 46 | `/stop` | `modules/controls.py` | merged |
| `FallenMusic/Modules/sudoers.py` | 132 | sudo list | `/addsudo` `/delsudo` `/sudolist` `/sudoers` (`power.py`) | same |
| `FallenMusic/Modules/sysstats.py` | 115 | `/sysstats` | `/sysstats` (`extras.py`) + `modules/doctor.py` | better |
| `FallenMusic/Modules/variables.py` | 61 | `/config` `/variables` | `/vars` (`power.py`) | same |
| `FallenMusic/Modules/watcher.py` | 110 | welcome, on-stream-end | `modules/presence.py` + `core/player.py` | better — removal also cleans up |

## 3.2 Commands

| Fallen command(s) | VYRON | verdict |
|---|---|---|
| `/play` `/vplay` `/p` | `/play` | same (`vplay`, `p` removed by the owner) |
| `/song` `/vsong` `/video` `/music` | `/song` | same |
| `/search` | `/search` + inline | same |
| `/skip` `/next` `/pause` `/resume` `/stop` `/end` | `/skip` (+`/next`) `/pause` `/resume` `/stop` (+`/end`) | same |
| `/activevc` | `/vc` `/active` | same |
| `/leaveall` `/assleaveall` | `/leaveall` (+`/assleaveall`) | same |
| `/asspfp` `/setpfp` `/delpfp` `/delasspfp` `/assbio` `/setbio` `/assname` `/setname` | `/setpfp` (+`/asspfp`) `/delpfp` (+`/delasspfp`) `/setbio` (+`/assbio`) `/setname` (+`/assname`) | same |
| `/broadcast` | `/broadcast` | same |
| `/clearcache` `/rmdownloads` | `/clearcache` (+`/rmdownloads`) | same |
| `/eval` `/sh` | `/eval` | same (`/sh` absent by design) |
| `/addsudo` `/delsudo` `/rmsudo` `/sudolist` `/sudoers` `/sudo` | `/addsudo` `/delsudo` (+`/rmsudo`) `/sudolist` `/sudoers` (+`/sudo`) | same |
| `/stats` `/sysstats` | `/stats` `/sysstats` | same |
| `/config` `/variables` | `/vars` (+`/config`, `/variables`) | same |
| `/speedtest` `/spt` | — | **absent (deliberate)** |
| inline search | inline search | same |

---

# 4. Where the comparison changed the code

Each item below came out of this comparison and is shipped:

| release | change | source of the idea |
|---|---|---|
| 1.10.13 | six-way ranged download accelerator tier; no re-encode for AAC-in-m4a; fragment concurrency; yt-dlp ladder raced against mirrors | Videl's fallback chain, Fallen's direct-stream handling |
| 1.10.14 | revoked API keys delete themselves after 7 days | Videl/Fallen both accumulate keys forever |
| 1.10.15 | removing the bot drops the queue, leaves the call and deletes the chat's settings; adding it sends the setup card | Shizu/Videl `bot_left_watcher` + `bot_added_watcher` |
| 1.10.17 | `COOKIES_URL`: a cookie jar that refreshes itself, refuses placeholders, and re-reads on a detected bot-wall | Videl's cookie download/validation in `utils/youtube.py` |
| 1.10.19 | 38 names from the other three bots are aliases on VYRON's existing handlers — one implementation, two names | their command tables (see the note below) |
| 1.10.19 | `/setlang <code>` sets a language in one message instead of four taps | Shizu's `/setlang` |
| 1.10.19 | if only the **assistant** is kicked, the queue is cleared and the group is told why; a queue that could never play again is gone | Shizu's `bot_left_watcher`, Videl's `utils/assistant.py` |
| 1.10.19 | a source search stops at half a page instead of waiting for every source to answer | the Render log's 4.8–6.3 s `POST /api/search` |

Deliberately **not** copied, with reasons:

| their feature | why not |
|---|---|
| `/playforce` family (Shizu) | owner deleted it; a group that wants to override should change its own settings, not a command |
| `/speedtest` (all three) | measured the host, not playback; `/ping` + `/doctor` answer the same question |
| `/sh` (Fallen) | shell from chat on a host holding the bot token |
| Fallen's `audio_dl()` shape (re-encode every id) | slower and lossier than copying the stream |
| Shizu's `_SEEK_STATE` tracker | a second source of truth next to `player.started_at`; it drifts |
| `/vplay`, `/p`, `/cvplay`, `/playforce` family, `/speedtest`, `/spt`, `/reboot` | removed or never added by the owner; `/restart` is the equivalent of `/reboot` |

Old names are kept as **aliases on the same handler** rather than second implementations, so a user arriving from another bot can keep typing what they know and behaviour cannot drift between the two names: `/q` `/end` `/cend` `/next` `/clear` `/removechannel` `/rmdownloads` `/ly` `/lyric` `/cleanup` `/config` `/variables` `/rmsudo` `/sudo` `/myplaylists` `/listpl` `/saveplaylist` `/loadpl` `/loadplaylist` `/delpl` `/rmplaylist` `/deleteplaylist` `/asspfp` `/assbio` `/assname` `/delasspfp` `/setflood` `/setlang` `/activevc` `/contentlocks` `/gcast` `/assleaveall` `/skipvotes` `/rmwarns` `/welcomemode` `/adminlist` `/channelplay` `/setchannel`.
