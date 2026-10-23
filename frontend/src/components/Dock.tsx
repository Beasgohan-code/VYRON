import { ChevronUp, Heart, Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { fmtDuration } from "../lib/format";
import { useApp } from "../lib/store";
import { Cover } from "./Cover";
import { Equalizer } from "./Equalizer";

/** The always-there mini player: artwork, title, transport, a hairline progress. */
export function Dock() {
  const { audio, state, act, cast, toast } = useApp();
  const track = audio.track;
  if (!track) return null;

  const total = audio.duration || track.duration || 0;
  const percent = total ? Math.min(100, (audio.position / total) * 100) : 0;
  const liked = (state?.favorites ?? []).some((item) => item.id === track.id);

  return (
    <div className={`dock ${audio.playing ? "playing" : ""}`}>
      <div className="dock-progress" aria-hidden="true">
        <span style={{ width: `${percent}%` }} />
      </div>

      <button
        type="button"
        className="dock-art"
        onClick={() => audio.setExpanded(true)}
        aria-label="Open full player"
      >
        <Cover track={track} />
        <span className="dock-open">
          <ChevronUp size={14} />
        </span>
      </button>

      <div className="dock-info" onClick={() => audio.setExpanded(true)} role="presentation">
        <b className="dock-title">{track.title}</b>
        <span className={`dock-sub ${audio.error ? "err" : ""}`}>
          {audio.error ? (
            audio.error
          ) : (
            <>
              {audio.playing ? <Equalizer playing bars={3} /> : null}
              {track.uploader || "VYRON"}
              {total ? ` · ${fmtDuration(audio.position)}` : ""}
            </>
          )}
        </span>
      </div>

      <div className="dock-actions">
        <button
          type="button"
          className="btn-icon dock-hide"
          aria-label={liked ? "Remove from liked" : "Like this track"}
          onClick={() => void act(liked ? "unfavorite" : "favorite_track", track)}
        >
          <Heart size={17} fill={liked ? "currentColor" : "none"} />
        </button>
        {audio.error && (
          <button
            type="button"
            className="btn-icon"
            aria-label="Retry playback"
            onClick={() => void audio.play(track)}
          >
            <Play size={17} fill="currentColor" />
          </button>
        )}
        <button type="button" className="btn-icon" aria-label="Previous" onClick={audio.prev}>
          <SkipBack size={18} fill="currentColor" />
        </button>
        <button
          type="button"
          className="dock-play"
          aria-label={audio.playing ? "Pause" : "Play"}
          onClick={audio.toggle}
        >
          {audio.playing ? <Pause size={18} fill="currentColor" /> : <Play size={18} fill="currentColor" />}
        </button>
        <button type="button" className="btn-icon" aria-label="Next" onClick={() => audio.next()}>
          <SkipForward size={18} fill="currentColor" />
        </button>
        <button
          type="button"
          className="btn-icon dock-hide"
          aria-label="Play in the voice chat"
          onClick={() => {
            toast("Sending to the call…");
            void cast(track, "play_now");
          }}
        >
          ⌁
        </button>
      </div>
    </div>
  );
}
