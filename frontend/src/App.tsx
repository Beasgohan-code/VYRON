import { ArrowUpRight, Compass, Download, Lock, WifiOff } from "lucide-react";
import { useEffect, useState } from "react";
import { Avatar } from "./components/Avatar";
import { BootScreen } from "./components/BootScreen";
import { Dock } from "./components/Dock";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Shortcuts } from "./components/Shortcuts";
import { Rail, Tabs } from "./components/Nav";
import { Sheet } from "./components/Sheet";
import { setOwnerToken } from "./lib/api";
import { SEEK_STEP, VOLUME_STEP, shortcutFor } from "./lib/keys";
import { useConnection, useUpdateReady } from "./lib/pwa";
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
  const { online } = useConnection();
  const update = useUpdateReady();

  const [shortcuts, setShortcuts] = useState(false);
  const { toggleLike } = useApp();

  /* Keyboard: one table (lib/keys) decides, this only routes. */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const action = shortcutFor(event, event.target);
      if (!action) return;
      if (action === "escape") {
        setShortcuts(false);
        if (audio.expanded) audio.setExpanded(false);
        return;
      }
      if (shortcuts) return; // the overlay owns the keyboard while it is open
      switch (action) {
        case "toggle":
          if (!audio.track) return;
          event.preventDefault();
          audio.toggle();
          break;
        case "next":
          event.preventDefault();
          if (audio.track) audio.next();
          break;
        case "prev":
          event.preventDefault();
          if (audio.track) audio.prev();
          break;
        case "seekForward":
          if (!audio.track) return;
          event.preventDefault();
          audio.seekBy(SEEK_STEP);
          break;
        case "seekBack":
          if (!audio.track) return;
          event.preventDefault();
          audio.seekBy(-SEEK_STEP);
          break;
        case "volumeUp":
          event.preventDefault();
          audio.setVolume(Math.min(1, audio.volume + VOLUME_STEP));
          break;
        case "volumeDown":
          event.preventDefault();
          audio.setVolume(Math.max(0, audio.volume - VOLUME_STEP));
          break;
        case "mute":
          audio.toggleMute();
          break;
        case "like":
          if (audio.track) void toggleLike(audio.track);
          break;
        case "search":
          event.preventDefault();
          setView("search");
          window.setTimeout(() => window.dispatchEvent(new Event("vyron:focus-search")), 60);
          break;
        case "queue":
          audio.setExpanded(true);
          break;
        case "help":
          event.preventDefault();
          setShortcuts((open) => !open);
          break;
        default:
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [audio, setView, shortcuts, toggleLike]);

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
      <BootScreen />
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
            <span className={`status-dot ${state?.streaming ? "on" : ""}`} title={state?.streaming ? "voice chat ready" : "voice engine offline"} />
            {/* Phone shell: the rail is gone, so the face lives here. */}
            <button
              type="button"
              className="topbar-avatar"
              aria-label="Your profile"
              onClick={() => setView("profile")}
            >
              <Avatar
                name={state?.user?.name}
                userId={state?.user?.id}
                photo={state?.user?.photo}
                size={30}
              />
            </button>
          </div>
        </header>

        {!online && (
          <div className="notice warn" role="status">
            <WifiOff size={15} />
            <span>
              You are offline. Playback stays as it is, and the last page is kept on this device.
            </span>
          </div>
        )}

        {update.ready && (
          <div className="notice" role="status">
            <span>A newer VYRON is ready.</span>
            <button type="button" className="btn btn-ghost sm" onClick={update.reload}>
              Reload
            </button>
          </div>
        )}

        {access === "offline" && (
          <div className="notice error">
            <WifiOff size={15} />
            <span>Cannot reach the VYRON server. Check the deployment, then retry.</span>
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

        {access === "locked" ? (
          <LockedGate
            bot={state?.bot ?? ""}
            retrying={retrying}
            onRetry={async () => {
              setRetrying(true);
              await refreshState();
              setRetrying(false);
            }}
          />
        ) : (
          <ErrorBoundary where={TITLES[view] ?? "view"} key={view}>
            <div className="view">{page}</div>
          </ErrorBoundary>
        )}

        <footer className="foot">
          <span>{state?.version ? `VYRON v${state.version}` : "VYRON"}</span>
          <span className="foot-dot" />
          <span>{state?.streaming ? "voice chat" : "engine off"}</span>
          <span className="foot-dot" />
          <button type="button" onClick={() => setView("search")}>
            <Download size={12} /> get music
          </button>
          <span className="foot-dot" />
          <button type="button" onClick={() => setShortcuts(true)} aria-label="Keyboard shortcuts">
            <kbd>?</kbd> shortcuts
          </button>
        </footer>
      </main>

      <Dock />
      <Tabs />
      <Sheet />
      <Shortcuts open={shortcuts} onClose={() => setShortcuts(false)} />
      {audio.expanded && <Player />}

      {toastMessage && (
        <div className={`toast toast-${toastTone}`} role="status" aria-live="polite">
          {toastMessage}
        </div>
      )}
    </div>
  );
}


/**
 * Outside Telegram there is no identity to sign requests with, so the app
 * explains exactly how to get in instead of showing empty shelves.
 */
function LockedGate({
  bot,
  retrying,
  onRetry,
}: {
  bot: string;
  retrying: boolean;
  onRetry: () => Promise<void>;
}) {
  const handle = bot || "VyronMusicBot";
  const [token, setToken] = useState("");
  const [tried, setTried] = useState(false);

  const submit = async () => {
    const clean = token.trim();
    if (!clean) return;
    setOwnerToken(clean);
    setTried(true);
    await onRetry();
  };

  return (
    <section className="gate">
      <div className="gate-art" aria-hidden="true" />
      <div className="gate-body">
        <span className="gate-badge">
          <Lock size={13} /> signed out
        </span>
        <h1>
          Open VYRON
          <em>inside Telegram</em>
        </h1>
        <p>
          The Mini App signs every request with your Telegram session, so your queue,
          likes and voice chat stay yours. Open the bot, then tap <b>Player</b>.
        </p>

        <div className="gate-actions">
          <a className="btn btn-primary" href={`https://t.me/${handle}`} target="_blank" rel="noreferrer">
            Open @{handle} <ArrowUpRight size={15} />
          </a>
          <button type="button" className="btn btn-ghost" disabled={retrying} onClick={() => void onRetry()}>
            {retrying ? "Checking…" : "I opened it — retry"}
          </button>
        </div>

        <ol className="gate-steps">
          <li>
            <b>1</b> Open <code>@{handle}</code> on Telegram
          </li>
          <li>
            <b>2</b> Tap the <code>Player</code> button in the menu
          </li>
          <li>
            <b>3</b> The app unlocks with your account
          </li>
        </ol>

        {/* A browser has no Telegram session, so the owner gets a real key. */}
        <form
          className="gate-token"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <label htmlFor="owner-token">Owner access</label>
          <input
            id="owner-token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="paste your owner token"
            value={token}
            onChange={(event) => setToken(event.target.value)}
          />
          <div className="row">
            <button type="submit" className="btn btn-primary sm" disabled={!token.trim() || retrying}>
              Unlock this browser
            </button>
            <small>Run <code>/apitoken</code> in the bot and open the link it sends.</small>
          </div>
          {tried && (
            <small>
              Still locked? The token may have expired — mint a new one with{" "}
              <code>/apitoken</code>, or revoke old ones in <code>/apitoken list</code>.
            </small>
          )}
        </form>
      </div>
    </section>
  );
}
