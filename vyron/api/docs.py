# ---------------------------------------------------------------------------
#  VYRON API — documentation site (GET /v1/docs)
#
#  A single, dependency-free HTML page: sticky sidebar, endpoint reference,
#  copy-to-clipboard snippets and a live "check status" button.  Rendered from
#  a Template so the CSS can use normal braces.
# ---------------------------------------------------------------------------
from __future__ import annotations

from html import escape
from string import Template

from aiohttp import web

from vyron.api.app import API_VERSION
from vyron.config import settings
from vyron.runtime import runtime

from vyron.api.routes import base_url

CSS = """
:root{color-scheme:dark;--bg:#07070d;--panel:#0e0e18;--line:rgba(255,255,255,.09);
--text:#f4f4fa;--muted:#9a9ab4;--dim:#6c6c85;--accent:#8b5cf6;--accent2:#22d3ee;
--ok:#34d399;--warn:#fbbf24;--bad:#f87171}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.65 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Inter,sans-serif;-webkit-font-smoothing:antialiased}
a{color:#93c5fd;text-decoration:none}
a:hover{text-decoration:underline}
.glow{position:fixed;inset:-25% -10% auto;height:62vh;pointer-events:none;z-index:0;
background:radial-gradient(45% 45% at 22% 18%,rgba(139,92,246,.34),transparent 70%),
radial-gradient(38% 38% at 82% 0%,rgba(34,211,238,.18),transparent 70%);filter:blur(28px)}
header.top{position:sticky;top:0;z-index:20;display:flex;align-items:center;gap:14px;
padding:12px 22px;border-bottom:1px solid var(--line);background:rgba(7,7,13,.82);backdrop-filter:blur(18px)}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;letter-spacing:.02em}
.brand .mark{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;
background:linear-gradient(140deg,var(--accent),var(--accent2));color:#08080e;font-size:15px}
.brand small{display:block;font-weight:500;font-size:11px;color:var(--dim);letter-spacing:.02em}
.status{margin-left:auto;display:flex;align-items:center;gap:8px;padding:6px 12px;border-radius:999px;
border:1px solid var(--line);font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.status i{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 0 3px rgba(52,211,153,.18)}
.status button{all:unset;cursor:pointer;color:var(--accent2);font-size:11.5px}
.layout{position:relative;z-index:1;display:grid;grid-template-columns:236px minmax(0,1fr);gap:34px;
max-width:1180px;margin:0 auto;padding:34px 22px 100px}
nav.side{position:sticky;top:78px;align-self:start;display:flex;flex-direction:column;gap:2px;
border-right:1px solid var(--line);padding-right:16px}
nav.side span{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--dim);margin:16px 0 6px}
nav.side a{padding:5px 8px;border-radius:7px;color:var(--muted);font-size:13px}
nav.side a:hover{background:rgba(255,255,255,.05);color:var(--text);text-decoration:none}
main{min-width:0}
h1{font-size:clamp(28px,4.4vw,42px);line-height:1.08;margin:0 0 10px;letter-spacing:-.025em}
.lede{font-size:16px;color:var(--muted);max-width:66ch}
h2{font-size:22px;margin:46px 0 12px;letter-spacing:-.01em;scroll-margin-top:80px}
h3{font-size:15px;margin:24px 0 8px;color:var(--text)}
p{color:var(--muted)}
.badges{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 0}
.badge{padding:5px 11px;border-radius:999px;border:1px solid var(--line);font-size:11.5px;color:var(--muted)}
.badge b{color:var(--text)}
.card{border:1px solid var(--line);background:var(--panel);border-radius:16px;padding:18px 20px;margin:16px 0}
.card.base{display:flex;flex-wrap:wrap;gap:12px;align-items:center}
.card.base code{font-size:14px}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.8px;
background:rgba(255,255,255,.06);padding:2px 6px;border-radius:6px;color:#e6e6f5}
pre{position:relative;margin:12px 0;padding:16px;border-radius:14px;overflow:auto;
background:#0a0a12;border:1px solid var(--line)}
pre code{background:none;padding:0;font-size:12.6px;line-height:1.6;color:#d8d8ea}
.copy{position:absolute;top:9px;right:9px;padding:5px 10px;border-radius:8px;cursor:pointer;
background:rgba(255,255,255,.06);border:1px solid var(--line);color:var(--muted);font-size:11px}
.copy:hover{color:var(--text);border-color:rgba(255,255,255,.2)}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:13.4px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);font-weight:600}
td code{white-space:nowrap}
.verb{display:inline-block;min-width:52px;text-align:center;font-size:10px;font-weight:700;
letter-spacing:.08em;padding:3px 7px;border-radius:6px}
.get{background:rgba(34,211,238,.16);color:#67e8f9}
.post{background:rgba(139,92,246,.22);color:#c4b5fd}
.del{background:rgba(248,113,113,.18);color:#fca5a5}
.tag{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--dim)}
.ok{color:var(--ok)} .warn{color:var(--warn)} .bad{color:var(--bad)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.note{border-left:2px solid var(--accent);padding:10px 14px;background:rgba(139,92,246,.08);
border-radius:0 10px 10px 0;color:var(--muted);font-size:13.4px;margin:14px 0}
footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);color:var(--dim);font-size:12px;
display:flex;flex-wrap:wrap;gap:14px;justify-content:space-between}
@media(max-width:900px){
 .layout{grid-template-columns:1fr;gap:10px;padding:22px 16px 80px}
 nav.side{position:static;flex-direction:row;overflow-x:auto;border-right:none;border-bottom:1px solid var(--line);
 padding:0 0 10px;gap:6px}
 nav.side span{display:none}
 nav.side a{white-space:nowrap;font-size:12px}
 .cols{grid-template-columns:1fr}
 header.top{padding:10px 14px}
 .status{font-size:10px;padding:5px 9px}
}
"""

