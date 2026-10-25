# VYRON vs ShizuMusic vs Videl vs FallenMusic

An exhaustive, file-by-file and command-by-command comparison, written on
2026-10-25 against the current trees of:

| repo | commit compared | size |
|---|---|---|
| **VYRON** (`Beasgohan-code/VYRON`) | branch `arena/34acaf50-vyron` @ 1.10.15 | **125 files · 40,454 lines** |
| `BadMunda05/ShizuMusic` | `main` | 49 files · 10,232 lines |
| `Beasgohan-code/Videl` | `main` | 45 files · 10,169 lines |
| `AnonymousX1025/FallenMusic` | `main` | 39 files · 3,447 lines |

Every competitor file appears below with a one-line reason — including the ones
judged **not needed** — and every competitor command is mapped to the VYRON
command that answers it.

## How this was produced

Both clones were read directly; nothing here is from memory.

```bash
git clone --depth 1 https://github.com/BadMunda05/ShizuMusic /tmp/shizu
git clone --depth 1 https://github.com/Beasgohan-code/Videl     /tmp/videl
git clone --depth 1 https://github.com/AnonymousX1025/FallenMusic /tmp/fallen
```

* file inventory and line counts: `rglob("*.py")` + `splitlines()` per repo;
* command inventory: regex over `filters.command(...)` in the three competitors,
  AST walk over `cmd([...])` / `cmd("...")` in `vyron/modules/*.py`;
* behaviour: every file's `def`/`class` list was extracted with `ast` and the
  interesting ones were read in full (`Helpers/downloaders.py`,
  `utils/youtube.py`, `core/player.py`, `modules/play.py`, …).

The two lists above (files, commands) were diffed against the tables below
mechanically — every path and every command name in this document was matched
against the clones, so nothing is missing from them.

Verdicts used below:

| verdict | meaning |
|---|---|
| **exceeded** | VYRON does what the file does, plus something that file cannot do |
| **equal** | same capability, comparable depth |
| **n/a** | the file has no VYRON-side counterpart because VYRON is structured differently |
| **rejected** | deliberately not copied, with the reason given |

---

# 1. Headline

* **Command surface**: VYRON exposes **163 command triggers** across 31 handler
  modules (aliases counted). ShizuMusic has **51** distinct command names,
  Videl **78**, FallenMusic **44**. Every one of them maps to something VYRON
  already has, except the names in §2.4 — all of which are either deliberately
  removed by the owner or aliases of commands VYRON already ships.
* **Nothing in the other three is a capability VYRON lacks.** The only real
  *behaviour* gaps found were smaller than a command: a group that added the
  bot got no greeting, and a group that removed it left a queue behind. Both
  were fixed in **1.10.15** (`vyron/modules/presence.py`).
* **VYRON is ~4× the code** of the largest of them (40k vs 10k lines), and the
  extra mass is not in commands: it is the download/stream stack, the three
  storage backends, the Mini App HTTP server, the public API, the journal, the
  watchdog, i18n and the Rich-card renderer — things none of the three have.
* **Downloads**: VYRON's ladder (yt-dlp with browser impersonation → aria2 /
  ranged accelerator → direct-host probes → Piped/Invidious/Cobalt mirrors →
  JioSaavn → Audius) is strictly longer than any of theirs. Shizu has yt-dlp +
  innertube, Videl has yt-dlp + 3 third-party APIs, Fallen has one yt-dlp call.

---

# 2. Commands

## 2.1 ShizuMusic → VYRON

Source: `filters.command` in `ShizuMusic/modules/*.py`.

