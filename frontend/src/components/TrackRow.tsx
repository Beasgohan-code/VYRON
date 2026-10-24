import { ChevronDown, ChevronUp, Heart, MoreHorizontal, Pause, Play, Plus, Radio } from "lucide-react";
import { compact, fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import type { Track } from "../lib/types";
import { Cover } from "./Cover";

interface Props {
  track: Track;
  index?: number;
  /** Show the "add to queue" and "play in the call" buttons on hover. */
  full?: boolean;
  onRemove?: () => void;
  /** Queue reordering — omitted everywhere except the "up next" list. */
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

export function TrackRow({ track, index, full = true, onRemove, onMoveUp, onMoveDown }: Props) {
  const { play, cast, openModal, audio, isLiked, toggleLike } = useApp();
  const current = audio.isCurrent(track);
  const liked = isLiked(track);
  const meta = [
    track.uploader || track.source || "unknown",
    track.duration ? fmtDuration(track.duration) : "",
    track.views ? `${compact(track.views)} plays` : "",
  ].filter(Boolean);

  return (
    <li
      className={`track-row ${current ? "current" : ""} ${current && audio.playing ? "playing" : ""}`}
      role="button"
      tabIndex={0}
      aria-label={`Play ${track.title}`}
      onClick={() => {
        if (current) audio.toggle();
        else void play(track, "play_now");
      }}
      onKeyDown={(event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        if (current) audio.toggle();
        else void play(track, "play_now");
      }}
    >
      {index !== undefined && <span className="tr-index">{current && audio.playing ? "❚❚" : index}</span>}

      <span className="tr-art">
        <Cover track={track} />
        <span className="tr-hover">
          {current && audio.playing ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" />}
        </span>
      </span>

      <span className="tr-main">
        <b className="tr-title">{track.title}</b>
        <span className="tr-sub">{meta.join(" · ")}</span>
      </span>

      <span className="tr-dur">{fmtDuration(track.duration)}</span>

      <span className="tr-actions">
        <button
          type="button"
          className={`btn-icon like ${liked ? "on" : ""}`}
          aria-label={liked ? `Remove ${track.title} from liked songs` : `Like ${track.title}`}
          aria-pressed={liked}
          onClick={(event) => {
            event.stopPropagation();
            void toggleLike(track);
          }}
        >
          <Heart size={15} fill={liked ? "currentColor" : "none"} />
        </button>
        {full && (
          <>
            <button
              type="button"
              className="btn-icon"
              aria-label="Add to queue"
              onClick={(event) => {
                event.stopPropagation();
                void play(track, "play");
              }}
            >
              <Plus size={15} />
            </button>
            <button
              type="button"
              className="btn-icon"
              aria-label="Play in the voice chat"
              onClick={(event) => {
                event.stopPropagation();
                void cast(track, "play_now");
              }}
            >
              <Radio size={15} />
            </button>
          </>
        )}
        <button
          type="button"
          className="btn-icon"
          aria-label="Track options"
          onClick={(event) => {
            event.stopPropagation();
            openModal({ type: "track", track });
          }}
        >
          <MoreHorizontal size={16} />
        </button>
        {onMoveUp && (
          <button
            type="button"
            className="btn-icon reorder"
            aria-label={`Move ${track.title} up`}
            onClick={(event) => {
              event.stopPropagation();
              onMoveUp();
            }}
          >
            <ChevronUp size={15} />
          </button>
        )}
        {onMoveDown && (
          <button
            type="button"
            className="btn-icon reorder"
            aria-label={`Move ${track.title} down`}
            onClick={(event) => {
              event.stopPropagation();
              onMoveDown();
            }}
          >
            <ChevronDown size={15} />
          </button>
        )}
        {onRemove && (
          <button
            type="button"
            className="btn-icon danger"
            aria-label="Remove from queue"
            onClick={(event) => {
              event.stopPropagation();
              onRemove();
            }}
          >
            ×
          </button>
        )}
      </span>
    </li>
  );
}
