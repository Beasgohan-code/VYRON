# Troubleshooting

Start with two commands in Telegram:

* `/doctor` — one card: voice engine, downloader, storage, sources, instance role,
  web app, cookies, impersonation.
* `/dbstats` — backend, ping, sizes, counters, cache, last housekeeping sweep.

Everything below assumes you have those two outputs. If the bot does not start at
all, read the deploy log first — it names the missing variable.

---

## The service is up but every API call is 503

`{"code": "not_ready"}` comes from the boot gate, not from a failure. The HTTP
server answers immediately (that is what Render/Koyeb health checks need) while
the voice engine and downloader finish starting. `GET /health` is 200 the whole
time; `GET /ready` is the one that says 503, with `Retry-After: 5`.

If it lasts longer than about a minute, the engine is genuinely stuck:

```bash
curl -s https://<your-app>.onrender.com/health | jq
curl -s https://<your-app>.onrender.com/ready | jq
```

The `problems` array in `/health` lists what failed, in words.

## "MongoDB unavailable — falling back to JSON"

The bot keeps running; nothing is lost. The cause is almost always Atlas →
**Network Access**: Render's egress IPs are not allowed, or `MONGO_URL` is missing
its scheme.

* the string must start with `mongodb://` or `mongodb+srv://`;
* allow `0.0.0.0/0` for a hosted bot, or add the host's IP;
* the database user needs read/write on the database named by `MONGO_DB`.

Three attempts with backoff are made on boot, so a single cold-start DNS miss is
not fatal. When the connection does succeed for the first time, an existing
`vyron.json` is imported once (marker: `meta.imported_from_json`) — you do not
need to re-add settings or keys.

## Playback fails with "This instance is a standby"

Two processes are running against one voice chat. Only one may stream; the second
one has taken a standby lease and is refusing to interrupt the first.

* scale the service to **one** instance;
* `/doctor` shows `instance · primary` or `standby (<id>)`;
* the lease expires after 90 s without a heartbeat, so a crashed instance never
  blocks the next deploy for longer than that.

## `429 quota_exceeded`

A per-key daily or monthly cap was hit. The error names the field:

```json
{"ok": false, "code": "quota_exceeded",
 "error": "daily_requests limit reached (200/day)"}
```

Raise it without rotating the key:

```bash
curl -X PATCH https://<app>/v1/admin/keys/<id> \
  -H "X-API-Key: vyrn_admin…" -H "Content-Type: application/json" \
  -d '{"daily_requests": 1000}'
```

`0` (or leaving the field out) means uncapped. `/v1/me` reports what a key has
used so far.

## `429 rate_limited`

That is the per-minute bucket, not the quota. Wait `X-RateLimit-Reset` seconds —
the header is in the response, and so is `Retry-After`.

## A Spotify, Deezer or Apple link plays the wrong version

The link is matched through song.link (Odesli) to an exact YouTube id and cached
for six hours. If the matcher is unreachable, the catalogue metadata is read and
the title is searched instead, which is where a remix can turn into a karaoke
track. `/v1/sources` lists `odesli` in the catalogue tier — that is the matcher's
health, not a source you can disable.

## `403 invalid_key` / `expired_key` / `forbidden_scope`

* keys are shown in full once, at creation — if it is lost, mint a new one;
* `expired_key` means the key's date passed (`PATCH` to extend, or mint again);
* `forbidden_scope` means the route needs a scope the key does not have
  (`download` for files, `admin` for key management and metrics).

The owner token (`/apitoken`) has every scope and can always mint a replacement.

## The Mini App is blank, or shows an old build

A service worker is serving the previous shell. Reload once — the app offers a
"newer VYRON is ready" chip when it detects one. The worker is versioned
(`vyron-1`) and deletes older caches on activate; assets are content-hashed, so a
new deploy is picked up on the next navigation.

If the page never loads at all:

```bash
curl -s https://<app>/app/ | head -5      # shell
curl -s https://<app>/app/sw.js | head -3 # offline worker
```

`web app not built` in that output means `webapp/dist` is missing — run
`npm install && npm run build` in `frontend/` (the Docker image does this for you).

## Nothing plays in the group

* the assistant must be in the voice chat: `/doctor` → voice engine;
* start a voice chat first, then `/play`;
* a group call that is full (or a channel) cannot accept the assistant;
* `pytgcalls` errors are logged with the peer id in `/logs`.

## Downloads are slow or time out

The downloader tries IPv4 first, then a different client, then the resolver stack
(Invidious → Piped → Cobalt) — see `/doctor` and `/v1/sources?probe=1`. A 502
`upstream_failed` means every tier failed for that id; retrying usually works,
because the failure is upstream and per-video.

## Logs

* `/logs` — the journal, last lines, filterable (`/logs error`);
* `/logs live` — a stream in the browser, owner-only;
* `GET /health` → `instance`, `database`, `problems`, `resolvers`.

Secrets are redacted before they reach any of these (`RedactFilter`): tokens,
cookies and `MONGO_URL` credentials never appear in logs or the journal.
