import { useEffect } from "react";
import { MobileTabBar, MiniPlayer } from "./components/MobileChrome";
import { Modal } from "./components/Modal";
import { NowPlayingRail } from "./components/NowPlayingRail";
import { Sidebar } from "./components/Sidebar";
import { Topbar } from "./components/Topbar";
import { useApp } from "./lib/store";
import { HomeView } from "./views/HomeView";
import { LibraryView } from "./views/LibraryView";
import { PlaylistsView } from "./views/PlaylistsView";
import { ProfileView } from "./views/ProfileView";
import { QueueView } from "./views/QueueView";
import { RoomsView } from "./views/RoomsView";
import { SearchView } from "./views/SearchView";

export default function App() {
  const { view, act, toastMessage, toastTone } = useApp();

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
        void act("toggle");
      }
      if (event.key.toLowerCase() === "n") void act("skip", 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [act]);

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
        {view === "profile" && <ProfileView />}
        <footer className="app-footer">
          <span>VYRON · music beyond limits</span>
          <span>streaming · downloads · listen together</span>
        </footer>
      </main>

      <aside className="rail">
        <NowPlayingRail />
      </aside>

      <MiniPlayer />
      <MobileTabBar />
      <Modal />

      <div className={`toast ${toastMessage ? "show" : ""} ${toastTone}`} role="status" aria-live="polite">
        {toastMessage}
      </div>
    </div>
  );
}
