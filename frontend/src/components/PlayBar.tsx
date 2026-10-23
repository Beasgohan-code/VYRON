import {
  ListMusic,
  Maximize2,
  Pause,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume1,
  Volume2,
  VolumeX,
} from "lucide-react";
import { useState } from "react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "./Cover";

/** Desktop dock — always-on "now playing" strip, like a music app's footer. */
export function PlayBar() {
  const { audio, setView } = useApp();
  const [draft, setDraft] = useState<number | null>(null);
  const { track } = audio;
  if (!track) return null;

  const total = audio.duration || track.duration || 0;
  const livePercent = total ? Math.min(100, (audio.position / total) * 100) : 0;
  const percent = draft ?? livePercent;
  const VolumeIcon = audio.muted || audio.volume === 0 ? VolumeX : audio.volume < 0.5 ? Volume1 : Volume2;

  return (
    <div className="playbar" role="region" aria-label="Player">
      <button
        type="button"
        className="pb-track"
        onClick={() => audio.setExpanded(true)}
        aria-label="Open full player"
      >
        <Cover track={track} className="pb-cover" />
        <span className="pb-meta">
          <b title={track.title}>{track.title}</b>
          <span>{track.uploader || "unknown artist"}</span>
        </span>
      </button>

      <div className="pb-center">
        <div className="pb-controls">
          <button
            type="button"
            className={`icon-btn ${audio.shuffle ? "on" : ""}`}
            aria-label="Shuffle"
            aria-pressed={audio.shuffle}
            onClick={audio.toggleShuffle}
          >
            <Shuffle size={15} />
          </button>
          <button type="button" className="icon-btn" aria-label="Previous" onClick={audio.prev}>
            <SkipBack size={16} fill="currentColor" />
          </button>
          <button
            type="button"
            className={`round-play ${audio.loading ? "loading" : ""}`}
            aria-label={audio.playing ? "Pause" : "Play"}
            onClick={audio.toggle}
          >
            {audio.playing ? <Pause size={17} fill="currentColor" /> : <Play size={17} fill="currentColor" />}
          </button>
          <button type="button" className="icon-btn" aria-label="Next" onClick={() => audio.next()}>
            <SkipForward size={16} fill="currentColor" />
          </button>
          <button
            type="button"
            className={`icon-btn ${audio.repeat !== "off" ? "on" : ""}`}
            aria-label={`Repeat ${audio.repeat}`}
            aria-pressed={audio.repeat !== "off"}
            onClick={audio.cycleRepeat}
          >
            {audio.repeat === "one" ? <Repeat1 size={15} /> : <Repeat size={15} />}
          </button>
        </div>

        <div className="pb-seek">
          <span className="pb-time">{fmtDuration(audio.position)}</span>
          <input
            type="range"
            min={0}
            max={1000}
            value={Math.round(percent * 10)}
            aria-label="Seek"
            style={{ ["--p" as string]: `${percent}%` }}
            onChange={(event) => setDraft(Number(event.target.value) / 10)}
            onPointerUp={() => {
              if (draft !== null) audio.seek((draft / 100) * total);
              setDraft(null);
            }}
            onKeyUp={() => {
              if (draft !== null) audio.seek((draft / 100) * total);
              setDraft(null);
            }}
          />
          <span className="pb-time">{fmtDuration(total)}</span>
        </div>
      </div>

      <div className="pb-right">
        <button
          type="button"
          className="icon-btn"
          aria-label="Mute"
          onClick={audio.toggleMute}
        >
          <VolumeIcon size={16} />
        </button>
        <input
          className="pb-volume"
          type="range"
          min={0}
          max={100}
          value={Math.round((audio.muted ? 0 : audio.volume) * 100)}
          aria-label="Volume"
          style={{ ["--p" as string]: `${Math.round((audio.muted ? 0 : audio.volume) * 100)}%` }}
          onChange={(event) => audio.setVolume(Number(event.target.value) / 100)}
        />
        <button
          type="button"
          className="icon-btn"
          aria-label="Open queue"
          onClick={() => setView("queue")}
        >
          <ListMusic size={16} />
        </button>
        <button
          type="button"
          className="icon-btn"
          aria-label="Expand player"
          onClick={() => audio.setExpanded(true)}
        >
          <Maximize2 size={15} />
        </button>
      </div>
    </div>
  );
}