SECTIONS = [
    ("overview", "Overview"),
    ("quickstart", "Quick start"),
    ("auth", "Authentication"),
    ("scopes", "Scopes"),
    ("endpoints", "Endpoints"),
    ("download", "Download API"),
    ("errors", "Errors"),
    ("limits", "Rate limits"),
    ("metrics", "Metrics"),
    ("troubleshooting", "Troubleshooting"),
    ("changelog", "Changelog"),
]

ENDPOINTS = [
    ("GET", "/v1/health", "Liveness, readiness, counters", "—"),
    ("GET", "/v1/version", "API + bot versions", "—"),
    ("POST", "/v1/tracks", "Download audio (video id, URL or query)", "download"),
    ("GET", "/v1/tracks/{video_id}", "Track metadata, no download", "read"),
    ("GET", "/v1/tracks/{video_id}/stream", "Inline stream, Range supported", "download"),
    ("POST", "/v1/downloads", "Start a job → 202 {job_id}", "download"),
    ("GET", "/v1/downloads/{job_id}", "Poll progress, size, download_url", "download"),
    ("GET", "/v1/downloads/{job_id}/file", "Fetch the finished file (Range)", "download"),
    ("DELETE", "/v1/downloads/{job_id}", "Cancel a queued or running job", "download"),
    ("GET", "/v1/search?q=…", "Search YouTube (or POST JSON)", "search"),
    ("GET", "/v1/lyrics?title=…", "Synced lyrics from LRCLIB", "read"),
    ("GET", "/v1/me", "Your key, capabilities, usage and expiry", "—"),
    ("GET", "/v1/ready", "readiness — 503 until the engine exists", "—"),
    ("POST", "/v1/token", "Short-lived browser token (Bearer vyt_…)", "read"),
    ("GET", "/v1/sources", "Every source in fallback order, with live health", "—"),
    ("GET", "/v1/sources/{name}", "One source's detail", "—"),
    ("GET", "/v1/admin/keys", "List keys (masked)", "admin"),
    ("POST", "/v1/admin/keys", "Mint a key — returned once", "admin"),
    ("GET", "/v1/admin/keys/{id}", "One key's detail", "admin"),
    ("PATCH", "/v1/admin/keys/{id}", "Edit label, scopes, expiry or quota", "admin"),
    ("DELETE", "/v1/admin/keys/{id}", "Revoke a key by id or prefix", "admin"),
    ("GET", "/v1/metrics", "JSON metrics (or Prometheus text)", "admin"),
]

