import {
  Download,
  Heart,
  ListPlus,
  Pause,
  Play,
  Repeat,
  Send,
  Shuffle,
  SkipForward,
  Users,
  Volume2,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "./Cover";
import { Panel } from "./Panel";

export function NowPlayingRail() {
  const { state, act, dragging, setDragging, openModal, setView, toast } = useApp();
  const now = state?.now ?? null;
  const settings = state?.settings;
  const waveRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = waveRef.current;
    if (!host || host.childElementCount) return;
    for (let index = 0; index < 26; index += 1) {
      const bar = document.createElement("i");
      bar.style.height = `${25 + Math.random() * 75}%`;
      bar.style.animationDelay = `${Math.random() * 0.9}s`;
      host.appendChild(bar);
    }
  }, []);

  /* the API is polled, so tick the clock locally between fetches */
  const [drift, setDrift] = useState(0);
  useEffect(() => {
    setDrift(0);
  }, [now?.elapsed, now?.title]);

  const total = now?.duration ?? 0;
  const live = Boolean(now && !now.paused);
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => setDrift((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [live, now?.title]);

  const raw = (now?.elapsed ?? 0) + drift;
  const elapsed = total ? Math.min(total, raw) : raw;
  const percent = total ? Math.min(100, (elapsed / total) * 100) : 0;

  return (
    <>
      <article className="panel np-card">
        <div className="np-head">
          <span className="tag">Now playing</span>
          <span className="np-flags">
            {state && state.streaming === false && (
              <span className="tag ghost" title="No assistant session — tracks arrive as files">
                file mode
              </span>
            )}
            <span className={`np-state ${now && !now.paused ? "on" : ""}`}>
              <i />
              {now ? (now.paused ? "paused" : "live") : "idle"}
            </span>
          </span>
        </div>

        <div className="np-art">
          {now ? <Cover track={now} /> : <div className="cover-fallback xl" />}
          <div className={`np-wave ${now && !now.paused ? "" : "paused"}`} ref={waveRef} aria-hidden="true" />
        </div>

        <div className="np-meta">
          <b>{now?.title ?? "Nothing playing"}</b>
          <span>{now?.uploader ?? "Send /play in the chat to start"}</span>
        </div>

        <div className="np-seek">
          <input
            type="range"
            min={0}
            max={1000}
            value={Math.round((percent / 100) * 1000)}
            disabled={!total}
            style={{ ["--p" as string]: `${percent}%` }}
            aria-label="Seek"
            onPointerDown={() => setDragging(true)}
            onChange={(event) => {
              const next = Number(event.target.value) / 10;
              event.currentTarget.style.setProperty("--p", `${next}%`);
            }}
            onPointerUp={(event) => {
              setDragging(false);
              const next = Number(event.currentTarget.value) / 1000;
              void act("seek", Math.round(next * total));
            }}
            onKeyUp={() => setDragging(false)}
          />
          <div className="np-times">
            <span>{fmtDuration(dragging ? percent && (percent / 100) * total : elapsed)}</span>
            <span>{total ? fmtDuration(total) : "live"}</span>
          </div>
        </div>

        <div className="np-transport">
          <button
            type="button"
            className="icon-btn"
            aria-label="Shuffle"
            onClick={async () => {
              const payload = await act<{ shuffled?: number }>("shuffle");
              if (payload) toast(`Shuffled ${payload.shuffled ?? 0} tracks`, "success");
            }}
          >
            <Shuffle size={17} />
          </button>
          <button type="button" className="icon-btn" aria-label="Skip" onClick={() => void act("skip", 1)}>
            <SkipForward size={18} />
          </button>
          <button
            type="button"
            className="round-play lg"
            aria-label={now && !now.paused ? "Pause" : "Play"}
            onClick={() => void act("toggle")}
          >
            {now && !now.paused ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
          </button>
          <button
            type="button"
            className={`icon-btn ${settings?.loop && settings.loop !== "off" ? "on" : ""}`}
            aria-label="Loop"
            onClick={async () => {
              const order = ["off", "one", "all"] as const;
              const current = settings?.loop ?? "off";
              const next = order[(order.indexOf(current) + 1) % order.length];
              const payload = await act<{ loop?: string }>("loop", next);
              if (payload) toast(`Loop: ${payload.loop ?? next}`);
            }}
          >
            <Repeat size={17} />
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label="Like"
            onClick={async () => {
              const payload = await act<{ saved?: boolean }>("favorite");
              if (payload) toast(payload.saved ? "Saved to liked songs" : "Already liked", "success");
            }}
          >
            <Heart size={17} />
          </button>
        </div>

        <div className="np-foot">
          <span className="source-pill">{now?.source ?? "youtube"}</span>
          <span>{settings ? `${settings.volume}% volume` : "—"}</span>
          <span>{state?.streaming ? "voice chat" : "file mode"}</span>
        </div>
      </article>

      <Panel title="Quick actions" className="quick">
        <button type="button" className="quick-row" onClick={() => openModal({ type: "download" })}>
          <span className="qi">
            <Download size={15} />
          </span>
          <span>
            <b>Download music</b>
            <small>MP3 or MP4 to the chat</small>
          </span>
        </button>
        <button type="button" className="quick-row" onClick={() => openModal({ type: "new-playlist" })}>
          <span className="qi">
            <ListPlus size={15} />
          </span>
          <span>
            <b>Create playlist</b>
            <small>Save what you love</small>
          </span>
        </button>
        <button type="button" className="quick-row" onClick={() => setView("rooms")}>
          <span className="qi">
            <Users size={15} />
          </span>
          <span>
            <b>Join listen together</b>
            <small>Live rooms in voice chats</small>
          </span>
        </button>
        <button
          type="button"
          className="quick-row"
          onClick={() => {
            const tg = window.Telegram?.WebApp;
            if (tg?.openTelegramLink) tg.openTelegramLink("https://t.me/VyronMusicBot");
            else window.open("https://t.me/VyronMusicBot", "_blank", "noopener");
          }}
        >
          <span className="qi">
            <Send size={15} />
          </span>
          <span>
            <b>Telegram bot</b>
            <small>@VyronMusicBot</small>
          </span>
        </button>
      </Panel>

      <Panel title="Output" className="rail-volume">
        <div className="rail-volume-row">
          <Volume2 size={15} />
          <input
            type="range"
            min={0}
            max={200}
            defaultValue={settings?.volume ?? 100}
            style={{ ["--p" as string]: `${((settings?.volume ?? 100) / 200) * 100}%` }}
            aria-label="Volume"
            onChange={(event) => {
              const value = Number(event.target.value);
              event.currentTarget.style.setProperty("--p", `${(value / 200) * 100}%`);
            }}
            onPointerUp={(event) => void act("volume", Number(event.currentTarget.value))}
          />
          <b>{settings?.volume ?? 100}</b>
        </div>
        <div className="rail-volume-row muted small">
          <span>Status</span>
          <span>{now ? (now.paused ? "paused" : "streaming") : "idle"}</span>
        </div>
      </Panel>
    </>
  );
}
