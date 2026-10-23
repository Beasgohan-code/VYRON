import { MoreHorizontal, Play, Radio } from "lucide-react";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { Cover } from "./Cover";

interface Props {
  track: Track;
  rank?: number;
  mix?: boolean;
  badge?: string;
  onMixClick?: () => void;
  delay?: number;
}

export function TrackCard({ track, rank, mix, badge, onMixClick, delay = 0 }: Props) {
  const { play, cast, openModal, audio } = useApp();

  return (
    <article
      className={`card-track ${mix ? "card-mix" : ""}`}
      style={{ animationDelay: `${delay}ms` }}
      onClick={onMixClick}
      role={onMixClick ? "button" : undefined}
      tabIndex={onMixClick ? 0 : undefined}
      onKeyDown={(event) => {
        if (onMixClick && (event.key === "Enter" || event.key === " ")) {
          event.preventDefault();
          onMixClick();
        }
      }}
    >
      <div className="cover">
        {rank !== undefined && <span className="rank">{rank}</span>}
        <Cover track={track} />
        {badge && <span className="badge">{badge}</span>}
        <button
          type="button"
          className="hover-play"
          aria-label={`Play ${track.title}`}
          onClick={(event) => {
            event.stopPropagation();
            void play(track, "play_now");
          }}
        >
          {audio.isCurrent(track) && audio.playing ? (
            <span className="pause-glyph">❚❚</span>
          ) : (
            <Play size={16} fill="currentColor" />
          )}
        </button>
        <button
          type="button"
          className="mini-action cast"
          aria-label={`Play ${track.title} in the voice chat`}
          title="Play in the voice chat"
          onClick={(event) => {
            event.stopPropagation();
            void cast(track, "play_now");
          }}
        >
          <Radio size={14} />
        </button>
        <button
          type="button"
          className="mini-action add"
          aria-label="Track options"
          onClick={(event) => {
            event.stopPropagation();
            openModal({ type: "track", track });
          }}
        >
          <MoreHorizontal size={16} />
        </button>
      </div>
      <div className="t">{track.title}</div>
      <div className="s">{track.uploader || track.source || "unknown artist"}</div>
    </article>
  );
}
