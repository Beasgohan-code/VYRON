import { MoreHorizontal, Play, Plus, Radio } from "lucide-react";
import { compact, fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { Cover } from "./Cover";

interface Props {
  track: Track;
  index?: number;
  onOpenTrack?: (track: Track) => void;
}

export function ResultRow({ track, index }: Props) {
  const { play, cast, openModal, audio } = useApp();
  const current = audio.isCurrent(track);
  const meta = [
    track.uploader || track.source || "unknown",
    track.duration ? fmtDuration(track.duration) : "",
    track.views ? `${compact(track.views)} plays` : "",
  ].filter(Boolean);

  return (
    <li
      className={`result ${current ? "current" : ""} ${current && audio.playing ? "playing" : ""}`}
      onClick={() => void play(track, "play_now")}
    >
      {index !== undefined && <span className="idx">{current && audio.playing ? "▸" : index}</span>}
      <span className="result-art">
        <Cover track={track} />
        <span className="result-art-play" aria-hidden="true">
          <Play size={16} fill="currentColor" />
        </span>
      </span>
      <div className="info">
        <b>{track.title}</b>
        <span>{meta.join(" · ")}</span>
      </div>
      <span className="dur">{fmtDuration(track.duration)}</span>
      <div className="acts">
        <button
          type="button"
          className="mini-action play"
          aria-label="Play now"
          onClick={(event) => {
            event.stopPropagation();
            void play(track, "play_now");
          }}
        >
          {audio.isCurrent(track) && audio.playing ? (
            <span className="pause-glyph">❚❚</span>
          ) : (
            <Play size={14} fill="currentColor" />
          )}
        </button>
        <button
          type="button"
          className="mini-action"
          aria-label="Add to queue"
          onClick={(event) => {
            event.stopPropagation();
            void play(track, "play");
          }}
        >
          <Plus size={14} />
        </button>
        <button
          type="button"
          className="mini-action cast"
          aria-label="Play in the voice chat"
          onClick={(event) => {
            event.stopPropagation();
            void cast(track, "play_now");
          }}
        >
          <Radio size={14} />
        </button>
        <button
          type="button"
          className="mini-action"
          aria-label="Track options"
          onClick={(event) => {
            event.stopPropagation();
            openModal({ type: "track", track });
          }}
        >
          <MoreHorizontal size={14} />
        </button>
      </div>
    </li>
  );
}
