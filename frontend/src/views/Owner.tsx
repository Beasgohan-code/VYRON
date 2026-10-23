import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Download,
  Eye,
  EyeOff,
  KeyRound,
  Pause,
  Play,
  RefreshCw,
  RotateCw,
  Server,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../lib/api";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import type { ApiKey, JournalEvent, JournalPayload } from "../lib/types";

type Tab = "logs" | "keys" | "system";

const LEVELS = [
  { key: "all", label: "All" },
  { key: "error", label: "Errors" },
  { key: "warn", label: "Warnings" },
  { key: "info", label: "Info" },
] as const;

const GLYPH: Record<string, string> = { debug: "·", info: "›", ok: "✓", warn: "!", error: "×" };

function clockOf(ts: number): string {
  const date = new Date(ts * 1000);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function Owner() {
  const { state, toast } = useApp();
  const [tab, setTab] = useState<Tab>("logs");

  if (!state?.owner) {
    return (
      <div className="stage">
        <div className="empty">
          <span className="empty-icon">
            <ShieldCheck size={20} />
          </span>
          <b>Owner only</b>
          <p>This console reads the bot's journal and manages API keys.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="stage">
      <header className="screen-head">
        <h1>Owner console</h1>
        <p>Journal, keys and runtime health — all from the same deployment.</p>
      </header>

      <div className="seg">
        <button type="button" className={`seg-btn ${tab === "logs" ? "active" : ""}`} onClick={() => setTab("logs")}>
          <Activity size={14} /> Journal
        </button>
        <button type="button" className={`seg-btn ${tab === "keys" ? "active" : ""}`} onClick={() => setTab("keys")}>
          <KeyRound size={14} /> API keys
        </button>
        <button type="button" className={`seg-btn ${tab === "system" ? "active" : ""}`} onClick={() => setTab("system")}>
          <Server size={14} /> System
        </button>
      </div>

      {tab === "logs" && <LogConsole toast={toast} />}
      {tab === "keys" && <KeyConsole toast={toast} />}
      {tab === "system" && <SystemPanel />}
    </div>
  );
}

/* ── journal ──────────────────────────────────────────────────────────────── */
function LogConsole({ toast }: { toast: (message: string, tone?: "info" | "error" | "success") => void }) {
  const [events, setEvents] = useState<JournalEvent[]>([]);
  const [payload, setPayload] = useState<JournalPayload | null>(null);
  const [level, setLevel] = useState<string>("all");
  const [scope, setScope] = useState<string>("");
  const [live, setLive] = useState(true);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const seq = useRef(0);

  const load = useCallback(
    async (reset = false) => {
      try {
        const data = await api.logs({
          since: reset ? 0 : seq.current,
          level,
          scope: scope || undefined,
          n: 200,
        });
        setPayload(data);
        setError(null);
        setEvents((previous) => {
          const merged = reset ? data.events : [...previous, ...data.events];
          const seen = new Set<number>();
          const unique = merged.filter((event) => (seen.has(event.seq) ? false : (seen.add(event.seq), true)));
          return unique.slice(-400);
        });
        const newest = data.events[data.events.length - 1];
        if (newest) seq.current = Math.max(seq.current, newest.seq);
        if (reset) {
          seq.current = data.events[data.events.length - 1]?.seq ?? 0;
          setSeconds(0);
        }
      } catch (cause) {
        const message = cause instanceof ApiError ? `${cause.message} (${cause.status})` : "could not reach the journal";
        setError(message);
      }
    },
    [level, scope]
  );

  useEffect(() => {
    seq.current = 0;
    setEvents([]);
    void load(true);
  }, [load]);

  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void load(false), 3000);
    const ticker = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(ticker);
    };
  }, [live, load]);

  useEffect(() => {
    const node = list.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [events.length]);

  const scopes = useMemo(() => {
    const set = new Set(events.map((event) => event.scope));
    return [...set].sort().slice(0, 10);
  }, [events]);

  const stats = payload?.stats;
  const counts = stats?.counts ?? {};

  return (
    <>
      <div className="log-toolbar">
        <div className="chips">
          {LEVELS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`chip ${level === item.key ? "active" : ""}`}
              onClick={() => setLevel(item.key)}
            >
              {item.label}
              {item.key === "error" && counts.error ? <i>{counts.error}</i> : null}
              {item.key === "warn" && counts.warn ? <i>{counts.warn}</i> : null}
            </button>
          ))}
        </div>
        <div className="log-actions">
          <button type="button" className="btn btn-ghost sm" onClick={() => void load(false)}>
            <RefreshCw size={13} />
          </button>
          <button
            type="button"
            className={`btn btn-ghost sm ${live ? "on" : ""}`}
            onClick={() => setLive((value) => !value)}
            aria-pressed={live}
          >
            {live ? <Pause size={13} /> : <Play size={13} />}
            {live ? "live" : "paused"}
          </button>
          <button
            type="button"
            className="btn btn-ghost sm"
            onClick={async () => {
              try {
                await api.logsAction("export");
                toast("Journal exported on the server", "success");
              } catch {
                toast("Export failed", "error");
              }
            }}
          >
            <Download size={13} />
          </button>
          <button
            type="button"
            className="btn btn-ghost sm danger"
            onClick={async () => {
              try {
                const result = await api.logsAction("clear");
                toast(`Cleared ${result.cleared ?? 0} events`, "success");
                await load(true);
              } catch {
                toast("Could not clear the journal", "error");
              }
            }}
          >
            <Trash2 size={13} />
          </button>
        </div>
      </div>

      {scopes.length > 0 && (
        <div className="chips scroll">
          <button
            type="button"
            className={`chip ghost ${scope ? "" : "active"}`}
            onClick={() => setScope("")}
          >
            every scope
          </button>
          {scopes.map((name) => (
            <button
              key={name}
              type="button"
              className={`chip ghost ${scope === name ? "active" : ""}`}
              onClick={() => setScope((current) => (current === name ? "" : name))}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      {error && (
        <p className="notice error">
          <AlertTriangle size={14} /> {error}
        </p>
      )}

      <div className="log-panel">
        <header className="log-head">
          <span>
            <span className={`live-dot ${live ? "" : "idle"}`} /> {live ? "streaming" : "paused"}
          </span>
          <span>
            {stats?.buffered ?? 0} buffered · {stats?.seq ?? 0} total · uptime{" "}
            {fmtDuration(stats?.uptime ?? 0)}
          </span>
        </header>
        <div className="log-list" ref={list} role="log" aria-live={live ? "polite" : "off"}>
          {events.length === 0 && !error && (
            <p className="fine center pad">Nothing recorded yet. The journal fills as the bot works.</p>
          )}
          {events.map((event) => (
            <div key={event.seq} className={`log-line level-${event.level}`}>
              <span className="log-time">{clockOf(event.ts)}</span>
              <span className="log-glyph">{GLYPH[event.level] ?? "·"}</span>
              <span className="log-scope">{event.scope}</span>
              <span className="log-msg">{event.message}</span>
              {typeof event.meta.traceback === "string" && (
                <details className="log-trace">
                  <summary>trace</summary>
                  <pre>{event.meta.traceback}</pre>
                </details>
              )}
            </div>
          ))}
        </div>
        <footer className="log-foot">
          <span>{live ? `refreshing · ${seconds % 3 === 0 ? "now" : `${3 - (seconds % 3)}s`}` : "paused"}</span>
          <button
            type="button"
            className="btn btn-ghost sm"
            onClick={() => {
              const text = events
                .map((event) => `${clockOf(event.ts)} ${event.level.toUpperCase()} ${event.scope} ${event.message}`)
                .join("\n");
              void navigator.clipboard?.writeText(text);
              toast("Journal copied", "success");
            }}
          >
            <Copy size={13} /> copy
          </button>
        </footer>
      </div>
    </>
  );
}

/* ── API keys ─────────────────────────────────────────────────────────────── */
function KeyConsole({ toast }: { toast: (message: string, tone?: "info" | "error" | "success") => void }) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [base, setBase] = useState("");
  const [fresh, setFresh] = useState("");
  const [busy, setBusy] = useState(false);
  const [showSecrets, setShowSecrets] = useState(false);
  const [label, setLabel] = useState("web");

  const refresh = useCallback(async () => {
    try {
      const payload = await api.keys();
      setKeys(payload.keys ?? []);
      setBase(payload.base ?? "");
    } catch (cause) {
      toast(cause instanceof Error ? cause.message : "Could not load keys", "error");
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <>
      <div className="key-create">
        <input
          className="text-input"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="key label"
          aria-label="Key label"
        />
        <button
          type="button"
          className="btn btn-primary sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const payload = await api.createKey(label.trim() || "web");
              setKeys(payload.keys ?? []);
              const minted = payload.keys?.find((item) => item.key)?.key ?? "";
              setFresh(minted);
              setShowSecrets(true);
              toast("Key created — copy it now", "success");
            } catch (cause) {
              toast(cause instanceof Error ? cause.message : "Could not create a key", "error");
            } finally {
              setBusy(false);
            }
          }}
        >
          <KeyRound size={14} /> Create key
        </button>
      </div>

      {fresh && (
        <div className="notice ok">
          <CheckCircle2 size={14} />
          <code>{fresh}</code>
          <button
            type="button"
            className="btn btn-ghost sm"
            onClick={() => void navigator.clipboard?.writeText(fresh)}
          >
            <Copy size={13} /> copy
          </button>
        </div>
      )}

      <p className="fine">
        Base URL <code>{base || window.location.origin}</code> · keys are hashed at rest, shown once. Scopes:{" "}
        <code>read · search · download · admin</code>
      </p>

      <ul className="rows">
        {keys.length === 0 && <li className="fine">No keys yet.</li>}
        {keys.map((key) => (
          <li key={key.id ?? key.masked} className="key-row">
            <span className="key-glyph">
              <KeyRound size={15} />
            </span>
            <span className="tr-main">
              <b className="tr-title">{key.label || "key"}</b>
              <span className="tr-sub">
                <code>{showSecrets && key.key ? key.key : key.masked || key.preview}</code> ·{" "}
                {key.scopes?.join(", ") || "read"} · {key.uses ?? 0} uses
                {key.last_used_at ? ` · ${new Date((key.last_used_at ?? 0) * 1000).toLocaleDateString()}` : ""}
              </span>
            </span>
            <span className={`tag ${key.active ? "on" : ""}`}>{key.active ? "active" : "revoked"}</span>
            <button
              type="button"
              className="btn-icon"
              aria-label={`Rotate ${key.label || "key"}`}
              onClick={async () => {
                try {
                  const payload = await api.rotateKey(String(key.id));
                  setKeys(payload.keys ?? []);
                  const minted = payload.keys?.find((item) => item.key)?.key ?? "";
                  if (minted) {
                    setFresh(minted);
                    setShowSecrets(true);
                  }
                  toast("Rotated — new secret shown", "success");
                } catch {
                  toast("Rotate failed", "error");
                }
              }}
            >
              <RotateCw size={14} />
            </button>
            <button
              type="button"
              className="btn-icon danger"
              aria-label={`Revoke ${key.label || "key"}`}
              onClick={async () => {
                try {
                  const payload = await api.revokeKey(String(key.id));
                  setKeys(payload.keys ?? []);
                  toast("Key revoked", "success");
                } catch {
                  toast("Revoke failed", "error");
                }
              }}
            >
              <Trash2 size={14} />
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="btn btn-ghost sm" onClick={() => setShowSecrets((value) => !value)}>
        {showSecrets ? <EyeOff size={13} /> : <Eye size={13} />}
        {showSecrets ? "hide secrets" : "reveal this session's secrets"}
      </button>
    </>
  );
}

/* ── system ───────────────────────────────────────────────────────────────── */
function SystemPanel() {
  const [data, setData] = useState<JournalPayload | null>(null);

  useEffect(() => {
    void api
      .logs({ n: 1 })
      .then(setData)
      .catch(() => undefined);
  }, []);

  const system = data?.system;
  const stats = data?.stats;

  const tiles = [
    { label: "uptime", value: fmtDuration(system?.uptime ?? 0) },
    { label: "version", value: system?.version ?? "—" },
    { label: "storage", value: system?.storage ?? "—" },
    { label: "streaming", value: system?.streaming ? "ready" : "file mode" },
    { label: "handlers", value: String(system?.handlers ?? 0) },
    { label: "active chats", value: String(system?.chats ?? 0) },
    { label: "playing now", value: String(system?.playing ?? 0) },
    { label: "journal errors", value: String(stats?.errors ?? 0) },
  ];

  return (
    <>
      <div className="stat-grid">
        {tiles.map((tile) => (
          <div key={tile.label} className="stat-card">
            <b>{tile.value}</b>
            <span>{tile.label}</span>
          </div>
        ))}
      </div>

      <div className="list-card">
        <div className="pref">
          <span>Watchdog</span>
          <code>
            {system?.watchdog?.checks ?? 0} checks · {system?.watchdog?.reconnects ?? 0} reconnects
          </code>
        </div>
        <div className="pref">
          <span>Keep-alive</span>
          <code>
            {system?.keepalive?.enabled ? "on" : "off"} · {system?.keepalive?.runs ?? 0} pings · last{" "}
            {system?.keepalive?.last_status ?? "—"}
          </code>
        </div>
        <div className="pref">
          <span>Resolver / downloader</span>
          <code>
            {system?.resolver ? "yt-dlp" : "missing"} / {system?.downloader ? "cache on" : "off"}
          </code>
        </div>
        <div className="pref">
          <span>Journal file</span>
          <code>{stats?.file || "memory only"}</code>
        </div>
      </div>

      {system?.watchdog?.last_error ? (
        <p className="notice error">
          <AlertTriangle size={14} /> {system.watchdog.last_error}
        </p>
      ) : (
        <p className="notice ok">
          <CheckCircle2 size={14} /> No watchdog errors recorded.
        </p>
      )}
    </>
  );
}