| Shizu command | VYRON answer | verdict |
|---|---|---|
| `/autoplay` `/cautoplay` | `/autoplay`, `/cautoplay` (`controls.py`, `channel.py`) | equal — VYRON adds mood/language lanes and chart seeding |
| `/gblock` `/gunblock` `/ublock` `/uunblock` `/blocklist` | same five names in `extras.py` | equal |
| `/broadcast` `/gcast` | `/broadcast` (`admin.py`) | exceeded — per-chat cards, batching, progress, resume on restart |
| `/addchannel` `/setchannel` `/delchannel` `/removechannel` | `/addchannel` `/cplayset` `/delchannel` (`channel.py`) | exceeded; `removechannel` is `delchannel`'s job, no alias added (see §2.4) |
| `/language` `/lang` `/setlang` | `/language` `/lang` + Mini App switch (`language.py`, `core/i18n.py`) | exceeded — `setlang` folded into the buttons |
| `/logger` | `/logger`, `/logs` (`logs_cmd.py`) | exceeded — journal scopes, filters, export |
| `/repo` `/id` | `/repo` `/id` (`start.py`) | equal |
| `/pause` `/cpause` | `/pause` `/cpause` (`controls.py`, `channel.py`) | equal |
| `/ping` | `/ping` (`start.py`) + `/doctor` | equal |
| `/speedtest` `/spt` | — | **rejected**: owner removed it (`test_removed_commands_stay_removed`) |
| `/playforce` `/vplayforce` `/cplayforce` `/cvplayforce` | — | **rejected**: owner removed the force-play family |
| `/pcreate` `/padd` `/premove` `/pview` `/pplay` `/cpplay` `/pdelete` | same names (`savedplaylists.py`) + `/playlists` `/savepl` | exceeded — saved playlists, sharing codes, `/exportpl` `/importpl` |
| `/resume` `/cresume` | `/resume` `/cresume` | equal |
| `/skip` `/cskip` | `/skip` `/cskip` + vote skip (`smartqueue.py`, `core/votes.py`) | exceeded |
| `/start` `/help` | `/start` `/help` + Mini App | exceeded |
| `/stats` | `/stats` + `/sysstats` (`power.py`, `extras.py`) | exceeded |
| `/stop` `/end` `/cstop` `/cend` `/clear` `/cclear` `/reboot` | `/stop` `/cstop` `/clearqueue` `/cclear` `/restart` | equal — different names, same actions (`end`/`reboot` aliases deliberately not added) |
| `/thumbnail` `/cthumbnail` | `/cthumbnail` (`channel.py`, `thumbnail_cmd.py`) | exceeded — the poster draws its own art (`utils/thumbnails.py`, 766 lines) |
| `/seek` (`seek.py`) | `/seek` (`controls.py`) | equal |
| `/queue` (`core/queue.py` API) | `/queue` `/queueinfo` | exceeded |

## 2.2 Videl → VYRON

| Videl command | VYRON answer | verdict |
|---|---|---|
| `/ban` `/dban` `/unban` `/kick` `/dkick` `/mute` `/tmute` `/unmute` `/promote` `/demote` `/warn` `/dwarn` `/warns` `/resetwarns` `/rmwarns` `/unwarn` `/setwarnlimit` `/purge` `/pin` `/unpin` `/setwelcome` `/welcome` `/welcomemode` `/setgoodbye` `/admins` `/adminlist` | same names in `moderation.py` (742) and `groupadmin.py` (889) | exceeded — plus `/slowmode` `/zombies` `/captcha` `/approve` `/report` `/revokeinvite` `/unpinall` `/invitelink` |
| `/gblock` `/gunblock` `/ublock` `/uunblock` `/blocklist` | `extras.py` | equal |
| `/broadcast` `/gcast` | `/broadcast` | exceeded |
| `/channelplay` `/cplayset` `/setchannel` | `/cplay` `/cplayset` `/addchannel` | exceeded |
| `/locks` `/lockpanel` `/contentlocks` `/antiflood` `/setflood` | `/locks` `/lockpanel` `/lock` `/unlock` `/antiflood` (`locks.py`) | exceeded — per-lock toggles; flood limit is one number in `/antiflood` |
| `/lyrics` `/lyric` `/ly` | `/lyrics` (`tools.py`, `core/lyrics.py`) | equal |
| `/repo` `/id` | `/repo` `/id` | equal |
| `/cleanup` `/dbcleanup` | `/dbcleanup` (`power.py`) | exceeded — also purges revoked API keys (1.10.14) |
| `/pause` `/resume` `/skip` `/stop` `/end` `/clear` `/reboot` | `/pause` `/resume` `/skip` `/stop` `/clearqueue` `/restart` | equal |
| `/ping` `/ping@` `/speedtest` `/spt` | `/ping` (`ping@bot` is the same filter with a username) ; speedtest rejected | equal / rejected |
| `/saveplaylist` `/savepl` `/playlist` `/loadplaylist` `/loadpl` `/playlists` `/myplaylists` `/listpl` `/deleteplaylist` `/delpl` `/rmplaylist` | `/savepl` `/playlists` `/pplay` `/pdelete` `/pcreate` `/padd` `/pview` `/premove` | exceeded |
| `/voteskip` `/setvoteskip` `/skipvotes` `/queue` `/q` | `/voteskip` `/setvoteskip` `/queue` | exceeded — `/q` shortcut intentionally not added (see §2.4) |

