import { ListMusic, Play, RefreshCw, Shuffle, Trash2, X } from "lucide-react";
import { Cover } from "../components/Cover";
import { fmtDuration, totalDuration } from "../lib/format";
import { useApp } from "../lib/store";

export function QueueView() {
  const { state, act, toast } = useApp();
  const queue = state?.queue ?? [];
  const now = state?.now;
  const settings = state?.settings;

  return (
    <section className="view active">
      <div className="view-head row-between">
        <div>
          <h1>Queue</h1>
          <p className="muted">
            {queue.length ? `${queue.length} tracks · ${totalDuration(queue)}` : now ? "Nothing queued after this track" : "Nothing queued"}
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

      <ul className="queue-list">
        {now && (
          <li className="q-item playing">
            <span className="idx">▸</span>
            <Cover track={now} />
            <div className="info">
              <b>{now.title}</b>
              <span>
                {now.uploader || "unknown"} · {now.paused ? "paused" : "playing"}
              </span>
            </div>
            <span className="dur">
              {fmtDuration(now.elapsed)} / {fmtDuration(now.duration)}
            </span>
            <button type="button" className="mini-action" aria-label="Pause or resume" onClick={() => void act("toggle")}>
              {now.paused ? <Play size={14} /> : <span className="pause-glyph">❚❚</span>}
            </button>
          </li>
        )}

        {queue.map((track, index) => (
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

      {!queue.length && !now && <p className="empty-state">The queue is empty — search something to add.</p>}

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

      <div className="queue-hint">
        <ListMusic size={15} />
        <span>
          Autoplay pulls a related mix when the queue runs dry. Loop is <b>{settings?.loop ?? "off"}</b>, effects{" "}
          <b>{settings?.effects?.length ? settings.effects.join(", ") : "off"}</b>.
        </span>
      </div>
    </section>
  );
}