#: symptom → cause → the one thing to do. Written from real reports, not theory.
TROUBLES = [
    (
        "503 on every request for a minute after deploy",
        "not_ready — the boot gate. The bot is connected but the voice engine and "
        "downloader are still starting.",
        "Retry after <code>Retry-After</code>. Nothing is broken: <code>/health</code> "
        "answers 200 the whole time, only <code>/ready</code> waits.",
    ),
    (
        "429 <code>quota_exceeded</code>",
        "This key hit its daily or monthly cap (requests or bytes). The error names "
        "the field.",
        "Raise the cap with <code>PATCH /v1/admin/keys/{id}</code> — no key rotation, "
        "no downtime. <code>0</code> or omission means uncapped.",
    ),
    (
        "Downloads work, playback says “standby”",
        "Two instances of the bot are running. Only one of them may stream to a "
        "voice chat.",
        "Scale the Render/Koyeb service to one instance. <code>/doctor</code> and "
        "<code>/health</code> both report which process owns the call.",
    ),
    (
        "MongoDB falls back to JSON",
        "<code>MONGO_URL</code> was unreachable from the host (Atlas → Network "
        "Access), or the string is missing its scheme.",
        "Allow <code>0.0.0.0/0</code> in Atlas Network Access and redeploy. The bot "
        "keeps serving on JSON meanwhile — nothing is lost, and the first successful "
        "connection imports the JSON data once.",
    ),
    (
        "A Spotify/Deezer link plays the wrong remix",
        "The catalogue page was unreadable, so the title was searched instead of "
        "matched.",
        "Nothing to do — song.link matching is tried first and cached six hours. If "
        "it is down, the plain search is the fallback.",
    ),
    (
        "Mini App shows a blank screen after a deploy",
        "A service worker is holding the previous build.",
        "Reload once (the app offers a chip); the worker is versioned and swaps on "
        "the next visit.",
    ),
]

ERRORS = [
    ("400", "bad_request · invalid_video · missing_query", "fix the request body/query"),
    ("401", "missing_key", "send X-API-Key"),
    ("403", "invalid_key · revoked_key · expired_key · forbidden_scope", "mint or rotate a key"),
    ("404", "not_found", "unknown track/key"),
    ("429", "rate_limited", "wait X-RateLimit-Reset seconds"),
    ("502", "upstream_failed", "YouTube/yt-dlp hiccup — retry"),
    ("503", "not_ready", "the bot is still booting"),
]

CHANGELOG = [
    ("2.3", "GET /v1/ready is a real readiness probe (503 + Retry-After until the engine is up), "
           "while /v1/health and /v1/ready never disagree. Per-key daily/monthly quotas on "
           "requests and bytes answer 429 <code>quota_exceeded</code>. POST /v1/token mints a "
           "short-lived browser token; POST /v1/downloads accepts an Idempotency-Key."),
    ("2.2", "GET /v1/sources?probe=1 measures each source instead of guessing, source health "
           "survives a restart, and /v1/metrics exports it as Prometheus gauges."),
    ("2.1", "GET /v1/sources and /v1/sources/{name} — the fallback chain and each source's health. "
           "GET /v1/me now reports capabilities, expiry and usage. Key detail + non-destructive "
           "PATCH (label, scopes, expiry, per-key rate limit) replace revoke-and-reissue."),
    ("2.0", "Hashed keys, scopes, expiry, rotation, admin endpoints, metrics (JSON + Prometheus), "
           "canonical REST routes, OpenAPI 3.1, richer error envelope, request ids."),
    ("1.0", "the original track download, search, metadata, lyrics, keys and docs."),
]


def _endpoint_rows(base: str) -> str:
    rows = []
    for method, path, description, scope in ENDPOINTS:
        verb = {"GET": "get", "POST": "post", "DELETE": "del"}.get(method, "get")
        anchor = escape(path.split("?")[0].replace("/v1", "").strip("/") or "root")
        rows.append(
            f'<tr><td><span class="verb {verb}">{method}</span></td>'
            f'<td><code><a href="#{anchor}">{escape(path)}</a></code></td>'
            f"<td>{escape(description)}</td>"
            f'<td class="tag">{escape(scope)}</td></tr>'
        )
    return "".join(rows)


def _scope_rows() -> str:
    rows = [
        ("read", "metadata, lyrics, /me", "GET /tracks/{id}, /lyrics, /me"),
        ("search", "YouTube search", "GET+POST /search"),
        ("download", "audio files, streams and download jobs", "POST /tracks, GET /tracks/{id}/stream, /downloads"),
        ("admin", "key management + metrics", "/admin/*, /metrics"),
    ]
    return "".join(
        f"<tr><td><code>{scope}</code></td><td>{escape(what)}</td><td><code>{escape(where)}</code></td></tr>"
        for scope, what, where in rows
    )


