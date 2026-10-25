import { Play } from "lucide-react";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { Cover } from "./Cover";

interface Props {
  track: Track;
  badge?: string;
  onPlay?: () => void;
  rank?: number;
  wide?: boolean;
}

/** Artwork-forward card: the artwork is the button, the caption is the label. */
export function Tile({ track, badge, onPlay, rank, wide }: Props) {
  const { play, audio } = useApp();
  const current = audio.isCurrent(track);

  return (
    <button
      type="button"
      className={`tile ${wide ? "tile-wide" : ""} ${current ? "current" : ""}`}
      onClick={() => {
        if (onPlay) onPlay();
        else if (current) audio.toggle();
        else void play(track, "play_now");
      }}
      aria-label={`Play ${track.title}`}
    >
      <span className="tile-art">
        <Cover track={track} />
        {rank !== undefined && <span className="tile-rank">{rank}</span>}
        {badge && <span className="tile-badge">{badge}</span>}
        <span className="tile-play">
          <Play size={17} fill="currentColor" />
        </span>
      </span>
      <span className="tile-text">
        <b>{track.title}</b>
        <span>{track.uploader || track.source || "VYRON"}</span>
      </span>
    </button>
  );
}