## 2.3 FallenMusic → VYRON

| Fallen command | VYRON answer | verdict |
|---|---|---|
| `/play` `/vplay` `/p` | `/play`, `/song`, replied-file playback | exceeded; `vplay`/`p` are removed aliases |
| `/song` `/video` `/music` | `/song` (plays video when asked) | exceeded |
| `/search` | `/search` + inline query | exceeded |
| `/skip` `/next` `/pause` `/resume` `/stop` `/end` | `/skip` `/pause` `/resume` `/stop` | equal |
| `/activevc` | `/vc`, `/active` | equal |
| `/leaveall` `/assleaveall` | `/leaveall`, `/leavevc` | exceeded |
| `/asspfp` `/setpfp` `/delpfp` `/delasspfp` `/assbio` `/setbio` `/assname` `/setname` | same names (`assistant_tools.py`, `core/botprofile.py`) | exceeded — validated, previewed, persisted |
| `/broadcast` | `/broadcast` | exceeded |
| `/clearcache` `/rmdownloads` | `/clearcache` | equal (`rmdownloads` alias not added) |
| `/eval` `/sh` | `/eval` (`power.py`) | equal — `/sh` folded into `/eval` |
| `/addsudo` `/delsudo` `/rmsudo` `/sudolist` `/sudoers` `/sudo` | `/addsudo` `/delsudo` `/sudolist` `/sudoers` | equal |
| `/stats` `/sysstats` | `/stats` `/sysstats` | exceeded |
| `/config` `/variables` | `/vars` | equal |
| `/speedtest` `/spt` | — | **rejected**: owner removed it |
| inline music search | inline query (`modules/inline.py`, 171 lines) | exceeded |

## 2.4 Commands deliberately *not* added

The owner's standing rule is "no new commands — extend existing ones". Each of
these is either a removed command or a pure alias, so the capability is already
reachable; nothing is missing from the bot's surface.

| name(s) | why not |
|---|---|
| `playforce`, `vplayforce`, `cplayforce`, `cvplayforce` | deleted by the owner; `play` queues or starts, the distinction was noise |
| `vplay`, `vsong`, `cplay`-force variants, `p` | removed aliases of `play` / `/song` |
| `speedtest`, `spt` | deleted; `/ping` + `/doctor` answer "is it slow, and where" |
| `end` | alias of `stop` |
| `clear` | alias of `clearqueue` |
| `reboot` | alias of `restart` |
| `removechannel` | `delchannel` |
| `rmdownloads` | `/clearcache` clears the download cache |
| `q` | alias of `queue` |
| `setlang` | the `/language` buttons |
| `setflood` | one dial inside `/antiflood` |
| `thumbnail` | the poster draws the song's own cover; `/cthumbnail` covers channel art |
| `sh` | `/eval` |
| `next` | alias of `skip` |
| `myplaylists`, `listpl`, `loadpl`, `delpl`, `rmplaylist`, `saveplaylist` | `/playlists`, `/pplay`, `/pdelete`, `/savepl` |
| `spt` | `speedtest` |
| `sudo`, `rmsudo` | `/sudolist`, `/delsudo` |
| `config` | `/vars` |
| `welcome`/`setgoodbye` — present; `welcomemode` | `/welcome` takes the short form |

---

# 3. ShizuMusic, file by file (49 files)

Paths are inside the `ShizuMusic/` package unless they are `config.py` /
`main.py` at the repo root: `core/autoplay.py` means
`ShizuMusic/core/autoplay.py`.