def _error_rows() -> str:
    return "".join(
        f'<tr><td><span class="badge"><b>{code}</b></span></td><td><code>{escape(kinds)}</code></td>'
        f"<td>{escape(fix)}</td></tr>"
        for code, kinds, fix in ERRORS
    )


def _trouble_rows() -> str:
    return "".join(
        f"<tr><td><b>{symptom}</b></td><td>{cause}</td><td>{fix}</td></tr>"
        for symptom, cause, fix in TROUBLES
    )


def _changelog_rows() -> str:
    return "".join(
        f"<tr><td><b>{version}</b></td><td>{escape(text)}</td></tr>" for version, text in CHANGELOG
    )


PAGE = Template("""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="description" content="VYRON Music API — downloads, streaming, search, lyrics for Telegram bots."/>
<title>VYRON Music API · docs</title>
<style>$css</style>
</head>
<body>
<div class="glow"></div>
<header class="top">
  <div class="brand"><span class="mark">◈</span><span>VYRON Music API<small>v$api_version · $bot_version</small></span></div>
  <div class="status"><i></i> $status_text
    <button id="ping" title="Call /v1/health">check</button>
  </div>
</header>
<div class="layout">
  <nav class="side">
    <span>Guide</span>
    $nav_links
    <span>Reference</span>
    <a href="$openapi">OpenAPI 3.1</a>
    <a href="$app">Mini App</a>
    <a href="$repo" target="_blank" rel="noreferrer">GitHub ↗</a>
  </nav>
  <main>
    <h1>Music API</h1>
    <p class="lede">Downloads, streaming, search, metadata and lyrics for Telegram music bots —
    served by <b>@$bot</b> on the same URL as its Mini App. No second service, no extra port.</p>
    <div class="badges">
      <span class="badge">API <b>2.0</b></span>
      <span class="badge">Bot <b>$bot_version</b></span>
      <span class="badge">auth <b>$auth_mode</b></span>
      <span class="badge"><b>$key_count</b> active keys</span>
      <span class="badge">rate <b>$rate</b>/min</span>
    </div>

    <div class="card base">
      <span class="tag">Base URL</span> <code id="base">$base</code>
      <button class="copy" data-copy="$base">copy</button>
    </div>

    <h2 id="overview">Overview</h2>
    <p>The API is mounted at <code>/v1</code> on the deployment that runs the bot. It is
    <b>Drop-in</b>: the original <code>POST /v1/track/by-video-id</code> flow with an
    <code>X-API-Key</code> header keeps working, and the canonical routes below add scopes,
    metadata, streaming and metrics.</p>
    <div class="cols">
      <div class="card"><h3 style="margin-top:0">Designed for bots</h3>
        <p>One request returns a ready MP3. Search results already include
        <code>stream_url</code>, so a bot can stream without a second lookup.</p></div>
      <div class="card"><h3 style="margin-top:0">Safe by default</h3>
        <p>Keys are stored as SHA-256 hashes with scopes, expiry and per-key rate limits.
        Revocation is instant; every response carries <code>X-RateLimit-*</code>.</p></div>
    </div>

    <h2 id="quickstart">Quick start</h2>
    <p>Mint a key in the Mini App (<b>Music API → Create key</b>) or with <code>/getapi</code> in the bot,
    then:</p>
    $curl_download
    <p>Prefer streaming with Range support (seekable)?</p>
    $curl_stream

    <h2 id="auth">Authentication</h2>
    <p>Send the key any of these ways — the header is preferred:</p>
    <table><thead><tr><th>Where</th><th>Example</th></tr></thead><tbody>
      <tr><td>Header</td><td><code>X-API-Key: vyrn_…</code></td></tr>
      <tr><td>Bearer</td><td><code>Authorization: Bearer vyrn_…</code></td></tr>
      <tr><td>Query (dev only)</td><td><code>?key=vyrn_…</code></td></tr>
      <tr><td>Owner token</td><td><code>X-Owner-Token: vown_…</code> — every scope</td></tr>
    </tbody></table>
    <div class="note">Keys are shown in full <b>once</b>, when they are created. Store them in your
    client's environment — never in a public repo.</div>
    <p>The deployment owner can mint a signed token with <code>/apitoken</code> in the bot. It works
    as <code>X-Owner-Token</code> (or <code>X-API-Key</code>), grants every scope, is valid for 30
    days, and unlocks the Mini App at <code>/app/?ot=…</code> without Telegram auth. Rotating
    <code>BOT_TOKEN</code> revokes it instantly.</p>

    <h2 id="scopes">Scopes</h2>
    <table><thead><tr><th>Scope</th><th>Grants</th><th>Routes</th></tr></thead><tbody>$scope_rows</tbody></table>
    <p>Default keys get <code>read</code>, <code>search</code> and <code>download</code>.
    <code>admin</code> is for key management and metrics — mint it with <code>/getapi admin admin</code>
    or from the Mini App.</p>

    <h2 id="endpoints">Endpoints</h2>
    <table><thead><tr><th>Method</th><th>Path</th><th>What it does</th><th>Scope</th></tr></thead>
    <tbody>$endpoint_rows</tbody></table>

    <h3>Python client</h3>
    $python_sample
    <h3>Node / fetch</h3>
    $node_sample

    <h2 id="download">Download API — <code>/vyron</code></h2>
    <p>When a client only wants a file, skip the library. Two endpoints on this same
    URL download a track by id or by plain text and stream it straight back:</p>
    $vyron_curl
    <table><thead><tr><th>Method</th><th>Path</th><th>Body</th></tr></thead><tbody>
      <tr><td><span class="verb post">POST</span></td><td><code>/vyron/v1/track/by-video-id</code></td><td><code>{"video_id": "dQw4w9WgXcQ"}</code></td></tr>
      <tr><td><span class="verb post">POST</span></td><td><code>/vyron/v1/track/by-query</code></td><td><code>{"query": "kesariya arijit singh"}</code></td></tr>
      <tr><td><span class="verb get">GET</span></td><td><code>/vyron/health</code></td><td>engine status, format, retry and cookie state</td></tr>
    </tbody></table>
    <div class="note">Same keys, scopes and rate limits as <code>/v1</code> — one key works
    everywhere. Each response is a temp file that is deleted as soon as it has been sent, and
    only two downloads run at once so the bot's voice chat always keeps its share.</div>

    <h2 id="errors">Errors</h2>
    <p>Everything fails with the same envelope, including a <code>request_id</code> you can quote
    in a bug report:</p>
    $error_sample
    <table><thead><tr><th>Status</th><th>Codes</th><th>What to do</th></tr></thead><tbody>$error_rows</tbody></table>

    <h2 id="limits">Rate limits</h2>
    <p>Each key gets <b>$rate requests/minute</b> by default (override per key at creation).
    Responses include <code>X-RateLimit-Limit</code>, <code>X-RateLimit-Remaining</code> and
    <code>X-RateLimit-Reset</code>; a 429 also sends <code>Retry-After</code>.</p>
    <div class="note">Downloads are queued behind a two-slot semaphore so API traffic can never
    starve the bot's own voice-chat playback.</div>

    <h2 id="metrics">Metrics</h2>
    <p><code class="accent">GET /v1/metrics</code> (admin scope) returns request counts, download
    volume, latency percentiles and per-route hits. Add <code>?format=prometheus</code> to scrape it:</p>
    $prometheus_sample

    <h2 id="troubleshooting">Troubleshooting</h2>
    <p>The six things that actually go wrong, and what each one means. Nothing here
    needs a redeploy except the two that say so.</p>
    <table><thead><tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr></thead><tbody>$trouble_rows</tbody></table>
    <div class="note">Owner-only diagnosis lives in the bot: <code>/doctor</code> (one card,
    every subsystem), <code>/dbstats</code> (storage, sizes, last sweep) and
    <code>/logs</code> (the live journal).</div>

    <h2 id="changelog">Changelog</h2>
    <table><thead><tr><th>Version</th><th>Changes</th></tr></thead><tbody>$changelog_rows</tbody></table>

    <footer>
      <span>VYRON · @$bot · API $api_version</span>
      <span><a href="$openapi">openapi.json</a> · <a href="$app">Mini App</a> · <a href="$repo">source</a></span>
    </footer>
  </main>
</div>
<script>
document.querySelectorAll('.copy').forEach(function(btn){
  btn.addEventListener('click', function(){
    var text = btn.getAttribute('data-copy') || btn.parentElement.querySelector('code').textContent;
    navigator.clipboard.writeText(text).then(function(){
      var old = btn.textContent; btn.textContent = 'copied';
      setTimeout(function(){ btn.textContent = old; }, 1400);
    });
  });
});
var ping = document.getElementById('ping');
if (ping) ping.addEventListener('click', function(){
  var started = performance.now();
  fetch('/v1/health').then(function(r){ return r.json(); }).then(function(data){
    ping.textContent = Math.round(performance.now() - started) + ' ms';
    ping.title = 'ready: ' + data.ready + ' · keys: ' + data.keys;
  }).catch(function(){ ping.textContent = 'down'; });
});
</script>
</body></html>""")


