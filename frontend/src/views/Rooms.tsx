import { Radio, RefreshCw, Users } from "lucide-react";
import { useApp } from "../lib/store";
import { Cover } from "../components/Cover";
import { useViewReveal } from "../lib/anim";

export function Rooms() {
  const { rooms, refreshRooms, state } = useApp();
  const stage = useViewReveal<HTMLDivElement>("rooms", ".room-card");
  const live = rooms.filter((room) => room.playing && !room.paused).length;

  return (
    <div className="stage" ref={stage}>
      <header className="screen-head">
        <h1>Rooms</h1>
        <p>
          {rooms.length === 0
            ? "Voice chats the bot is playing in."
            : `${live} live · ${rooms.length} room${rooms.length === 1 ? "" : "s"}`}
        </p>
        <button type="button" className="btn btn-ghost sm" onClick={() => void refreshRooms()}>
          <RefreshCw size={14} /> Refresh
        </button>
      </header>

      {rooms.length === 0 ? (
        <div className="empty">
          <span className="empty-icon">
            <Radio size={20} />
          </span>
          <b>No active rooms</b>
          <p>
            Open a voice chat in your group and send <code>/play</code> to {state?.bot ? `@${state.bot}` : "the bot"} —
            it joins and starts streaming.
          </p>
        </div>
      ) : (
        <div className="room-grid">
          {rooms.map((room) => (
            <article key={room.chat_id} className={`room-card ${room.playing && !room.paused ? "live" : ""}`}>
              <div className="room-art">
                {room.track ? <Cover track={room.track} /> : <span className="room-art-empty" />}
                <span className={`live-dot ${room.playing && !room.paused ? "" : "idle"}`} />
              </div>
              <div className="room-main">
                <b>{room.title}</b>
                <span className="room-track">{room.track?.title ?? "nothing playing"}</span>
                <span className="room-meta">
                  <Users size={12} /> {room.listeners} listening · vol {room.volume}
                </span>
              </div>
              <span className={`room-state ${room.playing && !room.paused ? "on" : ""}`}>
                {room.playing && !room.paused ? "live" : room.paused ? "paused" : "idle"}
              </span>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
