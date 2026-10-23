import {
  ListMusic,
  Play,
  RefreshCw,
  Shuffle,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { useState } from "react";
import { Cover } from "../components/Cover";
import { fmtDuration, totalDuration } from "../lib/format";
import { useApp } from "../lib/store";

type Tab = "app" | "call";

export function QueueView() {
  const { state, audio, act, toast } = useApp();
  const [tab, setTab] = useState<Tab>(audio.track ? "app" : "call");
  const callQueue = state?.queue ?? [];
  const callNow = state?.now;
  const settings = state?.settings;

  return (
    <section className="view active">
      <div className="view-head row-between">
        <div>
          <h1>Queue</h1>
          <p className="muted">
            {tab === "app"
              ? audio.queue.length
                ? `${audio.queue.length} here · ${totalDuration(audio.queue)}`
                : "Nothing queued in the app"
              : callQueue.length
                ? `${callQueue.length} in the call · ${totalDuration(callQueue)}`
                : callNow
                  ? "Nothing queued after this track"
                  : "The voice chat is idle"}
          </p>
        </div>
        <label className="switch-row">
          <span>Autoplay</span>
          <input
            type="checkbox"
            className="switch"
            checked={Boolean(settings?.autoplay)}
            onChange={async () => {
              const payload = await act<{ autoplay?: boolean }>("autoplay");
              if (payload) toast(`Autoplay ${payload.autoplay ? "on" : "off"}`);
            }}
          />
        </label>
      </div>

      <div className="segmented" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "app"}
          className={tab === "app" ? "active" : ""}
          onClick={() => setTab("app")}
        >
          <ListMusic size={14} /> This device
          <span className="seg-count">{audio.queue.length}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "call"}
          className={tab === "call" ? "active" : ""}
          onClick={() => setTab("call")}
        >
          <Users size={14} /> Voice chat
          <span className="seg-count">{callQueue.length}</span>
        </button>
      </div>

      {tab === "app" ? (
        <>
          <ul className="queue-list">
            {audio.track && (
              <li className="q-item playing">
                <span className="idx">▸</span>
                <Cover track={audio.track} />
                <div className="info">
                  <b>{audio.track.title}</b>
                  <span>
                    {audio.track.uploader || "unknown"} · {audio.playing ? "playing" : "paused"}
                  </span>
                </div>
                <span className="dur">
                  {fmtDuration(audio.position)} / {fmtDuration(audio.duration || audio.track.duration || 0)}
                </span>
                <button type="button" className="mini-action" aria-label="Pause or resume" onClick={audio.toggle}>
                  {audio.playing ? <span className="pause-glyph">❚❚</span> : <Play size={14} />}
                </button>
              </li>
            )}

            {audio.queue.map((track, index) =>
              audio.isCurrent(track) ? null : (
                <li key={`${track.id ?? track.title}-${index}`} className="q-item">
                  <span className="idx">{index + 1}</span>
                  <Cover track={track} />
                  <div className="info">
                    <b>{track.title}</b>
                    <span>{track.uploader || "unknown"}</span>
                  </div>
                  <span className="dur">{fmtDuration(track.duration)}</span>
                  <button
                    type="button"
                    className="mini-action"
                    aria-label="Play now"
                    onClick={() => audio.jumpTo(index)}
                  >
                    <Play size={13} />
                  </button>
                  <button
                    type="button"
                    className="mini-action"
                    aria-label="Remove"
                    onClick={() => audio.removeAt(index)}
                  >
                    <X size={13} />
                  </button>
                </li>
              )
            )}
          </ul>

          {!audio.track && <p className="empty-state">Nothing playing here — tap any track to start.</p>}

          <div className="queue-actions">
            <button type="button" className="pill-btn" onClick={audio.toggleShuffle}>
              <Shuffle size={14} /> {audio.shuffle ? "Shuffle on" : "Shuffle"}
            </button>
            <button
              type="button"
              className="pill-btn"
              onClick={audio.cycleRepeat}
            >
              <RefreshCw size={14} /> Repeat {audio.repeat}
            </button>
            <button
              type="button"
              className="pill-btn danger"
              onClick={audio.clear}
            >
              <Trash2 size={14} /> Clear queue
            </button>
          </div>
        </>
      ) : (
        <>
          <ul className="queue-list">
            {callNow && (
              <li className="q-item playing">
                <span className="idx">▸</span>
                <Cover track={callNow} />
                <div className="info">
                  <b>{callNow.title}</b>
                  <span>
                    {callNow.uploader || "unknown"} · {callNow.paused ? "paused" : "playing"}
                  </span>
                </div>
                <span className="dur">
                  {fmtDuration(callNow.elapsed)} / {fmtDuration(callNow.duration)}
                </span>
                <button type="button" className="mini-action" aria-label="Pause or resume" onClick={() => void act("toggle")}>
                  {callNow.paused ? <Play size={14} /> : <span className="pause-glyph">❚❚</span>}
                </button>
              </li>
            )}

            {callQueue.map((track, index) => (
              <li key={`${track.id ?? track.title}-${index}`} className="q-item">
                <span className="idx">{track.index ?? index + 1}</span>
                <Cover track={track} />
                <div className="info">
                  <b>{track.title}</b>
                  <span>{track.uploader || "unknown"}</span>
                </div>
                <span className="dur">{fmtDuration(track.duration)}</span>
                <button
                  type="button"
                  className="mini-action"
                  aria-label="Play now"
                  onClick={() => void act("jump", track.index ?? index + 1)}
                >
                  <Play size={13} />
                </button>
                <button
                  type="button"
                  className="mini-action"
                  aria-label="Remove"
                  onClick={() => void act("remove", track.index ?? index + 1)}
                >
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>

          {!callQueue.length && !callNow && (
            <p className="empty-state">The queue is empty — search something to add.</p>
          )}

          <div className="queue-actions">
            <button
              type="button"
              className="pill-btn"
              onClick={async () => {
                const payload = await act<{ shuffled?: number }>("shuffle");
                if (payload) toast(`Shuffled ${payload.shuffled ?? 0} tracks`, "success");
              }}
            >
              <Shuffle size={14} /> Shuffle
            </button>
            <button type="button" className="pill-btn" onClick={() => void act("autoplay")}>
              <RefreshCw size={14} /> Toggle autoplay
            </button>
            <button
              type="button"
              className="pill-btn danger"
              onClick={async () => {
                const payload = await act<{ removed?: number }>("clear");
                if (payload) toast(`Cleared ${payload.removed ?? 0} tracks`);
              }}
            >
              <Trash2 size={14} /> Clear queue
            </button>
          </div>
        </>
      )}

      <div className="queue-hint">
        <ListMusic size={15} />
        <span>
          Tap a track to play it on this device. The voice chat keeps its own queue — loop is{" "}
          <b>{settings?.loop ?? "off"}</b>, effects <b>{settings?.effects?.length ? settings.effects.join(", ") : "off"}</b>.
        </span>
      </div>
    </section>
  );
}
