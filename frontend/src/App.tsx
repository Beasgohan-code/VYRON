import { useEffect, useState } from "react";
import { CommandPalette } from "./components/CommandPalette";
import { MobileTabBar, MiniPlayer } from "./components/MobileChrome";
import { PlayBar } from "./components/PlayBar";
import { Modal } from "./components/Modal";
import { NowPlayingRail } from "./components/NowPlayingRail";
import { ShortcutSheet } from "./components/ShortcutSheet";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { useApp } from "./lib/store";
import { ApiView } from "./views/ApiView";
import { HomeView } from "./views/HomeView";
import { LibraryView } from "./views/LibraryView";
import { PlaylistsView } from "./views/PlaylistsView";
import { ProfileView } from "./views/ProfileView";
import { QueueView } from "./views/QueueView";
import { RoomsView } from "./views/RoomsView";
import { PlayerView } from "./views/PlayerView";
import { SearchView } from "./views/SearchView";

export default function App() {
  const { view, audio, toastMessage, toastTone } = useApp();
  const [shortcuts, setShortcuts] = useState(false);

  /* keyboard shortcuts — ignored while typing */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
      if (typing) return;
      if (event.key === "/") {
        event.preventDefault();
        window.dispatchEvent(new CustomEvent("vyron:focus-search"));
      }
      if (event.code === "Space") {
        event.preventDefault();
        audio.toggle();
      }
      if (event.key === "ArrowRight") audio.seekBy(5);
      if (event.key === "ArrowLeft") audio.seekBy(-5);
      if (event.key.toLowerCase() === "n") audio.next();
      if (event.key.toLowerCase() === "m") audio.toggleMute();
      if (event.key === "?") {
        event.preventDefault();
        setShortcuts((open) => !open);
      }
      if (event.key === "Escape") {
        audio.setExpanded(false);
        setShortcuts(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [audio]);

  return (
    <div className="app">
      <Sidebar />

      <main className="main">
        <Topbar />
        {view === "home" && <HomeView />}
        {view === "search" && <SearchView />}
        {view === "library" && <LibraryView />}
        {view === "queue" && <QueueView />}
        {view === "playlists" && <PlaylistsView />}
        {view === "rooms" && <RoomsView />}
        {view === "api" && <ApiView />}
        {view === "profile" && <ProfileView />}
        <footer className="app-footer">
          <span>VYRON · music beyond limits</span>
          <span>streaming · downloads · listen together</span>
        </footer>
      </main>

      <aside className="rail">
        <NowPlayingRail />
      </aside>

      <PlayBar />
      <MiniPlayer />
      <MobileTabBar />
      {audio.expanded && <PlayerView />}
      <Modal />
      <CommandPalette />
      <ShortcutSheet open={shortcuts} onClose={() => setShortcuts(false)} />

      <div className={`toast ${toastMessage ? "show" : ""} ${toastTone}`} role="status" aria-live="polite">
        {toastMessage}
      </div>
    </div>
  );
}
