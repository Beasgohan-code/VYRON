import { Download, Heart, ListPlus, Play, Plus } from "lucide-react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "../components/Cover";
import { ResultRow } from "../components/ResultRow";

const TABS = [
  { key: "liked", label: "Liked songs" },
  { key: "playlists", label: "Playlists" },
  { key: "history", label: "Recently played" },
] as const;

export function LibraryView() {
  const {
    state,
    playlists,
    libraryFilter,
    setLibraryFilter,
    openPlaylist,
    openModal,
    play,
    toast,
    act,
  } = useApp();

  const favorites = state?.favorites ?? [];
  const history = state?.history ?? [];

  const exportLibrary = () => {
    const payload = {
      exported: new Date().toISOString(),
      favorites,
      history,
      playlists,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "vyron-library.json";
    link.click();
    URL.revokeObjectURL(url);
    toast("Library exported", "success");
  };

  return (
    <section className="view active">
      <div className="view-head row-between">
        <div>
          <h1>Library</h1>
          <p className="muted">Liked songs, playlists and recently played</p>
        </div>
        <div className="head-actions">
          <button type="button" className="pill-btn ghost" onClick={exportLibrary}>
            <Download size={14} /> Export
          </button>
          <button type="button" className="pill-btn accent" onClick={() => openModal({ type: "new-playlist" })}>
            <Plus size={14} /> New
          </button>
        </div>
      </div>

      <div className="tabs">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`tab ${libraryFilter === tab.key ? "active" : ""}`}
            onClick={() => setLibraryFilter(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {libraryFilter === "liked" && (
        <>
          <div className="liked-card">
            <div className="liked-art">
              <Heart size={26} fill="currentColor" />
            </div>
            <div>
              <strong>Liked songs</strong>
              <span className="muted">{favorites.length} tracks</span>
            </div>
            <button
              type="button"
              className="round-play"
              aria-label="Play liked songs"
              onClick={async () => {
                if (!favorites.length) {
                  toast("No liked songs yet");
                  return;
                }
                toast(`Queuing ${Math.min(favorites.length, 25)} liked songs…`);
                for (const track of favorites.slice(0, 25)) {
                  await act("play", track.query ?? `${track.title} ${track.uploader ?? ""}`);
                }
                toast("Liked songs queued", "success");
              }}
            >
              <Play size={17} fill="currentColor" />
            </button>
          </div>
          <ul className="result-list">
            {favorites.map((track, index) => (
              <ResultRow key={`${track.id ?? track.title}-${index}`} track={track} index={index + 1} />
            ))}
          </ul>
          {favorites.length === 0 && <p className="empty-state">Like a track while it plays — it lands here.</p>}
        </>
      )}

      {libraryFilter === "playlists" && (
        <div className="playlist-grid">
          {playlists.map((playlist) => (
            <button key={playlist.id} type="button" className="playlist-card" onClick={() => openPlaylist(playlist)}>
              <div className="covers">
                {Array.from({ length: 4 }).map((_, index) => {
                  const cover = playlist.covers?.[index];
                  return cover ? (
                    <img key={index} src={cover} alt="" loading="lazy" />
                  ) : (
                    <span key={index} className="ph" />
                  );
                })}
              </div>
              <b>{playlist.name}</b>
              <span>
                {playlist.count} tracks · {fmtDuration(playlist.duration)}
              </span>
            </button>
          ))}
        </div>
      )}

      {libraryFilter === "playlists" && playlists.length === 0 && (
        <p className="empty-state">
          No playlists yet — create one, or save a queue from the bot with <code>/savepl</code>.
        </p>
      )}

      {libraryFilter === "history" && (
        <ul className="result-list">
          {history.map((track, index) => (
            <ResultRow key={`${track.id ?? track.title}-${index}`} track={track} index={index + 1} />
          ))}
        </ul>
      )}

      {libraryFilter === "history" && history.length === 0 && (
        <p className="empty-state">Nothing played yet.</p>
      )}

      <div className="cta-row">
        <button type="button" className="cta" onClick={() => void play(favorites[0]?.query, "play_now")}>
          <span>
            <b>Shuffle liked songs</b>
            <small>Fresh order every time</small>
          </span>
          <Play size={16} fill="currentColor" />
        </button>
        <button type="button" className="cta" onClick={() => openModal({ type: "new-playlist" })}>
          <span>
            <b>New playlist</b>
            <small>Group tracks into a set</small>
          </span>
          <ListPlus size={16} />
        </button>
      </div>

      {playlists.length > 0 && libraryFilter !== "playlists" && (
        <>
          <div className="section-head">
            <h2>Your playlists</h2>
          </div>
          <div className="shelf">
            {playlists.map((playlist) => (
              <button key={playlist.id} type="button" className="card-track" onClick={() => openPlaylist(playlist)}>
                <div className="cover">
                  <Cover track={{ title: playlist.name, thumbnail: playlist.covers?.[0] }} />
                </div>
                <div className="t">{playlist.name}</div>
                <div className="s">{playlist.count} tracks</div>
              </button>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
