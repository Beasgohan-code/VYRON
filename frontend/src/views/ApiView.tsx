import {
  Activity,
  BadgeCheck,
  Check,
  Clipboard,
  Code2,
  Copy,
  ExternalLink,
  Fingerprint,
  Gauge,
  Globe2,
  KeyRound,
  Layers,
  Lock,
  Plus,
  RefreshCw,
  RotateCw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Zap,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import type { ApiHealth, ApiKey, ApiKeyOptions, ApiKeyPayload, ApiScope } from "../lib/types";

type Verb = "GET" | "POST" | "DELETE";

const ENDPOINTS: { method: Verb; path: string; hint: string; scope: ApiScope | "—" }[] = [
  { method: "POST", path: "/v1/tracks", hint: "Download audio by id, URL or query", scope: "download" },
  { method: "GET", path: "/v1/tracks/{video_id}", hint: "Metadata without downloading", scope: "read" },
  { method: "GET", path: "/v1/tracks/{video_id}/stream", hint: "Inline stream, Range supported", scope: "download" },
  { method: "GET", path: "/v1/search?q=…", hint: "Search YouTube", scope: "search" },
  { method: "GET", path: "/v1/lyrics?title=…", hint: "Synced lyrics from LRCLIB", scope: "read" },
  { method: "GET", path: "/v1/me", hint: "Your key, scopes, quota", scope: "—" },
  { method: "GET", path: "/v1/admin/keys", hint: "List every key, masked", scope: "admin" },
  { method: "POST", path: "/v1/admin/keys", hint: "Mint a key programmatically", scope: "admin" },
  { method: "DELETE", path: "/v1/admin/keys/{id}", hint: "Revoke by id or prefix", scope: "admin" },
  { method: "GET", path: "/v1/metrics", hint: "Traffic, volume, latency", scope: "admin" },
  { method: "GET", path: "/v1/health", hint: "Status and readiness", scope: "—" },
  { method: "GET", path: "/v1/openapi.json", hint: "OpenAPI 3.1 description", scope: "—" },
];

const SCOPES: { id: ApiScope; label: string; hint: string }[] = [
  { id: "read", label: "Read", hint: "metadata, lyrics, /me" },
  { id: "search", label: "Search", hint: "YouTube search" },
  { id: "download", label: "Download", hint: "audio files and streams" },
  { id: "admin", label: "Admin", hint: "keys + metrics (implies all)" },
];

const EXPIRY: { label: string; days: number | null }[] = [
  { label: "Never", days: null },
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

function bytes(value = 0): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(2)} GB`;
}

function ago(stamp?: number | null): string {
  if (!stamp) return "never";
  const delta = Math.max(0, Math.floor(Date.now() / 1000 - stamp));
  if (delta < 60) return `${delta}s ago`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
  if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
  return `${Math.floor(delta / 86400)}d ago`;
}

function until(stamp?: number | null): string {
  if (!stamp) return "never";
  const delta = Math.floor(stamp - Date.now() / 1000);
  if (delta <= 0) return "expired";
  if (delta < 86400) return `${Math.ceil(delta / 3600)}h left`;
  return `${Math.ceil(delta / 86400)}d left`;
}

export function ApiView() {
  const { toast } = useApp();
  const [payload, setPayload] = useState<ApiKeyPayload | null>(null);
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApiKey | null>(null);
  const [copied, setCopied] = useState("");
  const [ping, setPing] = useState<number | null>(null);
  const [tab, setTab] = useState<"curl" | "python" | "node">("curl");

  const [label, setLabel] = useState("my-bot");
  const [scopes, setScopes] = useState<ApiScope[]>(["read", "search", "download"]);
  const [days, setDays] = useState<number | null>(null);
  const [rateLimit, setRateLimit] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const [keys, status] = await Promise.all([api.keys(), api.apiHealth().catch(() => null)]);
      setPayload(keys);
      if (status) setHealth(status);
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not load the API", "error");
    } finally {
      setBusy(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const base = payload?.base || window.location.origin;
  const docs = payload?.docs || "/v1/docs";
  const openapi = payload?.openapi || "/v1/openapi.json";
  const keys = payload?.keys ?? [];
  const stats = payload?.stats;
  const metrics = payload?.metrics;
  const live = health?.status === "ok";
  const isOwner = Boolean(payload?.is_owner);

  const copy = async (value: string, tag: string) => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      const field = document.createElement("textarea");
      field.value = value;
      document.body.appendChild(field);
      field.select();
      document.execCommand("copy");
      field.remove();
    }
    setCopied(tag);
    window.setTimeout(() => setCopied(""), 1600);
  };

  const toggleScope = (scope: ApiScope) => {
    setScopes((current) => {
      if (scope === "admin") return current.includes("admin") ? ["read", "search", "download"] : ["read", "search", "download", "admin"];
      return current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope];
    });
  };

  const create = async () => {
    if (!isOwner) return;
    setBusy(true);
    try {
      const options: ApiKeyOptions = {
        label: label.trim() || "web",
        scopes,
        days,
        rate_limit: rateLimit.trim() ? Number(rateLimit) : null,
      };
      const result = await api.createKey(options);
      setCreated(result.created ?? null);
      toast("API key created — copy it now", "success");
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create a key", "error");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (key: ApiKey) => {
    const identifier = key.id || key.prefix || key.key || "";
    if (!identifier) return;
    setBusy(true);
    try {
      await api.revokeKey(identifier);
      toast(`Revoked ${key.label || key.masked || identifier}`, "success");
      if (created && created.id === key.id) setCreated(null);
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not revoke that key", "error");
    } finally {
      setBusy(false);
    }
  };

  const rotate = async (key: ApiKey) => {
    const identifier = key.id || key.prefix || "";
    if (!identifier) return;
    setBusy(true);
    try {
      const result = await api.rotateKey(identifier);
      setCreated(result.created ?? null);
      toast("Key rotated — the old one is dead", "success");
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not rotate that key", "error");
    } finally {
      setBusy(false);
    }
  };

  const snippets = useMemo(() => {
    const secret = created?.key ?? "vyrn_xxxxxxxx";
    return {
      curl: `curl -X POST "${base}/v1/tracks" \\
  -H "X-API-Key: ${secret}" \\
  -H "Content-Type: application/json" \\
  -d '{"video_id":"dQw4w9WgXcQ"}' --output track.mp3

# stream with Range support (seekable in any player)
curl -L "${base}/v1/tracks/dQw4w9WgXcQ/stream?download=1" \\
  -H "X-API-Key: ${secret}" --output track.mp3`,
      python: `import requests

KEY = "${secret}"
BASE = "${base}"

r = requests.post(f"{BASE}/v1/tracks",
                  headers={"X-API-Key": KEY},
                  json={"video_id": "dQw4w9WgXcQ"}, stream=True)
r.raise_for_status()
with open("track.mp3", "wb") as fh:
    for chunk in r.iter_content(1 << 16):
        fh.write(chunk)`,
      node: `const res = await fetch("${base}/v1/tracks", {
  method: "POST",
  headers: {
    "X-API-Key": "${secret}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ video_id: "dQw4w9WgXcQ" }),
});
if (!res.ok) throw new Error(await res.text());
const file = Buffer.from(await res.arrayBuffer());
await fs.writeFile("track.mp3", file);`,
    };
  }, [base, created]);

  const measure = async () => {
    const started = performance.now();
    try {
      await api.apiHealth();
      setPing(Math.round(performance.now() - started));
      toast("API answered", "success");
    } catch {
      setPing(-1);
      toast("API did not answer", "error");
    }
  };

  return (
    <section className="view active api-view">
      <div className="view-head row-between">
        <div>
          <h1>Music API</h1>
          <p className="muted">
            A professional, Eldian-compatible music API served by this exact deployment — no second
            service, no second port.
          </p>
        </div>
        <div className="head-actions">
          <span className={`api-status ${live ? "on" : "off"}`}>
            <i />
            {live ? "live" : health ? "degraded" : "offline"}
          </span>
          <button type="button" className="pill-btn ghost" onClick={() => void measure()}>
            <Activity size={14} /> {ping === null ? "Test" : ping < 0 ? "down" : `${ping} ms`}
          </button>
          <button type="button" className="pill-btn ghost" onClick={() => void load()} disabled={busy}>
            <RefreshCw size={14} className={busy ? "spin" : undefined} /> Refresh
          </button>
        </div>
      </div>

      {!payload && (
        <div className="api-grid">
          <div className="skeleton-card tall" aria-hidden="true" />
          <div className="skeleton-card tall" aria-hidden="true" />
        </div>
      )}

      <div className="api-grid" aria-busy={!payload}>
        <article className="panel api-hero">
          <div className="panel-head">
            <h3>
              <Globe2 size={14} /> Base URL
            </h3>
            <span className="tag">API v{stats?.version ?? "2.0"}</span>
          </div>
          <button type="button" className="copy-field" onClick={() => void copy(base, "base")}>
            <code>{base}</code>
            {copied === "base" ? <Check size={15} /> : <Copy size={15} />}
          </button>
          <div className="api-chips">
            <span className="chip tiny">
              <Zap size={12} /> {stats?.rate_limit ?? 30} req/min
            </span>
            <span className="chip tiny">
              <KeyRound size={12} /> {stats?.keys ?? 0} keys
            </span>
            <span className="chip tiny">
              <Layers size={12} /> {payload?.scopes?.length ?? 4} scopes
            </span>
            <span className={`chip tiny ${stats?.open ? "warn" : "on"}`}>
              <ShieldCheck size={12} /> {stats?.open ? "open mode" : "keyed"}
            </span>
            <span className="chip tiny">
              <Fingerprint size={12} /> {stats?.storage ?? "json"}
            </span>
          </div>
          <p className="muted small">
            {health?.ready
              ? "Ready — downloads, search and lyrics are online."
              : "The bot process is still booting; endpoints answer as soon as it is ready."}
          </p>
          <div className="api-links">
            <a className="pill-btn ghost" href={docs} target="_blank" rel="noreferrer">
              <ExternalLink size={13} /> Docs
            </a>
            <a className="pill-btn ghost" href={openapi} target="_blank" rel="noreferrer">
              <Code2 size={13} /> OpenAPI
            </a>
            <a className="pill-btn ghost" href="/v1/health" target="_blank" rel="noreferrer">
              <Activity size={13} /> /health
            </a>
          </div>
        </article>

        <article className="panel api-meter">
          <div className="panel-head">
            <h3>
              <Gauge size={14} /> Live traffic
            </h3>
            <span className="tag">this process</span>
          </div>
          <div className="meter-grid">
            <div className="meter">
              <span>Requests</span>
              <b>{metrics?.requests ?? stats?.requests ?? 0}</b>
            </div>
            <div className="meter">
              <span>Downloads</span>
              <b>{metrics?.downloads ?? 0}</b>
            </div>
            <div className="meter">
              <span>Served</span>
              <b>{bytes(metrics?.bytes_served ?? stats?.bytes ?? 0)}</b>
            </div>
            <div className="meter">
              <span>Throttled</span>
              <b className={metrics?.rate_limited ? "warn-text" : ""}>{metrics?.rate_limited ?? 0}</b>
            </div>
            <div className="meter">
              <span>p50</span>
              <b>{metrics?.latency_ms?.p50 ?? 0} ms</b>
            </div>
            <div className="meter">
              <span>p95</span>
              <b>{metrics?.latency_ms?.p95 ?? 0} ms</b>
            </div>
          </div>
          <div className="latency-bar" aria-hidden="true">
            <i style={{ width: `${Math.min(100, (metrics?.latency_ms?.p50 ?? 0) * 4)}%` }} />
            <i style={{ width: `${Math.min(100, (metrics?.latency_ms?.p95 ?? 0) * 4)}%` }} />
            <i style={{ width: `${Math.min(100, (metrics?.latency_ms?.p99 ?? 0) * 4)}%` }} />
          </div>
          <p className="muted small">
            Per-key windows reset every 60 seconds. Every response carries{" "}
            <code>X-RateLimit-Limit</code>, <code>X-RateLimit-Remaining</code> and{" "}
            <code>X-RateLimit-Reset</code>.
          </p>
        </article>
      </div>

      {created && (
        <article className="panel key-spotlight">
          <div className="panel-head">
            <h3>
              <BadgeCheck size={14} /> New key
            </h3>
            <span className="tag">shown once</span>
          </div>
          <p className="muted small">
            <b>{created.label}</b> — copy it into your client's environment now. Keys are stored as
            SHA-256 hashes, so this value cannot be recovered later.
          </p>
          <button type="button" className="copy-field" onClick={() => void copy(created.key ?? "", "fresh")}>
            <code>{created.key}</code>
            {copied === "fresh" ? <Check size={15} /> : <Copy size={15} />}
          </button>
          <div className="api-chips">
            {(created.scopes ?? []).map((scope) => (
              <span key={scope} className="chip tiny on">
                <Lock size={12} /> {scope}
              </span>
            ))}
            <span className="chip tiny">
              <Gauge size={12} /> {created.rate_limit ?? stats?.rate_limit ?? 30}/min
            </span>
            <span className="chip tiny">
              <Sparkles size={12} /> {created.expires_at ? until(created.expires_at) : "never expires"}
            </span>
          </div>
          <div className="api-links">
            <button type="button" className="pill-btn accent" onClick={() => void copy(snippets.curl, "code")}>
              <Clipboard size={13} /> Copy curl
            </button>
            <button type="button" className="pill-btn ghost" onClick={() => setCreated(null)}>
              Done
            </button>
          </div>
        </article>
      )}

      <div className="api-grid">
        <article className="panel">
          <div className="panel-head">
            <h3>
              <Plus size={14} /> Mint a key
            </h3>
            <span className="tag">{isOwner ? "owner" : "read-only"}</span>
          </div>

          {isOwner ? (
            <>
              <label className="field">
                <span>Label</span>
                <input
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  placeholder="my-bot"
                  maxLength={40}
                />
              </label>

              <div className="field">
                <span>Scopes</span>
                <div className="scope-grid">
                  {SCOPES.map((scope) => (
                    <button
                      key={scope.id}
                      type="button"
                      className={`scope-toggle ${scopes.includes(scope.id) ? "on" : ""}`}
                      onClick={() => toggleScope(scope.id)}
                      aria-pressed={scopes.includes(scope.id)}
                    >
                      <b>{scope.label}</b>
                      <small>{scope.hint}</small>
                    </button>
                  ))}
                </div>
              </div>

              <div className="field-row">
                <label className="field">
                  <span>Expires</span>
                  <select value={days === null ? "never" : String(days)} onChange={(event) => setDays(event.target.value === "never" ? null : Number(event.target.value))}>
                    {EXPIRY.map((option) => (
                      <option key={option.label} value={option.days === null ? "never" : String(option.days)}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>Rate / min</span>
                  <input
                    value={rateLimit}
                    onChange={(event) => setRateLimit(event.target.value.replace(/\D/g, "").slice(0, 4))}
                    placeholder={String(stats?.rate_limit ?? 30)}
                    inputMode="numeric"
                  />
                </label>
              </div>

              <button type="button" className="pill-btn accent wide" onClick={() => void create()} disabled={busy}>
                <Plus size={14} /> Create key
              </button>
              <p className="muted small">
                Defaults: <code>read</code>, <code>search</code>, <code>download</code>. Add{" "}
                <code>admin</code> only when you need key management or metrics — it implies every
                other scope.
              </p>
            </>
          ) : (
            <p className="muted small">
              Only the bot owner can mint keys. Ask them for one, or run <code>/getapi</code> in a DM.
            </p>
          )}
        </article>

        <article className="panel">
          <div className="panel-head">
            <h3>
              <KeyRound size={14} /> Keys
            </h3>
            <span className="tag">
              {keys.filter((item) => item.active !== false).length}/{keys.length} active
            </span>
          </div>

          <ul className="key-list">
            {keys.map((item) => {
              const identifier = item.id || item.prefix || item.key || item.masked || "key";
              const scopeList = item.scopes ?? ["read", "search", "download"];
              return (
                <li key={identifier} className={item.active === false ? "off" : ""}>
                  <div className="key-main">
                    <b>{item.label || "key"}</b>
                    <code>{item.masked ?? item.prefix ?? item.key}</code>
                  </div>
                  <div className="key-scopes">
                    {scopeList.map((scope) => (
                      <span key={scope} className="chip tiny">
                        {scope}
                      </span>
                    ))}
                    {item.rate_limit ? <span className="chip tiny">≤{item.rate_limit}/min</span> : null}
                    {item.expires_at ? (
                      <span className={`chip tiny ${item.expired ? "warn" : ""}`}>{until(item.expires_at)}</span>
                    ) : null}
                  </div>
                  <div className="key-meta">
                    <span>{item.uses ?? 0} uses</span>
                    <span>{bytes(item.bytes ?? 0)}</span>
                    <span>{ago(item.last_used_at)}</span>
                    <span>{item.active === false ? "revoked" : "active"}</span>
                  </div>
                  {isOwner && (
                    <div className="key-actions">
                      <button
                        type="button"
                        className="icon-btn"
                        aria-label={`Rotate ${item.label || "key"}`}
                        disabled={busy || item.active === false}
                        onClick={() => void rotate(item)}
                      >
                        <RotateCw size={14} />
                      </button>
                      <button
                        type="button"
                        className="icon-btn danger"
                        aria-label={`Revoke ${item.label || "key"}`}
                        disabled={busy || item.active === false}
                        onClick={() => void revoke(item)}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {keys.length === 0 && <p className="empty-state">No keys yet — create one to start calling the API.</p>}
        </article>
      </div>

      <article className="panel">
        <div className="panel-head">
          <h3>
            <Code2 size={14} /> Endpoints
          </h3>
          <span className="tag">tap to copy</span>
        </div>
        <div className="endpoint-table">
          {ENDPOINTS.map((endpoint) => (
            <button
              key={`${endpoint.method}-${endpoint.path}`}
              type="button"
              className="endpoint-row"
              onClick={() => void copy(`${base}${endpoint.path}`, endpoint.path)}
            >
              <span className={`verb ${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
              <code>{endpoint.path}</code>
              <span className="hint">{endpoint.hint}</span>
              <span className={`lock ${endpoint.scope === "—" ? "open" : ""}`}>{endpoint.scope}</span>
            </button>
          ))}
        </div>
      </article>

      <article className="panel">
        <div className="panel-head">
          <h3>
            <Zap size={14} /> Quick start
          </h3>
          <div className="segmented small" role="tablist">
            {(["curl", "python", "node"] as const).map((key) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                className={tab === key ? "active" : ""}
                onClick={() => setTab(key)}
              >
                {key === "node" ? "Node" : key === "python" ? "Python" : "cURL"}
              </button>
            ))}
          </div>
        </div>
        <div className="code-block">
          <pre>
            <code>{snippets[tab]}</code>
          </pre>
          <button type="button" className="code-copy" aria-label="Copy snippet" onClick={() => void copy(snippets[tab], "code")}>
            {copied === "code" ? <Check size={14} /> : <Copy size={14} />}
          </button>
        </div>
        <p className="muted small">
          Keys live in MongoDB when <code>MONGO_URL</code> is set, otherwise in a local JSON file.
          Missing keys return <code>401</code>, revoked or expired keys <code>403</code>,
          over-quota requests <code>429</code> with <code>Retry-After</code>.
        </p>
      </article>
    </section>
  );
}
