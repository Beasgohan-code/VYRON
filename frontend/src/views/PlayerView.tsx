import {
  AlertTriangle,
  ChevronDown,
  Heart,
  ListMusic,
  Mic2,
  Radio,
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
  Wand2,
} from "lucide-react";
import { useEffect, useRef, useState, type CSSProperties } from "react";
import { Cover } from "../components/Cover";
import { Equalizer } from "../components/Equalizer";
import { Reactor } from "../components/Reactor";
import { WaveSeek } from "../components/WaveSeek";
import { Sparks } from "../components/Sparks";
import { reveal, useTilt } from "../lib/anim";
import { api } from "../lib/api";
import { fmtDuration, hashOf } from "../lib/format";
import { useApp } from "../lib/store";

interface LyricLine {
  time: number;
  text: string;
}

/** Full-screen, Spotify-style player with a live lyrics panel. */
export function PlayerView() {
  const { audio, state, cast, openModal, toast } = useApp();
  const [lyrics, setLyrics] = useState<{ lines: LyricLine[]; text: string } | null>(null);
  const [showLyrics, setShowLyrics] = useState(false);
  const [busy, setBusy] = useState(false);
  const [visuals, setVisuals] = useState(() => {
    try {
      return localStorage.getItem("vyron:visuals") !== "0";
    } catch {
      return true;
    }
  });
  const lyricsBox = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const artRef = useTilt<HTMLDivElement>(8);
  const track = audio.track;

  /* entrance: the artwork and controls rise into place */
  useEffect(() => {
    const root = bodyRef.current;
    if (!root) return;
    reveal(root.querySelectorAll(".pv-art, .pv-titles, .pv-seek, .pv-controls, .pv-secondary, .pv-side"), {
      y: 26,
      delay: 55,
      duration: 640,
    });
  }, [track?.id]);

  const toggleVisuals = () => {
    setVisuals((value) => {
      try {
        localStorage.setItem("vyron:visuals", value ? "0" : "1");
      } catch {
        /* private mode */
      }
      return !value;
    });
  };

  useEffect(() => {
    setLyrics(null);
    setShowLyrics(false);
  }, [track?.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") audio.setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [audio]);

  if (!track) return null;

  const total = audio.duration || track.duration || 0;
  const percent = total ? Math.min(100, (audio.position / total) * 100) : 0;
  const VolumeIcon = audio.muted || audio.volume === 0 ? VolumeX : audio.volume < 0.5 ? Volume1 : Volume2;
  const liked = (state?.favorites ?? []).some((item) => item.id === track.id);

  const loadLyrics = async () => {
    if (lyrics) {
      setShowLyrics((value) => !value);
      return;
    }
    setBusy(true);
    try {
      const payload = await api.lyrics(track.title, track.uploader ?? "", track.duration ?? 0);
      setLyrics({ lines: payload.lines ?? [], text: payload.text ?? "" });
      setShowLyrics(true);
    } catch {
      toast("No lyrics found for this track", "error");
    } finally {
      setBusy(false);
    }
  };

  /* keep the current lyric line in view */
  const activeLine = lyrics?.lines.reduce(
    (best, line, index) => (line.time <= audio.position + 0.4 ? index : best),
    -1
  );

  useEffect(() => {
    if (activeLine === undefined || activeLine < 0 || !lyricsBox.current) return;
    const node = lyricsBox.current.querySelector(`[data-line="${activeLine}"]`);
    node?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeLine]);

  // Every track gets its own ambient tint, derived from its id — no pixel
  // reads from the artwork (those are CORS-blocked), no network, no flicker.
  const hue = hashOf(String(track.id ?? track.title ?? "")) % 360;
  const tint = {
    "--pv-glow": `hsl(${hue} 68% 52%)`,
    "--pv-glow-soft": `hsl(${(hue + 42) % 360} 62% 46%)`,
  } as CSSProperties;

  return (
    <div className="player-view" role="dialog" aria-label="Player" aria-modal="true" style={tint}>
      <div className="pv-backdrop">
        <Cover track={track} />
      </div>
      {visuals && (
        <Reactor className="pv-reactor" analyser={audio.analyser} playing={audio.playing} size="hero" />
      )}
      <Sparks active={audio.playing} />

      <header className="pv-head">
        <button type="button" className="icon-btn" aria-label="Close player" onClick={() => audio.setExpanded(false)}>
          <ChevronDown size={20} />
        </button>
        <span className="pv-context">
          Playing in the app
          <i>{audio.queue.length} in queue</i>
        </span>
        <div className="pv-head-actions">
          <button
            type="button"
            className={`icon-btn ${visuals ? "on" : ""}`}
            aria-label="Toggle visualiser"
            aria-pressed={visuals}
            onClick={toggleVisuals}
          >
            <Wand2 size={17} />
          </button>
          <button
            type="button"
            className="icon-btn"
            aria-label="Toggle lyrics"
            onClick={() => void loadLyrics()}
          >
            <Mic2 size={18} />
          </button>
        </div>
      </header>

      <div className="pv-body" ref={bodyRef}>
        <div className="pv-art" ref={artRef}>
          <div
            className="pv-art-ring"
            style={{ "--p": `${Math.min(100, Math.max(0, percent))}%` } as CSSProperties}
          >
            <Cover track={track} className="pv-cover" />
          </div>
          {audio.loading && <span className="pv-spinner" aria-hidden="true" />}
        </div>

        <div className="pv-details">
          <div className="pv-titles">
            <h1>{track.title}</h1>
            <p>
              <Equalizer playing={audio.playing} bars={4} /> {track.uploader || "unknown artist"}
            </p>
          </div>

          {audio.error && (
            <div className="pv-alert" role="status">
              <AlertTriangle size={15} />
              <span>{audio.error}</span>
              <button
                type="button"
                className="pill-btn accent"
                onClick={() => void audio.play(track)}
              >
                <Play size={13} fill="currentColor" /> Retry
              </button>
            </div>
          )}

          {audio.loading && !audio.error && (
            <div className="pv-buffering" role="status" aria-live="polite">
              <span className="pv-buffering-dot" /> buffering audio…
            </div>
          )}

          <div className="pv-seek">
            <WaveSeek
              seed={String(track.id ?? track.title ?? "")}
              position={audio.position}
              duration={total}
              playing={audio.playing}
              onSeek={(seconds) => audio.seek(seconds)}
            />
            <div className="pv-times">
              <span>{fmtDuration(audio.position)}</span>
              <span>{total ? fmtDuration(total) : "live"}</span>
            </div>
          </div>

          <div className="pv-controls">
            <button
              type="button"
              className={`icon-btn ${audio.shuffle ? "on" : ""}`}
              aria-label="Shuffle"
              aria-pressed={audio.shuffle}
              onClick={audio.toggleShuffle}
            >
              <Shuffle size={19} />
            </button>
            <button type="button" className="icon-btn" aria-label="Previous" onClick={audio.prev}>
              <SkipBack size={22} fill="currentColor" />
            </button>
            <button
              type="button"
              className="round-play xl"
              aria-label={audio.playing ? "Pause" : "Play"}
              onClick={audio.toggle}
            >
              {audio.playing ? <Pause size={26} fill="currentColor" /> : <Play size={26} fill="currentColor" />}
            </button>
            <button type="button" className="icon-btn" aria-label="Next" onClick={() => audio.next()}>
              <SkipForward size={22} fill="currentColor" />
            </button>
            <button
              type="button"
              className={`icon-btn ${audio.repeat !== "off" ? "on" : ""}`}
              aria-label={`Repeat ${audio.repeat}`}
              onClick={audio.cycleRepeat}
            >
              {audio.repeat === "one" ? <Repeat1 size={19} /> : <Repeat size={19} />}
            </button>
          </div>

          <div className="pv-secondary">
            <button
              type="button"
              className={`chip ${liked ? "on" : ""}`}
              onClick={async () => {
                try {
                  await api.action(
                    liked ? "unfavorite" : "favorite_track",
                    liked
                      ? String(track.id ?? "")
                      : {
                          id: track.id,
                          title: track.title,
                          uploader: track.uploader,
                          duration: track.duration,
                          thumbnail: track.thumbnail,
                        }
                  );
                  toast(liked ? "Removed from favourites" : "Saved to favourites", "success");
                } catch {
                  toast("Could not update favourites", "error");
                }
              }}
            >
              <Heart size={15} fill={liked ? "currentColor" : "none"} />
              {liked ? "Saved" : "Save"}
            </button>
            <button type="button" className="chip" onClick={() => openModal({ type: "add-to-playlist", track })}>
              <ListMusic size={15} />
              Playlist
            </button>
            <button
              type="button"
              className="chip"
              onClick={() => void cast(track, "play_now").then(() => toast("Sent to the voice chat", "success"))}
            >
              <Radio size={15} />
              Voice chat
            </button>
            <label className="pv-volume">
              <VolumeIcon size={16} />
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((audio.muted ? 0 : audio.volume) * 100)}
                aria-label="Volume"
                style={{ ["--p" as string]: `${Math.round((audio.muted ? 0 : audio.volume) * 100)}%` }}
                onChange={(event) => audio.setVolume(Number(event.target.value) / 100)}
              />
            </label>
          </div>
        </div>

        <aside className="pv-side">
          {showLyrics ? (
            <>
              <div className="pv-side-head">
                <h3>Lyrics</h3>
                <button type="button" className="link-btn" onClick={() => setShowLyrics(false)}>
                  Queue
                </button>
              </div>
              <div className="pv-lyrics" ref={lyricsBox}>
                {lyrics?.lines.length ? (
                  lyrics.lines.map((line, index) => (
                    <p
                      key={`${line.time}-${index}`}
                      data-line={index}
                      className={index === activeLine ? "active" : ""}
                    >
                      {line.text}
                    </p>
                  ))
                ) : (
                  <pre className="pv-plain">{lyrics?.text || (busy ? "Looking…" : "No lyrics")}</pre>
                )}
              </div>
            </>
          ) : (
            <>
              <div className="pv-side-head">
                <h3>Up next</h3>
                <button type="button" className="link-btn" onClick={() => void loadLyrics()}>
                  {busy ? "…" : "Lyrics"}
                </button>
              </div>
              <ul className="pv-queue">
                {audio.queue.map((item, index) => {
                  const current = audio.isCurrent(item);
                  return (
                    <li key={`${item.id ?? item.title}-${index}`} className={current ? "current" : ""}>
                      <button type="button" className="pv-q-main" onClick={() => audio.jumpTo(index)}>
                        <Cover track={item} />
                        <span>
                          <b>{item.title}</b>
                          <i>{item.uploader || "unknown"}</i>
                        </span>
                      </button>
                      <span className="pv-q-dur">{fmtDuration(item.duration)}</span>
                    </li>
                  );
                })}
                {!audio.queue.length && <li className="pv-empty">Nothing queued yet</li>}
              </ul>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
