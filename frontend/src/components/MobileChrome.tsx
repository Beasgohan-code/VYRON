import { Home, Library, ListMusic, Pause, Play, Search, SkipForward, UserRound } from "lucide-react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import type { View } from "../lib/types";
import { Cover } from "./Cover";
import { Equalizer } from "./Equalizer";

const TABS: { view: View; label: string; icon: typeof Home }[] = [
  { view: "home", label: "Home", icon: Home },
  { view: "search", label: "Search", icon: Search },
  { view: "queue", label: "Queue", icon: ListMusic },
  { view: "library", label: "Library", icon: Library },
  { view: "profile", label: "Profile", icon: UserRound },
];

export function MiniPlayer() {
  const { state, audio, setView } = useApp();
  const local = audio.track;
  const remote = state?.now;
  const now = local ?? remote;
  if (!now) return null;

  const isLocal = Boolean(local);
  const playing = isLocal ? audio.playing : !remote?.paused;
  const elapsed = isLocal ? audio.position : (remote?.elapsed ?? 0);

  return (
    <div className="mini-player" role="region" aria-label="Now playing">
      <button
        type="button"
        className="mini-main"
        onClick={() => (isLocal ? audio.setExpanded(true) : setView("queue"))}
      >
        <Cover track={now} className="mini-cover" />
        <span className="mini-text">
          <b>{now.title}</b>
          <span>
            {playing ? <Equalizer playing bars={3} /> : null}
            {now.uploader || "unknown"}
            {now.duration ? ` · ${fmtDuration(elapsed)}` : ""}
            {isLocal ? " · in app" : " · in call"}
          </span>
        </span>
        <span className="mini-progress" aria-hidden="true">
          <i style={{ width: `${now.duration ? Math.min(100, (elapsed / now.duration) * 100) : 0}%` }} />
        </span>
      </button>
      <button
        type="button"
        className="mini-play"
        aria-label={playing ? "Pause" : "Play"}
        onClick={() => (isLocal ? audio.toggle() : setView("queue"))}
      >
        {playing ? <Pause size={16} fill="currentColor" /> : <Play size={16} fill="currentColor" />}
      </button>
      <button
        type="button"
        className="mini-skip"
        aria-label="Next"
        onClick={() => (isLocal ? audio.next() : setView("queue"))}
      >
        <SkipForward size={16} />
      </button>
    </div>
  );
}

export function MobileTabBar() {
  const { view, setView } = useApp();

  return (
    <nav className="tabbar" aria-label="Primary">
      {TABS.map(({ view: item, label, icon: Icon }) => (
        <button
          key={item}
          type="button"
          className={`tab-item ${view === item ? "active" : ""}`}
          onClick={() => setView(item)}
          aria-current={view === item ? "page" : undefined}
        >
          <span className="tab-icon">
            <Icon size={18} />
          </span>
          <span className="tab-label">{label}</span>
        </button>
      ))}
    </nav>
  );
}