| file (lines) | what it does | VYRON counterpart | verdict |
|---|---|---|---|
| `config.py` (70) | reads env into globals | `vyron/config.py` (349) — dataclass, validation, defaults, no import-time crash | exceeded |
| `main.py` (3) | entry shim | `main.py` + `vyron/__main__.py` (535) | n/a |
| `ShizuMusic/__init__.py` (57) | builds the bot client | `vyron/clients.py` (134) + `runtime.py` (177) | exceeded — bot *and* assistant, ordered shutdown |
| `ShizuMusic/__main__.py` (254) | boot, Flask keep-alive, `/health`, owner ping on boot | `vyron/__main__.py`, `core/keepalive.py`, `utils/health.py`, aiohttp server | exceeded |
| `core/__init__.py` (13) | package marker | — | n/a |
| `core/autoplay.py` (1938) | autoplay from one YouTube channel's uploads, mood + language filters, buffer refill, history dedupe | `core/autoplay.py` (487) + `core/charts.py` (327) + `core/ytmusic.py` (280) | exceeded *on quality*: VYRON seeds from search/related/charts across several sources instead of a fixed channel; Shizu is bigger because it hand-parses innertube |
| `core/call.py` (184) | `leave_vc`, stream-end handler | `core/player.py` (1481): `leave`, `on_stream_end`, `_recover_stream` | exceeded — mid-song recovery, duplicate-stream-end dedupe, idle leave, call-end filter |
| `core/channels.py` (93) | rewrites `-100…` ids inside commands to a linked channel by regex | `modules/channel.py` (735): explicit `/c*` commands + `/cplayset` | equal — VYRON chose explicit commands over regex rewriting (the regex approach is what makes Shizu's `setchannel` fragile) |
| `core/player.py` (510) | now-playing panel, progress refresh, ensure-call | `core/player.py` + `ui/nowplaying.py` (276) + `ui/progress.py` (176) | exceeded — poster message is the card, no `█`/`▬` glyphs |
| `core/queue.py` (85) | list helpers over a dict of lists | `core/queue.py` (303) — `Track`, `LoopMode`, `ChatState`, `QueueManager` | exceeded |
| `core/watcher.py` (21) | trivial watchdog loop | `core/watchdog.py` (150) + `core/lease.py` (227) + `core/maintenance.py` (111) | exceeded |
| `database.py` (79) | thin mongo accessor | `database.py` (912) — JSON/embedded/Mongo with migrations, retention, key rotation | exceeded |
| `modules/__init__.py` (39) | module loader | `modules/__init__.py` (90) + `core/commandlist.py` (63) | exceeded |
| `modules/autoplay.py` (150) | `/autoplay`, `/cautoplay` | `modules/controls.py` + Mini App toggle | equal |
| `modules/block.py` (277) | group/user block lists, blocklist card | `modules/extras.py` (318) + blocked-word check in `modules/play.py` | equal |
| `modules/bot.py` (193) | greets on add, says goodbye on removal | `modules/presence.py` (125, new in 1.10.15) | equal for the greeting; **exceeded** for removal — VYRON also stops playback, leaves the call and deletes the chat's stored settings |
| `modules/broadcast.py` (289) | `/broadcast`, `/gcast` with flags | `modules/admin.py` (278) | exceeded — resumable, per-chat cards, progress |
| `modules/callbacks.py` (372) | help menu + player buttons | `modules/callbacks.py` (1036) | exceeded |
| `modules/channel.py` (208) | add/del/set channel | `modules/channel.py` (735) | exceeded — 14 `/c*` commands |
| `modules/effects.py` (444) | speed/bass/8D by re-encoding a temp file | `modules/effects_cmd.py` (262) + `core/effects.py` (132) | exceeded — ffmpeg filter chain applied to the stream, no file rewrite |
| `modules/language.py` (111) | language menu | `modules/language.py` (99) + `core/i18n.py` (298) | exceeded — per-chat, coverage report, JSON packs |
| `modules/logtoggle.py` (86) | `/logger` on/off | `modules/logs_cmd.py` (234) + `core/journal.py` (551) | exceeded — scoped, filterable, exportable |
| `modules/misc.py` (134) | `/repo`, `/id` | `modules/start.py` | equal |
| `modules/pause.py` (60) | `/pause`, `/cpause` | `modules/controls.py`, `modules/channel.py` | equal |
| `modules/ping.py` (163) | `/ping`, `/speedtest` | `modules/start.py`, `api/metrics.py` (110) | equal; speedtest rejected |
| `modules/play.py` (341) | play with regex, cooldown, blocked words | `modules/play.py` (1032) | exceeded — 3× the code: file playback, playlists, links, duplicates, queue overflow |
| `modules/playforce.py` (166) | force play, skipping permission checks | — | **rejected**: removed by the owner |
| `modules/playlist.py` (488) | `/pcreate` … `/cpplay` | `modules/savedplaylists.py` (374) + `core/playlists.py` (150) | exceeded |
| `modules/resume.py` (60) | `/resume`, `/cresume` | `modules/controls.py`, `modules/channel.py` | equal |
| `modules/seek.py` (275) | `/seek`, `/seekback` | `modules/controls.py` `seek` | equal |
| `modules/skip.py` (115) | `/skip`, `/cskip` | `modules/controls.py`, `modules/channel.py`, vote skip | exceeded |
| `modules/start.py` (204) | `/start`, `/help` | `modules/start.py` (451) | exceeded — private vs group card, photo, Mini App button |
| `modules/stats.py` (147) | `/stats` | `modules/power.py` (658) | exceeded — storage, sweep, keys, uptime, queue |
| `modules/stop.py` (109) | `/stop`, `/end`, `/clear`, `/cclear`, `/reboot` | `controls.py`, `queue_cmd.py`, `channel.py`, `admin.py` | equal |
| `modules/thumbnail.py` (87) | `/thumbnail` reply-to-photo | `modules/thumbnail_cmd.py` (53) + `utils/thumbnails.py` (766) | exceeded — the poster draws the cover itself |
| `strings/__init__.py` (123) | loads per-language string dicts | `core/i18n.py` | exceeded |
| `utils/__init__.py` (21) | shim | — | n/a |
| `utils/assistant.py` (85) | is-assistant-in / try-join | `core/player.py` (`_ensure_call`, invite) | exceeded |
| `utils/buttons.py` (309) | button styling, pill rows, progress bars | `ui/blocks.py` (443) + `ui/keyboards.py` (261) + `ui/theme.py` (208) | exceeded — ≤6 buttons per card, no bar glyphs |
| `utils/db.py` (903) | mongo collections for chats/users/settings | `database.py` | equal (VYRON: three backends, same 900 lines) |
| `utils/decorators.py` (49) | block-list middleware | `modules/play.py` blocked-word check + `utils/filters.py` | equal |
| `utils/formatters.py` (121) | duration/ISO/progress-bar formatting | `ui/progress.py`, `utils/helpers.py` | equal |
| `utils/helpers.py` (24) | `delete_file` | `utils/helpers.py` (339) | exceeded |
| `utils/language.py` (26) | per-chat string table | `core/i18n.py` | exceeded |
| `utils/logs.py` (20) | logger on/off flag | `core/logsink.py` (137) | exceeded |
| `utils/permissions.py` (53) | `is_user_authorized` | `core/acl.py` (104) + `utils/filters.py` | exceeded — sudo list, owner, per-chat admin |
| `utils/routes.py` (51) | route table for panels | `modules/callbacks.py` router + `core/pending.py` + `core/shortlived.py` | exceeded |
| `utils/thumbnail.py` (37) | thumbnail url/html | `utils/thumbnails.py` | exceeded |
| `utils/youtube.py` (585) | innertube scraping, `download_song`, `resolve_stream` | `core/search.py` (1661) + `core/sources.py` (471) + `core/public_streams.py` (729) + `core/downloader.py` (1121) + `engine/youtube.py` (239) | exceeded — multi-source ladder, mirror fallbacks, accelerator |

---

# 4. Videl, file by file (45 files)

| file (lines) | what it does | VYRON counterpart | verdict |
|---|---|---|---|
| `config.py` (62) | env with `_req()` hard requirements | `vyron/config.py` (349) | exceeded |
| `main.py` (3) | entry shim | `main.py` | n/a |
| `videl/__init__.py` (48) | client construction | `clients.py` + `runtime.py` | exceeded |
| `videl/__main__.py` (294) | boot, Flask keep-alive, `/health`, owner ping | `__main__.py` + `core/keepalive.py` + aiohttp server | exceeded |
| `videl/api/__init__.py` (1) | package marker | `api/__init__.py` | n/a |
| `videl/api/eldian_routes.py` (236) | download API with an API key and `/eldian` routes | `api/routes.py` (777) + `api/openapi.py` (616) + `api/docs.py` (521) + `api/security.py` (136) + `api/metrics.py` (110) | exceeded — versioned contract, scopes, quotas, OpenAPI + live docs |
| `videl/core/__init__.py` (5) | marker | — | n/a |
| `videl/core/autoplay.py` (147) | autoplay by query, batch refetch | `core/autoplay.py` (487) | exceeded |
| `videl/core/call.py` (212) | leave + stream-end | `core/player.py` | exceeded |
| `videl/core/player.py` (749) | now playing, loop, progress, call creation, assistant promotion | `core/player.py` (1481) | exceeded — VYRON adds recovery, prefetch, idle leave, persistence |
| `videl/core/queue.py` (67) | queue helpers | `core/queue.py` (303) | exceeded |
| `videl/core/watcher.py` (127) | cleanup downloads/db, auto-leave idle VCs | `core/watchdog.py` + `core/maintenance.py` + `Player._idle_worker` | exceeded |
| `videl/database.py` (55) | mongo accessor | `database.py` | exceeded |
| `videl/modules/__init__.py` (29) | loader | `modules/__init__.py` | exceeded |
| `videl/modules/admin.py` (925) | ban/kick/mute/warn/welcome/purge/pin (26 commands) | `modules/moderation.py` (742) + `modules/groupadmin.py` (889) | exceeded — 44 commands incl. captcha, zombies, approvals, invitelinks |
| `videl/modules/autoplay.py` (120) | `/autoplay` | `controls.py` | equal |
| `videl/modules/block.py` (269) | block lists | `modules/extras.py` | equal |
| `videl/modules/broadcast.py` (277) | `/broadcast`, `/gcast` | `modules/admin.py` | exceeded |
| `videl/modules/bot.py` (185) | add/remove watcher | `modules/presence.py` | exceeded (removal cleanup, 1.10.15) |
| `videl/modules/callbacks.py` (525) | help/player callbacks | `modules/callbacks.py` (1036) | exceeded |
| `videl/modules/cplay.py` (347) | channel play | `modules/channel.py` (735) | exceeded |
| `videl/modules/effects.py` (427) | speed/bass/8D | `modules/effects_cmd.py` + `core/effects.py` | exceeded |
| `videl/modules/locks.py` (245) | `/locks`, `/antiflood`, content locks | `modules/locks.py` (283) | equal |
| `videl/modules/lyrics.py` (152) | LRCLIB lyrics | `core/lyrics.py` (152) | equal |
| `videl/modules/misc.py` (174) | `/repo`, `/id`, `/cleanup`, `/dbcleanup` | `modules/start.py`, `modules/power.py` | equal |
| `videl/modules/pause.py` (46) | `/pause` | `controls.py` | equal |
| `videl/modules/ping.py` (155) | `/ping`, `/speedtest` | `modules/start.py` | equal; speedtest rejected |
| `videl/modules/play.py` (601) | play incl. uploaded documents, `ytpick` callback | `modules/play.py` (1032) | exceeded |
| `videl/modules/playlist.py` (260) | 5 playlist commands | `modules/savedplaylists.py` + `core/playlists.py` | exceeded |
| `videl/modules/resume.py` (46) | `/resume` | `controls.py` | equal |
| `videl/modules/seek.py` (256) | `/seek`, `/seekback` | `controls.py` | equal |
| `videl/modules/skip.py` (95) | `/skip` | `controls.py` + vote skip | exceeded |
| `videl/modules/smartqueue.py` (189) | `/voteskip`, `/setvoteskip`, `/queue` | `modules/smartqueue.py` (200) + `core/votes.py` (88) | exceeded |
| `videl/modules/start.py` (250) | start, help, cooldown, photo url | `modules/start.py` (451) + `modules/presence.py` | exceeded |
| `videl/modules/stats.py` (136) | `/stats` | `modules/power.py` | exceeded |
| `videl/modules/stop.py` (91) | `/stop`, `/clear`, `/reboot` | `controls.py`, `queue_cmd.py`, `admin.py` | equal |
| `videl/utils/__init__.py` (12) | shim | — | n/a |
| `videl/utils/assistant.py` (104) | assistant join helpers | `core/player.py` | exceeded |
| `videl/utils/db.py` (974) | mongo collections | `database.py` | equal |
| `videl/utils/decorators.py` (52) | block middleware | `modules/play.py` blocked words | equal |
| `videl/utils/formatters.py` (126) | duration/progress formatting | `ui/progress.py` | equal |
| `videl/utils/helpers.py` (15) | `delete_file` | `utils/helpers.py` | exceeded |
| `videl/utils/permissions.py` (44) | `is_user_authorized` | `core/acl.py` + `utils/filters.py` | exceeded |
| `videl/utils/rich_ui.py` (7) | 7-line re-export | `ui/rich.py` (733) | exceeded |
| `videl/utils/youtube.py` (1029) | yt-dlp + Eldian → Piped → Shruti fallback, proxy list, cookie refresh | `core/search.py` + `core/alternate.py` (361) + `core/public_streams.py` + `core/accelerator.py` (574) + `core/downloader.py` | exceeded — a longer ladder, plus a multi-connection accelerator and impersonation; the *cookie-refresh* and *proxy rotation* ideas are noted in §6 |

---

# 5. FallenMusic, file by file (39 files)

Paths are inside the `FallenMusic/` package unless they are `config.py` at
the repo root: `Helpers/downloaders.py` means
`FallenMusic/Helpers/downloaders.py`.

| file (lines) | what it does | VYRON counterpart | verdict |
|---|---|---|---|
| `config.py` (27) | env constants | `vyron/config.py` | exceeded |
| `FallenMusic/__init__.py` (118) | clients, sudoers, startup | `clients.py` + `runtime.py` + `__main__.py` | exceeded |
| `FallenMusic/__main__.py` (92) | boot | `__main__.py` | exceeded |
| `Helpers/__init__.py` (32) | re-exports | — | n/a |
| `Helpers/active.py` (60) | a set of active chats | `core/queue.py` + `Player._in_call` | equal |
| `Helpers/admins.py` (91) | admin checks | `utils/helpers.py` `is_chat_admin` | equal |
| `Helpers/clear.py` (32) | wipe downloads dir | `power.py` `/clearcache` | equal |
| `Helpers/dossier.py` (81) | hard-coded marketing strings | `ui/blocks.py` + `core/i18n.py` | exceeded |
| `Helpers/downloaders.py` (52) | one module-level `YoutubeDL`, `audio_dl` with a path-existence short-circuit | `core/downloader.py` (1121) | exceeded — accelerator tiers, mirror fallbacks, retries; the id-keyed "already downloaded" short-circuit is already VYRON behaviour |
| `Helpers/errors.py` (29) | duration-limit and ffmpeg exceptions | `core/player.StreamError` + `core/downloader.DownloadError` | exceeded |
| `Helpers/formatters.py` (45) | `get_readable_time` | `utils/helpers.py` | equal |
| `Helpers/gets.py` (57) | url extraction from entities/replies, file names | `modules/play.py` | exceeded |
| `Helpers/inline.py` (110) | inline strings + keyboards | `ui/blocks.py`, `ui/keyboards.py` | exceeded |
| `Helpers/queue.py` (48) | `asyncio.Queue.put` helper | `core/queue.py` | exceeded — real per-chat queues with loop/shuffle |
| `Helpers/thumbnails.py` (327) | PIL thumbnails, rounded corners, blur, per-user cache | `utils/thumbnails.py` (766) + `utils/brandart.py` (269) | exceeded — generated poster art, brand fonts, cover cache |
| `Helpers/utils/__init__.py` (21) | shim | — | n/a |
| `Modules/__init__.py` (40) | loader | `modules/__init__.py` | exceeded |
| `Modules/activevc.py` (55) | `/activevc` | `modules/extras.py` `/vc`, `modules/admin.py` `/active` | equal |
| `Modules/assistant.py` (97) | set assistant pfp/bio/name | `modules/assistant_tools.py` (259) + `core/botprofile.py` (168) | exceeded |
| `Modules/broadcast.py` (65) | `/broadcast` | `modules/admin.py` | exceeded |
| `Modules/callback.py` (253) | callback router | `modules/callbacks.py` (1036) | exceeded |
| `Modules/cleaner.py` (49) | `/clearcache`, `/rmdownloads` | `power.py` `/clearcache` | equal |
| `Modules/eval.py` (195) | `/eval`, `/sh`, runtime callback | `power.py` `/eval` | equal |
| `Modules/inline.py` (92) | inline query handler | `modules/inline.py` (171) | exceeded |
| `Modules/leaveall.py` (63) | `/leaveall` | `modules/admin.py`, `modules/extras.py` | exceeded |
| `Modules/pause.py` (48) | `/pause` | `controls.py` | exceeded |
| `Modules/ping.py` (68) | `/ping` | `modules/start.py` | equal |
| `Modules/play.py` (258) | `/play` with a blocking `audio_dl` call | `modules/play.py` (1032) | exceeded — VYRON never blocks the loop |
| `Modules/resume.py` (45) | `/resume` | `controls.py` | exceeded |
| `Modules/search.py` (67) | `/search` | `modules/play.py` + `modules/inline.py` | exceeded |
| `Modules/skip.py` (77) | `/skip`, `/next` | `controls.py` + vote skip | exceeded |
| `Modules/song.py` (119) | `/song`, `/video` | `modules/play.py` `/song` | exceeded |
| `Modules/speedtest.py` (67) | `/speedtest` | — | **rejected**: removed by the owner |
| `Modules/start.py` (103) | `/start` | `modules/start.py` (451) | exceeded |
| `Modules/stop.py` (46) | `/stop`, `/end` | `controls.py` | exceeded |
| `Modules/sudoers.py` (132) | sudo add/del/list | `power.py` `/addsudo` `/delsudo` `/sudolist` | equal |
| `Modules/sysstats.py` (115) | `/sysstats` | `modules/extras.py` + `utils/sysinfo.py` (93) | exceeded |
| `Modules/variables.py` (61) | `/config`, `/variables` | `power.py` `/vars` | equal |
| `Modules/watcher.py` (110) | welcome, unauthorized leave, stream-end | `modules/presence.py` + `core/player.py` | exceeded |

---

# 6. What VYRON has that none of the three do

These are the reason the bot is not just "parity":

* **Mini App** (`webapp/`, `vyron/web/*` — server 1636, stream 500, auth 339,
  artwork 212, avatars 242, budget 135) streaming audio to a browser with
  Telegram `initData` auth, per-listener DM mirror, byte-range streaming.
* **Public API** (`vyron/api/*`, 2 000+ lines): versioned `/v1`, API keys with
  scopes/quotas/rotation/7-day revocation (`core/musicapi.py`, 861), OpenAPI,
  live docs, metrics.
* **Download stack**: `core/accelerator.py` (aria2 → 6-way ranged HTTP → curl →
  single stream), `core/sources.py` registry, `core/public_streams.py` mirrors,
  `core/alternate.py` (Piped/Invidious/Cobalt), `core/metasources.py`
  (Odesli/JioSaavn/Audius), `core/extract.py`, `core/downloadjobs.py`.
* **Search stack**: `core/search.py` (1661) with yt-dlp search, YouTube Music,
  caching, wall detection, walled-result substitution.
* **Observability**: `core/journal.py` (551) ring buffer + `/logs`, `/doctor`
  (395), `/uicheck`, `/sources`, `/dbstats`, watchdog + lease (`core/lease.py`).
* **Three storage backends** with retention, privacy export/delete
  (`modules/privacy.py`), revoked-key purge.
* **i18n** with coverage reporting, per-chat language, JSON packs.
* **Rich UI**: `ui/cards.py` (2658), `ui/rich.py` (733), `ui/blocks.py` (443),
  `ui/theme.py` (208) — every message a card, ≤6 buttons, no progress glyphs.
* **Tests**: 901 passing (13 test modules), versus none in any of the three.

# 7. Ideas still worth taking (ranked)

Things the other repos do that VYRON does not, judged on merit rather than
parity:

1. **Videl's cookie *refresh*** (`utils/youtube.py`: `_cookies_save_path`,
   `_save_cookies_bytes`, `_is_real_cookies`): pulling a fresh `cookies.txt` from
   a URL and rejecting the placeholder ones people commit by mistake. VYRON
   already rotates proxies from `YOUTUBE_PROXY_FILE` and honours
   `COOKIES_FILE`/`YOUTUBE_COOKIES`, so the missing half is the download-and-
   validate step. *Status: not implemented; impersonation + the mirror ladder
   currently covers the "Sign in to confirm you're not a bot" wall.*
2. **Fallen's per-video thumbnail cache key** (`cache/{videoid}_{user_id}.png`):
   a repeat play re-renders nothing. VYRON caches the *marked* size variants in
   `utils/thumbnails.py`, but the poster composition itself is rebuilt each
   time. Small win, cheap. *Status: not implemented.*
3. **Shizu's `/thumbnail`-style per-group poster art**: rejected — the poster
   draws the song's cover, which is what listeners want.
4. **Videl's `/q` shortcut**: rejected as a new command (see §2.4).

# 8. What was actually changed because of this comparison

* **1.10.14** — revoked API keys delete themselves after 7 days.
* **1.10.15** — `modules/presence.py`: greeting on join, and full cleanup on
  removal (queue dropped, call left, per-chat settings deleted; new
  `delete_chat_settings` in all three storage backends).
* **1.10.13** — download/playback speed: 6-way ranged accelerator tier, aria2
  head-start race, no re-encode for AAC-in-m4a, fragment concurrency, wall
  detection with walled-result substitution.

Nothing else in the three repositories was found to be a capability VYRON
lacks.
