import { Headphones, ListPlus, Play, Plus, Trash2, X } from "lucide-react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { ResultRow } from "../components/ResultRow";

export function PlaylistsView() {
  const {
    playlists,
    selectedPlaylist,
    openPlaylist,
    openModal,
    act,
    audio,
    toast,
    refreshPlaylists,
  } = useApp();

  return (
    <section className="view active">
      <div className="view-head row-between">
        <div>
          <h1>Playlists</h1>
          <p className="muted">
            {playlists.length
              ? `${playlists.length} playlist${playlists.length === 1 ? "" : "s"} · ${fmtDuration(
                  playlists.reduce((sum, item) => sum + item.duration, 0)
                )} total`
              : "Your saved collections"}
          </p>
        </div>
        <button type="button" className="pill-btn accent" onClick={() => openModal({ type: "new-playlist" })}>
          <Plus size={14} /> Create
        </button>
      </div>

      <div className="playlist-grid">
        {playlists.map((playlist) => (
          <button key={playlist.id} type="button" className="playlist-card" onClick={() => openPlaylist(playlist)}>
            <div className="covers">
              {Array.from({ length: 4 }).map((_, index) => {
                const cover = playlist.covers?.[index];
                return cover ? <img key={index} src={cover} alt="" loading="lazy" /> : <span key={index} className="ph" />;
              })}
            </div>
            <b>{playlist.name}</b>
            <span>
              {playlist.count} tracks · {fmtDuration(playlist.duration)}
            </span>
          </button>
        ))}
      </div>

      {playlists.length === 0 && (
        <p className="empty-state">
          No playlists yet — create one above, or save a queue from the bot with <code>/savepl</code>.
        </p>
      )}

      {selectedPlaylist && (
        <div className="playlist-detail">
          <div className="panel-head">
            <h3>
              {selectedPlaylist.name} · {selectedPlaylist.count} tracks
            </h3>
            <div className="head-actions">
              <button
                type="button"
                className="pill-btn accent"
                onClick={async () => {
                  const payload = await act<{ queued?: number; name?: string }>("playlist_play", selectedPlaylist.id);
                  if (payload) toast(`Queued ${payload.queued ?? 0} tracks from “${payload.name ?? selectedPlaylist.name}”`, "success");
                }}
              >
                <Play size={14} /> Play all
              </button>
              <button
                type="button"
                className="pill-btn"
                onClick={() => {
                  const tracks = selectedPlaylist.tracks ?? [];
                  if (!tracks.length) {
                    toast("This playlist is empty", "error");
                    return;
                  }
                  audio.play(tracks[0], tracks);
                  audio.setExpanded(true);
                  toast(`Playing “${selectedPlaylist.name}” on this device`, "success");
                }}
              >
                <Headphones size={14} /> Play here
              </button>
              <button
                type="button"
                className="icon-btn"
                aria-label="Delete playlist"
                onClick={async () => {
                  const payload = await act<{ deleted?: boolean }>("playlist_delete", selectedPlaylist.id);
                  if (payload) {
                    toast(`Deleted “${selectedPlaylist.name}”`);
                    openPlaylist(null);
                    await refreshPlaylists();
                  }
                }}
              >
                <Trash2 size={15} />
              </button>
              <button type="button" className="icon-btn" aria-label="Close" onClick={() => openPlaylist(null)}>
                <X size={15} />
              </button>
            </div>
          </div>

          <ul className="result-list">
            {(selectedPlaylist.tracks ?? []).map((track, index) => (
              <ResultRow key={`${track.id ?? track.title}-${index}`} track={track} index={index + 1} />
            ))}
          </ul>

          {(selectedPlaylist.tracks ?? []).length === 0 && (
            <p className="empty-state">
              This playlist is empty — use <b>Add to playlist</b> from any track menu.
            </p>
          )}
        </div>
      )}

      <div className="cta-row">
        <button type="button" className="cta" onClick={() => openModal({ type: "new-playlist" })}>
          <span>
            <b>New playlist</b>
            <small>Empty canvas, your rules</small>
          </span>
          <ListPlus size={16} />
        </button>
        <button
          type="button"
          className="cta"
          onClick={() => toast("Open a track menu (⋯) to add it to a playlist")}
        >
          <span>
            <b>Add from any track</b>
            <small>Search, then tap ⋯ on a result</small>
          </span>
          <Plus size={16} />
        </button>
      </div>
    </section>
  );
}
