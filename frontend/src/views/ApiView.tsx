import {
  Activity,
  Check,
  Clipboard,
  Code2,
  Copy,
  ExternalLink,
  KeyRound,
  Plus,
  RefreshCw,
  Server,
  ShieldCheck,
  Trash2,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useApp } from "../lib/store";
import type { ApiHealth, ApiKey, ApiKeyPayload } from "../lib/types";

const ENDPOINTS: { method: "GET" | "POST"; path: string; hint: string; keyed: boolean }[] = [
  { method: "POST", path: "/v1/track/by-video-id", hint: "Download audio for a YouTube id", keyed: true },
  { method: "POST", path: "/v1/track/by-query", hint: "Download the first match for a query", keyed: true },
  { method: "POST", path: "/v1/search", hint: "Search YouTube, returns JSON", keyed: true },
  { method: "GET", path: "/v1/info/by-video-id", hint: "Metadata without downloading", keyed: true },
  { method: "GET", path: "/v1/lyrics", hint: "Lyrics and synced lines", keyed: true },
  { method: "GET", path: "/v1/key", hint: "Your key, usage and quota", keyed: true },
  { method: "GET", path: "/v1/health", hint: "Status, version, readiness", keyed: false },
  { method: "GET", path: "/v1/openapi.json", hint: "OpenAPI 3.1 description", keyed: false },
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

export function ApiView() {
  const { toast } = useApp();
  const [payload, setPayload] = useState<ApiKeyPayload | null>(null);
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [label, setLabel] = useState("my-bot");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<ApiKey | null>(null);
  const [copied, setCopied] = useState("");
  const [ping, setPing] = useState<number | null>(null);
  const [tab, setTab] = useState<"curl" | "python" | "node">("curl");

  const load = async () => {
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
  };

  useEffect(() => {
    void load();
  }, []);

  const base = payload?.base || window.location.origin;

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
    toast("Copied to clipboard", "success");
    window.setTimeout(() => setCopied(""), 1600);
  };

  const create = async () => {
    setBusy(true);
    try {
      const result = await api.createKey(label.trim() || "web");
      setCreated(result.created ?? null);
      toast("API key created", "success");
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not create a key", "error");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (key: ApiKey) => {
    setBusy(true);
    try {
      await api.revokeKey(key.key);
      toast(`Revoked ${key.masked ?? key.key.slice(0, 8)}`, "success");
      await load();
    } catch (error) {
      toast(error instanceof Error ? error.message : "Could not revoke that key", "error");
    } finally {
      setBusy(false);
    }
  };

  const snippets = useMemo(
    () => ({
      curl: `curl -X POST "${base}/v1/track/by-video-id" \\
  -H "X-API-Key: ${created?.key ?? "vyrn_xxxxxxxx"}" \\
  -H "Content-Type: application/json" \\
  -d '{"video_id":"dQw4w9WgXcQ"}' --output track.mp3`,
      python: `import requests

KEY = "${created?.key ?? "vyrn_xxxxxxxx"}"
BASE = "${base}"

r = requests.post(f"{BASE}/v1/track/by-video-id",
                  headers={"X-API-Key": KEY},
                  json={"video_id": "dQw4w9WgXcQ"}, stream=True)
r.raise_for_status()
with open("track.mp3", "wb") as fh:
    for chunk in r.iter_content(65536):
        fh.write(chunk)`,
      node: `const res = await fetch("${base}/v1/track/by-video-id", {
  method: "POST",
  headers: {
    "X-API-Key": "${created?.key ?? "vyrn_xxxxxxxx"}",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ video_id: "dQw4w9WgXcQ" }),
});
if (!res.ok) throw new Error(await res.text());
const file = Buffer.from(await res.arrayBuffer());
await fs.writeFile("track.mp3", file);`,
    }),
    [base, created]
  );

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

  const keys = payload?.keys ?? [];
  const stats = payload?.stats;
  const live = health?.status === "ok";

  return (
    <section className="view active api-view">
      <div className="view-head row-between">
        <div>
          <h1>Music API</h1>
          <p className="muted">
            Eldian-compatible API for other bots — served from this exact deployment, no second service.
          </p>
        </div>
        <div className="head-actions">
          <span className={`api-status ${live ? "on" : "off"}`}>
            <i />
            {live ? "live" : health ? "degraded" : "offline"}
          </span>
          <button type="button" className="pill-btn ghost" onClick={() => void measure()} title="Time one /v1/health request">
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
              <Server size={14} /> Base URL
            </h3>
            <span className="tag">{health ? `v${health.version}` : "—"}</span>
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
              <Activity size={12} /> {stats?.requests ?? 0} requests
            </span>
            <span className="chip tiny">
              <Clipboard size={12} /> {bytes(stats?.bytes ?? 0)}
            </span>
            <span className={`chip tiny ${stats?.open ? "warn" : "on"}`}>
              <ShieldCheck size={12} /> {stats?.open ? "open mode" : "keyed"}
            </span>
          </div>
          <p className="muted small">
            {health?.ready
              ? "Ready — downloads, search and lyrics are online."
              : "The bot process is still booting; endpoints answer as soon as it is ready."}
          </p>
        </article>

        <article className="panel">
          <div className="panel-head">
            <h3>
              <KeyRound size={14} /> API keys
            </h3>
            <span className="tag">{payload?.is_owner ? "owner" : "read-only"}</span>
          </div>

          {created && (
            <div className="key-reveal">
              <span>
                <b>{created.label}</b> — copy it now, it is only shown once.
              </span>
              <button type="button" className="copy-field small" onClick={() => void copy(created.key, "fresh")}>
                <code>{created.key}</code>
                {copied === "fresh" ? <Check size={14} /> : <Copy size={14} />}
              </button>
            </div>
          )}

          {payload?.is_owner ? (
            <div className="key-create">
              <input
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="label (e.g. my-bot)"
                maxLength={40}
                aria-label="Key label"
              />
              <button type="button" className="pill-btn accent" onClick={() => void create()} disabled={busy}>
                <Plus size={14} /> Create key
              </button>
            </div>
          ) : (
            <p className="muted small">
              Only the bot owner can mint keys. Ask them for one, or run <code>/getapi</code> in a DM.
            </p>
          )}

          <ul className="key-list">
            {keys.map((item) => (
              <li key={item.key} className={item.active === false ? "off" : ""}>
                <div className="key-main">
                  <b>{item.label || "key"}</b>
                  <code>{item.masked ?? item.key}</code>
                </div>
                <div className="key-meta">
                  <span>{item.uses ?? 0} uses</span>
                  <span>{bytes(item.bytes ?? 0)}</span>
                  <span>{ago(item.last_used_at)}</span>
                </div>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label={`Revoke ${item.label || "key"}`}
                  disabled={!payload?.is_owner || item.active === false}
                  onClick={() => void revoke(item)}
                >
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
          {keys.length === 0 && <p className="empty-state">No keys yet — create one to start calling the API.</p>}
        </article>
      </div>

      <article className="panel">
        <div className="panel-head">
          <h3>
            <Code2 size={14} /> Endpoints
          </h3>
          <div className="head-actions">
            <a className="pill-btn ghost" href="/v1/docs" target="_blank" rel="noreferrer">
              <ExternalLink size={13} /> Docs
            </a>
            <a className="pill-btn ghost" href="/v1/openapi.json" target="_blank" rel="noreferrer">
              OpenAPI
            </a>
          </div>
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
              <span className={`lock ${endpoint.keyed ? "" : "open"}`}>{endpoint.keyed ? "key" : "open"}</span>
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
          Keys are stored in MongoDB when <code>MONGO_URL</code> is set, otherwise in a local JSON file. Revoked
          keys return <code>403</code>, missing keys <code>401</code>, over-quota requests <code>429</code>.
        </p>
      </article>
    </section>
  );
}