def _code(text: str) -> str:
    return f'<pre><code>{escape(text)}</code><button class="copy">copy</button></pre>'


async def render(request: web.Request) -> web.Response:
    base = base_url(request)
    site = base[: -len("/v1")]
    from vyron.core.musicapi import get_music_api

    stats = await get_music_api().stats()

    auth_mode = "open" if settings.music_api_open else "required"
    health_ready = runtime.youtube is not None and runtime.downloader is not None

    curl_download = _code(
        'curl -X POST "' + base + '/tracks" \\\n'
        '  -H "X-API-Key: vyrn_xxxxxxxx" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        '  -d \'{"video_id":"dQw4w9WgXcQ"}\' --output track.mp3'
    )
    curl_stream = _code(
        'curl -L "' + base + '/tracks/dQw4w9WgXcQ/stream?download=1" \\\n'
        '  -H "X-API-Key: vyrn_xxxxxxxx" --output track.mp3'
    )
    python_sample = _code(
        "import requests\n\n"
        'KEY = "vyrn_xxxxxxxx"\n'
        'BASE = "' + base + '"\n\n'
        'r = requests.post(f"{BASE}/tracks",\n'
        '                  headers={"X-API-Key": KEY},\n'
        '                  json={"video_id": "dQw4w9WgXcQ"}, stream=True)\n'
        "r.raise_for_status()\n"
        'with open("track.mp3", "wb") as fh:\n'
        "    for chunk in r.iter_content(1 << 16):\n"
        "        fh.write(chunk)"
    )
    vyron_curl = _code(
        'curl -X POST "' + site + "/vyron" + '/v1/track/by-video-id" \\\n'
        '  -H "X-API-Key: vyrn_xxxxxxxx" \\\n'
        '  -H "Content-Type: application/json" \\\n'
        '  -d \'{"video_id":"dQw4w9WgXcQ"}\' --output track.m4a'
    )
    node_sample = _code(
        'const res = await fetch("' + base + '/tracks", {\n'
        "  method: 'POST',\n"
        "  headers: {\n"
        '    "X-API-Key": process.env.VYRON_API_KEY,\n'
        '    "Content-Type": "application/json",\n'
        "  },\n"
        '  body: JSON.stringify({ video_id: "dQw4w9WgXcQ" }),\n'
        "});\n"
        "if (!res.ok) throw new Error(await res.text());\n"
        "const audio = Buffer.from(await res.arrayBuffer());"
    )
    error_sample = _code(
        "{\n"
        '  "ok": false,\n'
        '  "error": "rate limit reached (30/min) — retry in 42s",\n'
        '  "code": "rate_limited",\n'
        '  "hint": "wait X-RateLimit-Reset seconds",\n'
        '  "request_id": "req_9f3c1a7b2d4e"\n'
        "}"
    )
    prometheus_sample = _code(
        "curl -s '" + base + '/metrics?format=prometheus" \\\n'
        '  -H "X-API-Key: vyrn_xxxxxxxx"'
    )

    html = PAGE.substitute(
        css=CSS,
        api_version=API_VERSION,
        bot_version=runtime.version,
        status_text="ready" if health_ready else "starting",
        nav_links="".join(
            f'<a href="#{anchor}">{escape(label)}</a>' for anchor, label in SECTIONS
        ),
        openapi=f"{base}/openapi.json",
        app=f"{site}/app/",
        repo=settings.git_repo,
        bot=escape(settings.bot_username),
        auth_mode=auth_mode,
        key_count=str(stats.get("keys", 0)),
        rate=str(settings.music_api_rate),
        base=escape(base),
        endpoint_rows=_endpoint_rows(base),
        scope_rows=_scope_rows(),
        error_rows=_error_rows(),
        trouble_rows=_trouble_rows(),
        changelog_rows=_changelog_rows(),
        curl_download=curl_download,
        vyron_curl=vyron_curl,
        curl_stream=curl_stream,
        python_sample=python_sample,
        node_sample=node_sample,
        error_sample=error_sample,
        prometheus_sample=prometheus_sample,
    )
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})


__all__ = ["render"]
