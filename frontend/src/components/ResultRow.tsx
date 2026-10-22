import { MoreHorizontal, Play, Plus } from "lucide-react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { Cover } from "./Cover";

interface Props {
  track: Track;
  index?: number;
  onOpenTrack?: (track: Track) => void;
}

export function ResultRow({ track, index }: Props) {
  const { play, openModal } = useApp();
  const query = track.query ?? `${track.title} ${track.uploader ?? ""}`;

  return (
    <li className="result" onClick={() => void play(query, "play_now")}>
      {index !== undefined && <span className="idx">{index}</span>}
      <Cover track={track} />
      <div className="info">
        <b>{track.title}</b>
        <span>
          {track.uploader || track.source || "unknown"}
          {track.duration ? ` · ${fmtDuration(track.duration)}` : ""}
        </span>
      </div>
      <span className="dur">{fmtDuration(track.duration)}</span>
      <div className="acts">
        <button
          type="button"
          className="mini-action play"
          aria-label="Play now"
          onClick={(event) => {
            event.stopPropagation();
            void play(query, "play_now");
          }}
        >
          <Play size={14} fill="currentColor" />
        </button>
        <button
          type="button"
          className="mini-action"
          aria-label="Add to queue"
          onClick={(event) => {
            event.stopPropagation();
            void play(query, "play");
          }}
        >
          <Plus size={14} />
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
