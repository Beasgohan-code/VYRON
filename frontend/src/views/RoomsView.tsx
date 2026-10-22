import { ChevronRight, ExternalLink, Radio, RefreshCw, Users } from "lucide-react";
import { Cover } from "../components/Cover";
import { useApp } from "../lib/store";

export function RoomsView() {
  const { rooms, refreshRooms, toast } = useApp();
  const totalListeners = rooms.reduce((sum, room) => sum + room.listeners, 0);

  const openRoom = (username?: string) => {
    const url = username ? `https://t.me/${username}` : "https://t.me/VyronMusicBot";
    const tg = window.Telegram?.WebApp;
    if (tg?.openTelegramLink) tg.openTelegramLink(url);
    else window.open(url, "_blank", "noopener");
  };

  return (
    <section className="view active">
      <div className="view-head row-between">
        <div>
          <h1>Listen together</h1>
          <p className="muted">
            {rooms.length
              ? `${rooms.length} live room${rooms.length === 1 ? "" : "s"} · ${totalListeners} listeners`
              : "Live voice chats the bot is streaming in right now"}
          </p>
        </div>
        <button
          type="button"
          className="pill-btn ghost"
          onClick={async () => {
            await refreshRooms();
            toast("Rooms refreshed");
          }}
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <ul className="rooms">
        {rooms.map((room) => (
          <li key={room.chat_id} className="room-card">
            <Cover track={room.track} />
            <div className="info">
              <b>{room.title}</b>
              <span>
                <span className={`live ${room.playing && !room.paused ? "" : "off"}`}>
                  <i />
                  {room.playing && !room.paused ? "live" : "paused"}
                </span>
                · <Users size={11} /> {room.listeners} listening
              </span>
              <span>{room.track?.title ?? "nothing playing"}</span>
            </div>
            <div className="room-meta">
              <span className="source-pill">{room.volume ?? 100}%</span>
              {room.effects?.length ? <span className="source-pill">{room.effects.join(" · ")}</span> : null}
            </div>
            <button type="button" className="mini-action play" aria-label="Open room" onClick={() => openRoom(room.username)}>
              {room.username ? <ExternalLink size={14} /> : <ChevronRight size={14} />}
            </button>
          </li>
        ))}
      </ul>

      {rooms.length === 0 && (
        <p className="empty-state">
          No rooms live right now. Add the bot to a group, start a voice chat and send <code>/play</code>.
        </p>
      )}

      <div className="cards-grid">
        <article className="panel">
          <div className="panel-head">
            <h3>
              <Radio size={14} /> How it works
            </h3>
          </div>
          <ol className="steps">
            <li>Add the bot to a group and give it voice-chat rights.</li>
            <li>Start a voice chat, then <code>/play lofi</code>.</li>
            <li>Everyone in the call hears the same track, in sync.</li>
            <li>Use <code>/np</code> or this app to control playback live.</li>
          </ol>
        </article>
        <article className="panel">
          <div className="panel-head">
            <h3>
              <Users size={14} /> Your session
            </h3>
          </div>
          <p className="muted small">
            Rooms follow the assistant account, so playback keeps going even if your phone sleeps. 24/7 mode keeps the
            bot in the chat between tracks.
          </p>
          <button type="button" className="pill-btn accent wide" onClick={() => openRoom()}>
            Open the bot
          </button>
        </article>
      </div>
    </section>
  );
}
