import {
  Code2,
  Command,
  Disc3,
  Headphones,
  Home,
  Library,
  ListMusic,
  Radio,
  Search,
  Settings,
  Users,
} from "lucide-react";
import { useApp } from "../lib/store";
import type { View } from "../lib/types";
import { compact, initials } from "../lib/format";

const NAV: { view: View; label: string; icon: typeof Home; badge?: string }[] = [
  { view: "home", label: "Home", icon: Home },
  { view: "search", label: "Search", icon: Search },
  { view: "library", label: "Library", icon: Library },
  { view: "queue", label: "Queue", icon: ListMusic },
  { view: "playlists", label: "Playlists", icon: Disc3 },
  { view: "rooms", label: "Rooms", icon: Users, badge: "live" },
  { view: "api", label: "Music API", icon: Code2 },
  { view: "profile", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const { view, setView, state, rooms } = useApp();
  const user = state?.user ?? {};
  const liveRooms = rooms.length;
  const online = state?.stats?.chats ?? 0;

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <Headphones size={18} />
        </span>
        <div>
          <b>VYRON</b>
          <span>music beyond limits</span>
        </div>
      </div>

      <nav className="nav">
        {NAV.map(({ view: item, label, icon: Icon, badge }) => (
          <button
            key={item}
            type="button"
            className={`nav-item ${view === item ? "active" : ""}`}
            onClick={() => setView(item)}
            aria-current={view === item ? "page" : undefined}
          >
            <Icon size={17} />
            <span>{label}</span>
            {badge === "live" && liveRooms > 0 && <em className="dot-live" title={`${liveRooms} live`} />}
          </button>
        ))}
      </nav>

      <button
        type="button"
        className="palette-trigger"
        onClick={() => window.dispatchEvent(new CustomEvent("vyron:palette"))}
        aria-label="Open command palette"
      >
        <Command size={14} />
        <span>Quick actions</span>
        <kbd>⌘K</kbd>
      </button>

      <div className="side-card">
        <div className="side-card-head">
          <Radio size={15} />
          <b>Listen Together</b>
        </div>
        <p>{liveRooms ? `${liveRooms} room${liveRooms === 1 ? "" : "s"} streaming right now.` : "No live rooms yet."}</p>
        <button type="button" className="pill-btn ghost wide" onClick={() => setView("rooms")}>
          Open rooms
        </button>
      </div>

      <a
        className="side-user"
        href="https://t.me/VyronMusicBot"
        target="_blank"
        rel="noreferrer noopener"
        onClick={(event) => {
          const tg = window.Telegram?.WebApp;
          if (tg?.openTelegramLink) {
            event.preventDefault();
            tg.openTelegramLink("https://t.me/VyronMusicBot");
          }
        }}
      >
        <span className="avatar">{initials(user.name)}</span>
        <span className="meta">
          <b>{user.name || "Listener"}</b>
          <span>
            @{state?.bot || "VyronMusicBot"} · Online
            {online ? ` · ${compact(online)} chats` : ""}
          </span>
        </span>
        <span className="online-dot" />
      </a>
    </aside>
  );
}
