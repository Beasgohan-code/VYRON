import {
  Crown,
  Download,
  Gauge,
  HardDrive,
  History,
  Link2,
  Moon,
  Palette,
  ShieldCheck,
  Sparkles,
  Sun,
  X,
  Zap,
} from "lucide-react";
import { useEffect, useState } from "react";
import { clearOffline, keptCount } from "../lib/offline";
import { useApp } from "../lib/store";
import { fmtDuration } from "../lib/format";
import type { AccentName, ThemeName } from "../lib/store";
import { Avatar } from "../components/Avatar";
import { Count } from "../components/Count";
import { useViewReveal } from "../lib/anim";

const THEMES: { key: ThemeName; label: string; icon: typeof Sun }[] = [
  { key: "beat", label: "Beat", icon: Moon },
  { key: "telegram", label: "Telegram", icon: Sun },
  { key: "system", label: "System", icon: Sparkles },
];

const ACCENTS: AccentName[] = ["violet", "blue", "cyan", "green", "pink", "amber"];

export function You() {
  const [kept, setKept] = useState(0);
  useEffect(() => {
    let alive = true;
    void keptCount().then((value) => {
      if (alive) setKept(value);
    });
    return () => {
      alive = false;
    };
  }, []);

  const {
    state,
    setView,
    theme,
    setTheme,
    accent,
    setAccent,
    normalise,
    setNormalise,
    openModal,
    playlists,
    audio,
    toast,
  } = useApp();
  const stage = useViewReveal<HTMLDivElement>("you", ".stage-block");
  const user = state?.user;
  const isOwner = Boolean(state?.owner);

  return (
    <div className="stage" ref={stage}>
      <section className="profile-card stage-block">
        <div className="profile-art">
          <Avatar
            name={user?.name}
            userId={user?.id}
            photo={user?.photo}
            size={96}
            shape="squircle"
            ring
            status={state?.streaming ? "on" : "off"}
          />
        </div>
        <div className="profile-main">
          <span className="eyebrow">
            <Crown size={13} /> {isOwner ? "owner" : user?.access ?? "listener"}
          </span>
          <h1>{user?.name || "Listener"}</h1>
          <p>{user?.username ? `@${user.username}` : state?.chat?.title || "listening on Telegram"}</p>
          <div className="profile-tags">
            {state?.chat?.is_group && <span className="tag">{state.chat.title}</span>}
            <span className="tag">{state?.streaming ? "voice chat ready" : "voice engine offline"}</span>
            {state?.version && <span className="tag">v{state.version}</span>}
          </div>
        </div>
      </section>

      <section className="stage-block">
        <div className="stat-grid">
          <div className="stat-card">
            <b>
              <Count value={state?.favorites?.length ?? 0} />
            </b>
            <span>liked</span>
          </div>
          <div className="stat-card">
            <b>
              <Count value={state?.history?.length ?? 0} />
            </b>
            <span>played</span>
          </div>
          <div className="stat-card">
            <b>
              <Count value={playlists.length} />
            </b>
            <span>playlists</span>
          </div>
          <div className="stat-card">
            <b>{fmtDuration(audio.queue.reduce((sum, track) => sum + (track.duration ?? 0), 0))}</b>
            <span>queued</span>
          </div>
        </div>
      </section>

      <section className="stage-block">
        <header className="section-head">
          <h2>
            <Palette size={15} /> Appearance
          </h2>
        </header>
        <div className="list-card">
          <div className="pref">
            <span>Theme</span>
            <div className="seg sm">
              {THEMES.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.key}
                    type="button"
                    className={`seg-btn ${theme === item.key ? "active" : ""}`}
                    onClick={() => setTheme(item.key)}
                  >
                    <Icon size={13} /> {item.label}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="pref">
            <span>Accent</span>
            <div className="accents">
              {ACCENTS.map((name) => (
                <button
                  key={name}
                  type="button"
                  className={`accent-dot accent-${name} ${accent === name ? "active" : ""}`}
                  aria-label={`${name} accent`}
                  onClick={() => setAccent(name)}
                />
              ))}
            </div>
          </div>
          <div className="pref">
            <span>
              Normalise volume
              <i className="fine">evens out loud and quiet tracks</i>
            </span>
            <button
              type="button"
              className={`switch ${normalise ? "on" : ""}`}
              role="switch"
              aria-checked={normalise}
              aria-label="Normalise volume"
              onClick={() => setNormalise(!normalise)}
            >
              <span />
            </button>
          </div>
        </div>
      </section>

      <section className="stage-block">
        <header className="section-head">
          <h2>
            <Gauge size={15} /> Playback
          </h2>
          <span className="fine">this device</span>
        </header>
        <div className="list-card">
          <div className="pref">
            <span>
              Speed
              <i className="fine">podcasts and long mixes</i>
            </span>
            <div className="chips tight">
              {[0.75, 1, 1.25, 1.5, 2].map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`chip tiny ${Math.abs(audio.rate - value) < 0.01 ? "active" : ""}`}
                  onClick={() => audio.setRate(value)}
                  aria-pressed={Math.abs(audio.rate - value) < 0.01}
                >
                  {value}×
                </button>
              ))}
            </div>
          </div>
          <div className="pref">
            <span>
              Blend
              <i className="fine">
                {audio.crossfade ? `${audio.crossfade}s overlap between tracks` : "gapless — one track into the next"}
              </i>
            </span>
            <div className="chips tight">
              {[0, 3, 6, 12].map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`chip tiny ${audio.crossfade === value ? "active" : ""}`}
                  onClick={() => audio.setCrossfade(value)}
                  aria-pressed={audio.crossfade === value}
                >
                  {value === 0 ? "off" : `${value}s`}
                </button>
              ))}
            </div>
          </div>
          <div className="pref">
            <span>
              <HardDrive size={14} /> Kept offline
              <i className="fine">
                {kept ? `${kept} ${kept === 1 ? "track" : "tracks"} on this device` : "keep songs from the track menu"}
              </i>
            </span>
            {kept ? (
              <button
                type="button"
                className="btn btn-ghost sm"
                onClick={async () => {
                  await clearOffline();
                  setKept(0);
                  toast("Offline songs cleared", "success");
                }}
              >
                Clear
              </button>
            ) : (
              <span className="fine">—</span>
            )}
          </div>
          <div className="pref">
            <span>
              <History size={14} /> Saved session
              <i className="fine">
                {audio.saved
                  ? `${audio.saved.queue[audio.saved.index]?.title ?? "track"} · restores paused`
                  : "nothing saved on this device"}
              </i>
            </span>
            {audio.saved ? (
              <div className="row gap">
                <button type="button" className="btn btn-ghost sm" onClick={audio.resumeSession}>
                  Resume
                </button>
                <button type="button" className="btn btn-ghost sm" onClick={audio.dismissSession}>
                  <X size={13} /> Forget
                </button>
              </div>
            ) : (
              <span className="fine">—</span>
            )}
          </div>
        </div>
      </section>

      <section className="stage-block">
        <header className="section-head">
          <h2>
            <Zap size={15} /> Tools
          </h2>
        </header>
        <div className="action-list">
          <button type="button" onClick={() => openModal({ type: "download" })}>
            <Download size={17} />
            <span>
              <b>Download music</b>
              <i>MP3 320 or MP4 720p straight to this chat</i>
            </span>
          </button>
          <button type="button" onClick={() => setView("library")}>
            <Sparkles size={17} />
            <span>
              <b>Your library</b>
              <i>liked, history and playlists</i>
            </span>
          </button>
          {isOwner && (
            <>
              <button type="button" onClick={() => setView("api")}>
                <ShieldCheck size={17} />
                <span>
                  <b>Owner console</b>
                  <i>live journal, API keys, system health</i>
                </span>
              </button>
              <button
                type="button"
                onClick={() => {
                  const base = window.location.origin;
                  void navigator.clipboard?.writeText(`${base}/app/`);
                }}
              >
                <Link2 size={17} />
                <span>
                  <b>Copy app link</b>
                  <i>share the Mini App URL</i>
                </span>
              </button>
            </>
          )}
        </div>
      </section>

      <p className="fine center">
        VYRON v{state?.version ?? "1.2.0"} · voice-chat streaming · in-app player · built on Telegram Bot API
      </p>
    </div>
  );
}
