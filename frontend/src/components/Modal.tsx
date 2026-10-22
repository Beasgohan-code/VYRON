import { Check, Download, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { coverFor } from "../lib/format";

export function Modal() {
  const { modal, closeModal, openModal, act, play, toast, refreshPlaylists, playlists } = useApp();
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

  const title =
    modal.type === "download"
      ? "Download"
      : modal.type === "new-playlist"
      ? "New playlist"
      : modal.type === "add-to-playlist"
      ? "Add to playlist"
      : "Track";

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

  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label={title} onClick={(event) => {
      if (event.target === event.currentTarget) closeModal();
    }}>
      <div className="modal-card">
        <div className="modal-head">
          <h3>{title}</h3>
          <button type="button" className="icon-btn" onClick={closeModal} aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          {modal.type === "download" && (
            <form
              className="modal-form"
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
                autoFocus
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Paste a YouTube link or type a name…"
              />
              <span className="field-label">Format</span>
              <div className="quality-row">
                <label>
                  <input type="radio" name="kind" checked={kind === "audio"} onChange={() => setKind("audio")} />
                  <span>MP3 · 320 kbps</span>
                </label>
                <label>
                  <input type="radio" name="kind" checked={kind === "video"} onChange={() => setKind("video")} />
                  <span>MP4 · 720p</span>
                </label>
              </div>
              <p className="muted small">The bot sends the file to your chat — this window can stay open.</p>
              <button type="submit" className="pill-btn accent wide" disabled={busy}>
                <Download size={15} />
                {busy ? "Starting…" : "Download"}
              </button>
            </form>
          )}

          {modal.type === "new-playlist" && (
            <form
              className="modal-form"
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
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Late night drive"
              />
              <button type="submit" className="pill-btn accent wide" disabled={busy}>
                <Plus size={15} />
                {busy ? "Creating…" : "Create playlist"}
              </button>
            </form>
          )}

          {modal.type === "add-to-playlist" && (
            <ul className="rows">
              {playlists.length === 0 && <li className="empty-row">No playlists yet — create one first.</li>}
              {playlists.map((playlist) => (
                <li key={playlist.id} onClick={() => void addToPlaylist(playlist.id, modal.track)}>
                  <span className="rk">
                    <Check size={13} />
                  </span>
                  <span className="tx">
                    <b>{playlist.name}</b>
                    <span>{playlist.count} tracks</span>
                  </span>
                </li>
              ))}
            </ul>
          )}

          {modal.type === "track" && (
            <>
              <div className="modal-track">
                <img src={modal.track.thumbnail || coverFor(modal.track)} alt="" />
                <div>
                  <b>{modal.track.title}</b>
                  <span>{modal.track.uploader || "unknown artist"}</span>
                </div>
              </div>
              <ul className="rows">
                <li
                  onClick={() => {
                    void play(modal.track.query ?? `${modal.track.title} ${modal.track.uploader ?? ""}`, "play_now");
                    closeModal();
                  }}
                >
                  <span className="rk">▸</span>
                  <span className="tx">
                    <b>Play now</b>
                  </span>
                </li>
                <li
                  onClick={() => {
                    void play(modal.track.query ?? `${modal.track.title} ${modal.track.uploader ?? ""}`, "play");
                    closeModal();
                  }}
                >
                  <span className="rk">+</span>
                  <span className="tx">
                    <b>Add to queue</b>
                  </span>
                </li>
                <li
                  onClick={async () => {
                    const payload = await act<{ saved?: boolean }>("favorite_track", modal.track);
                    toast(payload?.saved ? "Added to liked songs" : "Already liked", "success");
                    closeModal();
                  }}
                >
                  <span className="rk">♥</span>
                  <span className="tx">
                    <b>Add to liked songs</b>
                  </span>
                </li>
                <li onClick={() => openModal({ type: "add-to-playlist", track: modal.track })}>
                  <span className="rk">≡</span>
                  <span className="tx">
                    <b>Add to playlist</b>
                  </span>
                </li>
                <li onClick={() => openModal({ type: "download", query: modal.track.query ?? modal.track.title })}>
                  <span className="rk">⤓</span>
                  <span className="tx">
                    <b>Download</b>
                  </span>
                </li>
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
