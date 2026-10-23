import { AlertTriangle, Compass, Download, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { Dock } from "./components/Dock";
import { Rail, Tabs } from "./components/Nav";
import { Sheet } from "./components/Sheet";
import { useApp } from "./lib/store";
import { Home } from "./views/Home";
import { Library } from "./views/Library";
import { Owner } from "./views/Owner";
import { Player } from "./views/Player";
import { Rooms } from "./views/Rooms";
import { Search } from "./views/Search";
import { You } from "./views/You";

const TITLES: Record<string, string> = {
  home: "Home",
  search: "Search",
  library: "Library",
  rooms: "Rooms",
  profile: "You",
  api: "Owner",
  queue: "Queue",
  playlists: "Playlists",
};

export default function App() {
  const { view, setView, access, toastMessage, toastTone, audio, state, refreshState } = useApp();
  const [retrying, setRetrying] = useState(false);

  /* keyboard: "/" jumps to search, space toggles playback */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);

      if (event.key === "/" && !typing) {
        event.preventDefault();
        setView("search");
        window.setTimeout(() => window.dispatchEvent(new Event("vyron:focus-search")), 60);
      }
      if (event.code === "Space" && !typing && audio.track) {
        event.preventDefault();
        audio.toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [audio, setView]);

  const page = (() => {
    switch (view) {
      case "search":
        return <Search />;
      case "library":
      case "playlists":
        return <Library />;
      case "rooms":
        return <Rooms />;
      case "profile":
        return <You />;
      case "api":
        return <Owner />;
      default:
        return <Home />;
    }
  })();

  return (
    <div className={`app ${audio.track ? "with-dock" : ""}`}>
      <Rail />

      <main className="main">
        <header className="topbar">
          <div className="topbar-title">
            <span className="mobile-brand">VYRON</span>
            <h2>{TITLES[view] ?? "VYRON"}</h2>
          </div>
          <div className="topbar-actions">
            <button
              type="button"
              className="btn-icon"
              aria-label="Search"
              onClick={() => {
                setView("search");
                window.setTimeout(() => window.dispatchEvent(new Event("vyron:focus-search")), 60);
              }}
            >
              <Compass size={18} />
            </button>
            <span className={`status-dot ${state?.streaming ? "on" : ""}`} title={state?.streaming ? "voice chat ready" : "file mode"} />
          </div>
        </header>

        {(access === "locked" || access === "offline") && (
          <div className={`notice ${access === "offline" ? "error" : "warn"}`}>
            {access === "offline" ? <WifiOff size={15} /> : <AlertTriangle size={15} />}
            <span>
              {access === "offline"
                ? "Cannot reach the VYRON server. Check the deployment, then retry."
                : "This app needs a Telegram session. Open it from the bot to unlock playback."}
            </span>
            <button
              type="button"
              className="btn btn-ghost sm"
              disabled={retrying}
              onClick={async () => {
                setRetrying(true);
                await refreshState();
                setRetrying(false);
              }}
            >
              {retrying ? "…" : "Retry"}
            </button>
          </div>
        )}

        <div className="view" key={view}>
          {page}
        </div>

        <footer className="foot">
          <span>VYRON v{state?.version ?? "1.2.0"}</span>
          <span className="foot-dot" />
          <span>{state?.streaming ? "voice chat" : "file mode"}</span>
          <span className="foot-dot" />
          <button type="button" onClick={() => setView("search")}>
            <Download size={12} /> get music
          </button>
        </footer>
      </main>

      <Dock />
      <Tabs />
      <Sheet />
      {audio.expanded && <Player />}

      {toastMessage && (
        <div className={`toast toast-${toastTone}`} role="status" aria-live="polite">
          {toastMessage}
        </div>
      )}
    </div>
  );
}
