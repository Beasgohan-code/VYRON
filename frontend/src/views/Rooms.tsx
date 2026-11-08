import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, Radio, RefreshCw, Users } from "lucide-react";
import { useApp } from "../lib/store";
import { Cover } from "../components/Cover";
import { useViewReveal } from "../lib/anim";
import { RoomScreen } from "./Room";
import type { Room as RoomSummary } from "../lib/types";

export function Rooms() {
  const { rooms, refreshRooms, state, attachRoom } = useApp();
  const [busy, setBusy] = useState<number | null>(null);
  /* Opening a room is how you get from "these exist" to "you are in one". */
  const [open, setOpen] = useState<RoomSummary | null>(null);
  /* Auto-entry happens once per visit: if somebody closes the room they came
     from, they meant it, and re-opening it under their thumb is a fight. */
  const entered = useRef(false);

  /**
   * You are already somewhere — open *that* room.
   *
   * `/api/room` attaches the app to a chat the caller administers, and the
   * state then says which chat this phone is driving. Landing on a grid and
   * asking the user to find the row again is the step that made the old screen
   * feel like a directory instead of a player. A `#room=-100…` hash (a link
   * pasted into the group) does the same for a room they are only listening to.
   */
  useEffect(() => {
    if (entered.current || open || rooms.length === 0) return;
    const wanted = (() => {
      const match = /room=(-?\d+)/.exec(window.location.hash);
      if (match) return Number(match[1]);
      return state?.chat?.id ?? null;
    })();
    if (wanted === null) return;
    const room = rooms.find((entry) => entry.chat_id === wanted);
    if (!room) return;
    entered.current = true;
    setOpen(room);
  }, [open, rooms, state?.chat?.id]);
  const stage = useViewReveal<HTMLDivElement>("rooms", ".room-card");
  const live = rooms.filter((room) => room.playing && !room.paused).length;

  return (
    <div className="stage" ref={stage}>
      <header className="screen-head with-art">
        <div className="head-art" aria-hidden="true" />
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
            <article
              key={room.chat_id}
              className={`room-card ${room.playing && !room.paused ? "live" : ""}`}
              tabIndex={0}
              role="button"
              aria-label={`Open ${room.title}`}
              onClick={() => setOpen(room)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setOpen(room);
                }
              }}
            >
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
              <div className="room-side">
                <span className={`room-state ${room.playing && !room.paused ? "on" : ""}`}>
                  {room.playing && !room.paused ? "live" : room.paused ? "paused" : "idle"}
                </span>
                {/* Telegram opens Mini Apps only in DMs, so this is how a group
                    player is driven from the app — no URL, no browser. */}
                <button
                  type="button"
                  className={`room-attach ${state?.chat?.id === room.chat_id ? "on" : ""}`}
                  disabled={busy === room.chat_id}
                  onClick={async (event) => {
                    event.stopPropagation();
                    setBusy(room.chat_id);
                    await attachRoom(room.chat_id);
                    setBusy(null);
                    void refreshRooms();
                  }}
                >
                  {state?.chat?.id === room.chat_id ? <Check size={13} /> : <Radio size={13} />}
                  {state?.chat?.id === room.chat_id ? "Controlling" : "Control"}
                </button>
                <span className="room-open" aria-hidden="true">
                  Open <ChevronRight size={13} />
                </span>
              </div>
            </article>
          ))}
        </div>
      )}

      {open ? <RoomScreen room={open} onClose={() => setOpen(null)} /> : null}
    </div>
  );
}
