import { Check, Download, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { Cover } from "./Cover";

/**
 * Bottom-sheet host for the app's small tasks: download, track options,
 * playlist creation. One sheet, one place, dismissible by tapping the scrim.
 */
export function Sheet() {
  const { modal, closeModal, openModal, act, play, cast, toast, refreshPlaylists, playlists } = useApp();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"audio" | "video">("audio");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!modal) return;
    setBusy(false);
    if (modal.type === "download") {
      setQuery(modal.query ?? "");
      setKind(modal.kind ?? "audio");
    }
    if (modal.type === "new-playlist") setName("");
  }, [modal]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeModal();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closeModal]);

  if (!modal) return null;

  const titles: Record<string, string> = {
    download: "Download",
    "new-playlist": "New playlist",
    "add-to-playlist": "Add to playlist",
    track: "Track",
  };

  const submitDownload = async () => {
    if (!query.trim() || busy) return;
    setBusy(true);
    const payload = await act<{ started?: boolean }>("download", { query: query.trim(), kind });
    setBusy(false);
    if (payload) {
      toast(`Download started · ${kind === "video" ? "MP4" : "MP3"}`, "success");
      closeModal();
    }
  };

  const submitPlaylist = async () => {
    const clean = name.trim();
    if (!clean || busy) return;
    setBusy(true);
    const payload = await act<{ playlist?: { id: string; name: string } }>("playlist_create", clean);
    setBusy(false);
    if (payload?.playlist) {
      toast(`Playlist “${payload.playlist.name}” created`, "success");
      await refreshPlaylists();
      closeModal();
    }
  };

  const addToPlaylist = async (playlistId: string, track: Track) => {
    const payload = await act<{ added?: number }>("playlist_add", { playlist_id: playlistId, track });
    toast(payload?.added ? "Added to playlist" : "Already in that playlist", payload?.added ? "success" : "info");
    closeModal();
  };

  const trackAction = async (label: string, run: () => void | Promise<void>) => {
    void label;
    await run();
    closeModal();
  };

  return (
    <div
      className="scrim"
      role="dialog"
      aria-modal="true"
      aria-label={titles[modal.type] ?? "Sheet"}
      onClick={(event) => {
        if (event.target === event.currentTarget) closeModal();
      }}
    >
      <div className="sheet">
        <span className="grabber" aria-hidden="true" />
        <div className="sheet-head">
          <h3>{titles[modal.type]}</h3>
          <button type="button" className="btn-icon" onClick={closeModal} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <div className="sheet-body">
          {modal.type === "download" && (
            <form
              className="sheet-form"
              onSubmit={(event) => {
                event.preventDefault();
                void submitDownload();
              }}
            >
              <label className="field-label" htmlFor="dl-query">
                Link or search
              </label>
              <input
                id="dl-query"
                className="text-input"
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Paste a YouTube link or type a name…"
              />
              <span className="field-label">Format</span>
              <div className="seg">
                <button
                  type="button"
                  className={`seg-btn ${kind === "audio" ? "active" : ""}`}
                  onClick={() => setKind("audio")}
                >
                  MP3 · 320
                </button>
                <button
                  type="button"
                  className={`seg-btn ${kind === "video" ? "active" : ""}`}
                  onClick={() => setKind("video")}
                >
                  MP4 · 720p
                </button>
              </div>
              <p className="fine">The bot sends the file to your chat — this window can stay open.</p>
              <button type="submit" className="btn btn-primary wide" disabled={busy}>
                <Download size={15} />
                {busy ? "Starting…" : "Download"}
              </button>
            </form>
          )}

          {modal.type === "new-playlist" && (
            <form
              className="sheet-form"
              onSubmit={(event) => {
                event.preventDefault();
                void submitPlaylist();
              }}
            >
              <label className="field-label" htmlFor="pl-name">
                Name
              </label>
              <input
                id="pl-name"
                className="text-input"
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Late night drive"
              />
              <button type="submit" className="btn btn-primary wide" disabled={busy}>
                <Plus size={15} />
                {busy ? "Creating…" : "Create playlist"}
              </button>
            </form>
          )}

          {modal.type === "add-to-playlist" && (
            <ul className="sheet-list">
              {playlists.length === 0 && <li className="fine">No playlists yet — create one first.</li>}
              {playlists.map((playlist) => (
                <li key={playlist.id}>
                  <button type="button" onClick={() => void addToPlaylist(playlist.id, modal.track)}>
                    <span className="sheet-icon">
                      <Check size={14} />
                    </span>
                    <span className="sheet-li-text">
                      <b>{playlist.name}</b>
                      <span>{playlist.count} tracks</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {modal.type === "track" && (
            <>
              <div className="sheet-track">
                <Cover track={modal.track} className="sheet-cover" />
                <div>
                  <b>{modal.track.title}</b>
                  <span>{modal.track.uploader || "unknown artist"}</span>
                </div>
              </div>
              <ul className="sheet-list">
                <li>
                  <button type="button" onClick={() => trackAction("play", () => play(modal.track, "play_now"))}>
                    <span className="sheet-icon">▸</span>
                    <span className="sheet-li-text">
                      <b>Play now</b>
                      <span>in this app</span>
                    </span>
                  </button>
                </li>
                <li>
                  <button type="button" onClick={() => trackAction("queue", () => play(modal.track, "play"))}>
                    <span className="sheet-icon">+</span>
                    <span className="sheet-li-text">
                      <b>Add to queue</b>
                      <span>play it next</span>
                    </span>
                  </button>
                </li>
                <li>
                  <button type="button" onClick={() => trackAction("cast", () => cast(modal.track, "play_now"))}>
                    <span className="sheet-icon">⌁</span>
                    <span className="sheet-li-text">
                      <b>Play in the voice chat</b>
                      <span>streams through the bot</span>
                    </span>
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    onClick={() =>
                      trackAction("like", async () => {
                        const payload = await act<{ saved?: boolean }>("favorite_track", modal.track);
                        toast(payload?.saved ? "Added to liked songs" : "Already liked", "success");
                      })
                    }
                  >
                    <span className="sheet-icon">♥</span>
                    <span className="sheet-li-text">
                      <b>Add to liked songs</b>
                      <span>saved to your library</span>
                    </span>
                  </button>
                </li>
                <li>
                  <button type="button" onClick={() => openModal({ type: "add-to-playlist", track: modal.track })}>
                    <span className="sheet-icon">≡</span>
                    <span className="sheet-li-text">
                      <b>Add to playlist</b>
                      <span>pick a collection</span>
                    </span>
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    onClick={() =>
                      openModal({ type: "download", query: modal.track.query ?? modal.track.title })
                    }
                  >
                    <span className="sheet-icon">⤓</span>
                    <span className="sheet-li-text">
                      <b>Download</b>
                      <span>MP3 or MP4 to your chat</span>
                    </span>
                  </button>
                </li>
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
