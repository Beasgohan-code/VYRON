import { Check, Gauge, Headphones, LogOut, Maximize2, Moon, Palette, Send, SunMedium, Wand2 } from "lucide-react";
import { useApp } from "../lib/store";
import type { AccentName, ThemeName } from "../lib/store";
import { initials } from "../lib/format";

const THEMES: { key: ThemeName; label: string; hint: string }[] = [
  { key: "beat", label: "Beat", hint: "VYRON violet edition" },
  { key: "telegram", label: "Telegram", hint: "Follows your Telegram theme" },
  { key: "system", label: "System", hint: "Matches device light/dark" },
];

const ACCENTS: AccentName[] = ["violet", "blue", "cyan", "green", "pink", "amber"];

const EFFECTS: { key: string; label: string }[] = [
  { key: "bass", label: "Bass" },
  { key: "treble", label: "Treble" },
  { key: "loud", label: "Loudness" },
  { key: "nightcore", label: "Nightcore" },
  { key: "vaporwave", label: "Vaporwave" },
  { key: "8d", label: "8D" },
  { key: "echo", label: "Echo" },
  { key: "karaoke", label: "Karaoke" },
  { key: "mono", label: "Mono" },
];

export function ProfileView() {
  const {
    state,
    theme,
    setTheme,
    accent,
    setAccent,
    normalise,
    setNormalise,
    act,
    toast,
    openModal,
    rooms,
  } = useApp();

  const user = state?.user ?? {};
  const settings = state?.settings;
  const effects = settings?.effects ?? [];

  const toggleEffect = async (key: string) => {
    const next = effects.includes(key) ? effects.filter((item) => item !== key) : [...effects, key].slice(0, 3);
    const payload = await act<{ labels?: string }>("effects", next);
    if (payload) toast(`Effects: ${payload.labels || "off"}`, "success");
  };

  return (
    <section className="view active">
      <div className="view-head">
        <h1>Profile &amp; settings</h1>
        <p className="muted">Account, appearance and playback</p>
      </div>

      <div className="profile-card">
        <div className="avatar xl">{initials(user.name)}</div>
        <div className="profile-id">
          <strong>{user.name || "Listener"}</strong>
          <span className="muted">{user.username ? `@${user.username}` : `id ${user.id ?? "—"}`}</span>
        </div>
        <div className="profile-tags">
          <span className="pill-tiny">{state?.chat?.title ?? "private chat"}</span>
          <span className="pill-tiny">{state?.streaming ? "voice chat ready" : "file mode"}</span>
          <span className="pill-tiny">{rooms.length} rooms</span>
        </div>
        <button
          type="button"
          className="pill-btn"
          onClick={() => {
            const tg = window.Telegram?.WebApp;
            if (tg?.requestFullscreen) tg.requestFullscreen();
            else if (!document.fullscreenElement) void document.documentElement.requestFullscreen?.();
            else void document.exitFullscreen?.();
          }}
        >
          <Maximize2 size={14} /> Fullscreen
        </button>
      </div>

      <div className="settings-grid">
        <article className="panel">
          <div className="panel-head">
            <h3>
              <Palette size={14} /> Appearance
            </h3>
          </div>
          <div className="theme-row">
            {THEMES.map((item) => (
              <button
                key={item.key}
                type="button"
                className={`theme-card ${theme === item.key ? "active" : ""} theme-${item.key}`}
                onClick={() => setTheme(item.key)}
              >
                <span className="theme-preview" />
                <b>{item.label}</b>
                <small>{item.hint}</small>
                {theme === item.key && (
                  <span className="theme-check">
                    <Check size={12} />
                  </span>
                )}
              </button>
            ))}
          </div>
          <span className="field-label">Accent</span>
          <div className="accent-row">
            {ACCENTS.map((item) => (
              <button
                key={item}
                type="button"
                className={`accent-dot accent-${item} ${accent === item ? "active" : ""}`}
                aria-label={item}
                onClick={() => setAccent(item)}
              />
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-head">
            <h3>
              <Headphones size={14} /> Playback
            </h3>
          </div>
          <label className="switch-row">
            <span>Autoplay related tracks</span>
            <input
              type="checkbox"
              className="switch"
              checked={Boolean(settings?.autoplay)}
              onChange={() => void act("autoplay")}
            />
          </label>
          <label className="switch-row">
            <span>24/7 mode (stay in chat)</span>
            <input
              type="checkbox"
              className="switch"
              checked={Boolean(settings?.always_on)}
              onChange={() => void act("always")}
            />
          </label>
          <label className="switch-row">
            <span>Normalise volume</span>
            <input type="checkbox" className="switch" checked={normalise} onChange={(event) => setNormalise(event.target.checked)} />
          </label>
          <label className="select-row">
            <span>Loop</span>
            <select
              value={settings?.loop ?? "off"}
              onChange={async (event) => {
                const payload = await act<{ loop?: string }>("loop", event.target.value);
                if (payload) toast(`Loop: ${payload.loop ?? event.target.value}`);
              }}
            >
              <option value="off">Off</option>
              <option value="one">Track</option>
              <option value="all">Queue</option>
            </select>
          </label>
          <label className="select-row">
            <span>Volume</span>
            <input
              type="range"
              min={0}
              max={200}
              defaultValue={settings?.volume ?? 100}
              style={{ ["--p" as string]: `${((settings?.volume ?? 100) / 200) * 100}%` }}
              onChange={(event) =>
                event.currentTarget.style.setProperty("--p", `${(Number(event.target.value) / 200) * 100}%`)
              }
              onPointerUp={(event) => void act("volume", Number(event.currentTarget.value))}
            />
          </label>
        </article>
      </div>

      <article className="panel">
        <div className="panel-head">
          <h3>
            <Wand2 size={14} /> Effects
          </h3>
          <span className="muted small">{effects.length}/3 active · applied from the next track</span>
        </div>
        <div className="chips-row">
          {EFFECTS.map((effect) => (
            <button
              key={effect.key}
              type="button"
              className={`chip fx ${effects.includes(effect.key) ? "active" : ""}`}
              onClick={() => void toggleEffect(effect.key)}
            >
              {effect.label}
            </button>
          ))}
        </div>
      </article>

      <div className="settings-grid">
        <article className="panel">
          <div className="panel-head">
            <h3>
              <Send size={14} /> Telegram integration
            </h3>
          </div>
          <ul className="kv-list">
            <li>
              <span>Bot</span>
              <b>@{state?.bot ?? "VyronMusicBot"}</b>
            </li>
            <li>
              <span>Streaming</span>
              <b>{state?.streaming ? "connected" : "file mode"}</b>
            </li>
            <li>
              <span>Chat</span>
              <b>{state?.chat?.title ?? "private"}</b>
            </li>
            <li>
              <span>Version</span>
              <b>{state?.version ?? "—"}</b>
            </li>
          </ul>
        </article>

        <article className="panel">
          <div className="panel-head">
            <h3>
              <Gauge size={14} /> Account
            </h3>
          </div>
          <p className="muted small">
            Everything here is stored in your Telegram chat — no cookies, no trackers. The Mini App talks to the same
            player the bot uses, so chat and app always agree.
          </p>
          <div className="head-actions">
            <button type="button" className="pill-btn ghost" onClick={() => openModal({ type: "download" })}>
              <SunMedium size={14} /> Download a track
            </button>
            <button
              type="button"
              className="pill-btn danger"
              onClick={() => {
                localStorage.removeItem("vyron:recent");
                localStorage.removeItem("vyron:theme");
                localStorage.removeItem("vyron:accent");
                toast("Local preferences cleared");
              }}
            >
              <LogOut size={14} /> Reset local data
            </button>
          </div>
          <div className="footer-note">
            <Moon size={13} /> VYRON — music beyond limits
          </div>
        </article>
      </div>
    </section>
  );
}
