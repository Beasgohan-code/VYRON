import { Heart, History, ListMusic, Play, Plus, Radio, Shuffle, Trash2 } from "lucide-react";
import { useApp } from "../lib/store";
import { fmtDuration } from "../lib/format";
import { Cover } from "../components/Cover";
import { TrackRow } from "../components/TrackRow";
import { useViewReveal } from "../lib/anim";

export function Library() {
  const {
    state,
    playlists,
    libraryFilter,
    setLibraryFilter,
    openModal,
    openPlaylist,
    selectedPlaylist,
    play,
    act,
    toast,
    audio,
    refreshPlaylists,
  } = useApp();
  const stage = useViewReveal<HTMLDivElement>("library", ".stage-block");

  const liked = state?.favorites ?? [];
  const history = state?.history ?? [];
  const tracks = libraryFilter === "liked" ? liked : history;

  return (
    <div className="stage" ref={stage}>
      <header className="screen-head stage-block">
        <h1>Library</h1>
        <p>Everything you saved, played and collected.</p>
      </header>

      <div className="seg stage-block">
        <button
          type="button"
          className={`seg-btn ${libraryFilter === "liked" ? "active" : ""}`}
          onClick={() => setLibraryFilter("liked")}
        >
          <Heart size={14} /> Liked <i>{liked.length}</i>
        </button>
        <button
          type="button"
          className={`seg-btn ${libraryFilter === "history" ? "active" : ""}`}
          onClick={() => setLibraryFilter("history")}
        >
          <History size={14} /> History <i>{history.length}</i>
        </button>
        <button
          type="button"
          className={`seg-btn ${libraryFilter === "playlists" ? "active" : ""}`}
          onClick={() => setLibraryFilter("playlists")}
        >
          <ListMusic size={14} /> Playlists <i>{playlists.length}</i>
        </button>
      </div>

      {libraryFilter !== "playlists" && (
        <section className="stage-block">
          <header className="section-head">
            <h2>{libraryFilter === "liked" ? "Liked songs" : "Recently played"}</h2>
            {tracks.length > 0 && (
              <button
                type="button"
                className="section-link"
                onClick={() => {
                  void play(tracks[0], "play_now");
                }}
              >
                <Play size={13} /> Play all
              </button>
            )}
          </header>

          {tracks.length === 0 ? (
            <div className="empty">
              <span className="empty-icon">
                {libraryFilter === "liked" ? <Heart size={20} /> : <History size={20} />}
              </span>
              <b>{libraryFilter === "liked" ? "Nothing liked yet" : "Nothing played yet"}</b>
              <p>
                {libraryFilter === "liked"
                  ? "Tap the heart on any track and it lands here."
                  : "Play something in the app or the voice chat and it will show up."}
              </p>
            </div>
          ) : (
            <ul className="rows">
              {tracks.map((track, index) => (
                <TrackRow key={`${track.id ?? track.title}-${index}`} track={track} index={index + 1} />
              ))}
            </ul>
          )}
        </section>
      )}

      {libraryFilter === "playlists" && (
        <section className="stage-block">
          <header className="section-head">
            <h2>Playlists</h2>
            <button type="button" className="section-link" onClick={() => openModal({ type: "new-playlist" })}>
              <Plus size={13} /> New
            </button>
          </header>

          {selectedPlaylist ? (
            <div className="playlist-detail">
              <header className="playlist-head">
                <Cover track={{ title: selectedPlaylist.name, thumbnail: selectedPlaylist.covers?.[0] }} />
                <div>
                  <b>{selectedPlaylist.name}</b>
                  <span>
                    {selectedPlaylist.count} tracks · {fmtDuration(selectedPlaylist.duration)}
                  </span>
                  <div className="playlist-actions">
                    {/* Play the tracks themselves. This used to pass the
                        playlist *name* to the song resolver, so "Play" on a
                        playlist called "Chill" searched for a song called
                        Chill — and usually played something else entirely. */}
                    <button
                      type="button"
                      className="btn btn-primary sm"
                      disabled={(selectedPlaylist.tracks ?? []).length === 0}
                      onClick={() => {
                        const tracks = selectedPlaylist.tracks ?? [];
                        if (tracks[0]) audio.play(tracks[0], tracks);
                      }}
                    >
                      <Play size={14} fill="currentColor" /> Play
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost sm"
                      disabled={(selectedPlaylist.tracks ?? []).length === 0}
                      onClick={() => {
                        const tracks = [...(selectedPlaylist.tracks ?? [])];
                        for (let index = tracks.length - 1; index > 0; index -= 1) {
                          const swap = Math.floor(Math.random() * (index + 1));
                          [tracks[index], tracks[swap]] = [tracks[swap], tracks[index]];
                        }
                        if (tracks[0]) audio.play(tracks[0], tracks);
                      }}
                    >
                      <Shuffle size={13} /> Shuffle
                    </button>
                    <button
                      type="button"
                      className="btn btn-ghost sm"
                      onClick={() => void act("playlist_play", selectedPlaylist.id)}
                    >
                      <Radio size={13} /> Cast
                    </button>
                    <button type="button" className="btn btn-ghost sm" onClick={() => openPlaylist(null)}>
                      Close
                    </button>
                  </div>
                </div>
              </header>
              <ul className="rows">
                {(selectedPlaylist.tracks ?? []).map((track, index) => (
                  <TrackRow
                    key={`${track.id ?? track.title}-${index}`}
                    track={track}
                    index={index + 1}
                    onRemove={async () => {
                      const payload = await act("playlist_remove", {
                        playlist_id: selectedPlaylist.id,
                        id: track.id,
                      });
                      if (payload) {
                        toast("Removed from the playlist", "success");
                        await refreshPlaylists();
                        openPlaylist({
                          ...selectedPlaylist,
                          tracks: (selectedPlaylist.tracks ?? []).filter((item) => item !== track),
                          count: Math.max(0, selectedPlaylist.count - 1),
                        });
                      }
                    }}
                  />
                ))}
                {(selectedPlaylist.tracks ?? []).length === 0 && (
                  <li className="fine">This playlist is empty — add tracks from any result.</li>
                )}
              </ul>
            </div>
          ) : playlists.length === 0 ? (
            <div className="empty">
              <span className="empty-icon">
                <ListMusic size={20} />
              </span>
              <b>No playlists yet</b>
              <p>Group tracks into a collection — the bot can play it in any chat.</p>
              <button type="button" className="btn btn-primary" onClick={() => openModal({ type: "new-playlist" })}>
                <Plus size={15} /> Create playlist
              </button>
            </div>
          ) : (
            <div className="card-grid">
              {playlists.map((playlist) => (
                <div key={playlist.id} className="playlist-card">
                  <button type="button" className="playlist-open" onClick={() => openPlaylist(playlist)}>
                    <Cover track={{ title: playlist.name, thumbnail: playlist.covers?.[0] }} />
                    <b>{playlist.name}</b>
                    <span>
                      {playlist.count} tracks · {fmtDuration(playlist.duration)}
                    </span>
                  </button>
                  <button
                    type="button"
                    className="btn-icon danger playlist-delete"
                    aria-label={`Delete ${playlist.name}`}
                    onClick={async () => {
                      const payload = await act("playlist_delete", { playlist_id: playlist.id });
                      if (payload) {
                        toast(`Deleted “${playlist.name}”`, "success");
                        openPlaylist(null);
                      }
                    }}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
