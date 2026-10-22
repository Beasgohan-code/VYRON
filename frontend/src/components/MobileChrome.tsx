import { Home, Library, ListMusic, Pause, Play, Search, SkipForward, UserRound } from "lucide-react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import type { View } from "../lib/types";
import { Cover } from "./Cover";

const TABS: { view: View; label: string; icon: typeof Home }[] = [
  { view: "home", label: "Home", icon: Home },
  { view: "search", label: "Search", icon: Search },
  { view: "queue", label: "Queue", icon: ListMusic },
  { view: "library", label: "Library", icon: Library },
  { view: "profile", label: "Profile", icon: UserRound },
];

export function MiniPlayer() {
  const { state, act, setView } = useApp();
  const now = state?.now;
  if (!now) return null;

  return (
    <div className="mini-player" role="region" aria-label="Now playing">
      <button type="button" className="mini-main" onClick={() => setView("queue")}>
        <Cover track={now} className="mini-cover" />
        <span className="mini-text">
          <b>{now.title}</b>
          <span>
            {now.uploader || "unknown"}
            {now.duration ? ` · ${fmtDuration(now.elapsed)}` : ""}
          </span>
        </span>
      </button>
      <button
        type="button"
        className="mini-play"
        aria-label={now.paused ? "Play" : "Pause"}
        onClick={() => void act("toggle")}
      >
        {now.paused ? <Play size={16} fill="currentColor" /> : <Pause size={16} fill="currentColor" />}
      </button>
      <button type="button" className="mini-skip" aria-label="Skip" onClick={() => void act("skip", 1)}>
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
