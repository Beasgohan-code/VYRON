import {
  AlertTriangle,
  ChevronDown,
  Download,
  Gauge,
  Heart,
  ListMusic,
  Mic2,
  Moon,
  Pause,
  Play,
  Radio,
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
import { Seek } from "../components/Seek";
import { Sparks } from "../components/Sparks";
import { TrackRow } from "../components/TrackRow";
import { reveal, useTilt } from "../lib/anim";
import { api } from "../lib/api";
import { activeLyricLine, fmtDuration, hashOf } from "../lib/format";
import { useApp } from "../lib/store";

interface LyricLine {
  time: number;
  text: string;
}

const SLEEP_STEPS = [0, 15, 30, 60];
const SPEEDS = [0.75, 1, 1.25, 1.5];

export function Player() {
  const { audio, state, cast, act, openModal, toast } = useApp();
  const [lyrics, setLyrics] = useState<{ lines: LyricLine[]; text: string } | null>(null);
  const [showLyrics, setShowLyrics] = useState(false);
  const [showQueue, setShowQueue] = useState(false);
  const [sleepMinutes, setSleepMinutes] = useState(0);
  const [sleepLeft, setSleepLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [visuals, setVisuals] = useState(() => {
    try {
      return localStorage.getItem("vyron:visuals") !== "0";
    } catch {
      return true;
    }
  });
  const lyricsBox = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const art = useTilt<HTMLDivElement>(7);
  const track = audio.track;

  useEffect(() => {
    const root = body.current;
    if (!root) return;
    reveal(root.querySelectorAll(".pv-art, .pv-titles, .pv-seek, .pv-controls, .pv-extra"), {
      y: 24,
      delay: 50,
      duration: 620,
    });
  }, [track?.id]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") audio.setExpanded(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [audio]);

  useEffect(() => {
    setLyrics(null);
    setShowLyrics(false);
  }, [track?.id]);

  /* sleep timer: pause playback after N minutes, then reset */
  useEffect(() => {
    if (!sleepMinutes) {
      setSleepLeft(0);
      return;
    }
    setSleepLeft(sleepMinutes * 60);
    const timer = window.setInterval(() => {
      setSleepLeft((left) => {
        if (left <= 1) {
          window.clearInterval(timer);
          if (audio.playing) audio.toggle();
          setSleepMinutes(0);
          toast("Sleep timer: playback paused", "info");
          return 0;
        }
        return left - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sleepMinutes]);

  if (!track) return null;

  const total = audio.duration || track.duration || 0;
  const VolumeIcon = audio.muted || audio.volume === 0 ? VolumeX : audio.volume < 0.5 ? Volume1 : Volume2;
  const liked = (state?.favorites ?? []).some((item) => item.id === track.id);
  const hue = hashOf(String(track.id ?? track.title ?? "")) % 360;
  const tint = {
    "--pv-glow": `hsl(${hue} 70% 54%)`,
    "--pv-glow-soft": `hsl(${(hue + 46) % 360} 64% 46%)`,
  } as CSSProperties;

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

  const activeLine = activeLyricLine(lyrics?.lines, audio.position);

  /**
   * Follow the song — unless the listener has taken over.
   *
   * Auto-scrolling while somebody is reading a verse is the fastest way to make
   * a lyrics panel unusable, so following pauses for a few seconds after a
   * manual scroll and resumes on its own.
   */
  const followedAt = useRef(0);
  useEffect(() => {
    if (activeLine === undefined || activeLine < 0 || !lyricsBox.current) return;
    if (Date.now() - followedAt.current < 4000) return;
    lyricsBox.current
      .querySelector(`[data-line="${activeLine}"]`)
      ?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeLine]);

  /** Tap a line to jump there — the timings are already known. */
  const seekToLine = (time: number) => {
    followedAt.current = 0;
    audio.seek(time);
  };

  return (
    <div className="player" role="dialog" aria-label="Player" aria-modal="true" style={tint}>
      <div className="pv-glow" aria-hidden="true" />
      <div className="pv-backdrop" aria-hidden="true">
        <Cover track={track} />
      </div>
      {visuals && <Reactor className="pv-reactor" analyser={audio.analyser} playing={audio.playing} size="hero" />}
      <Sparks active={audio.playing} />

      <header className="pv-head">
        <button type="button" className="btn-icon" aria-label="Close player" onClick={() => audio.setExpanded(false)}>
          <ChevronDown size={20} />
        </button>
        <span className="pv-context">
          playing in the app<i>{audio.queue.length} in queue</i>
        </span>
        <div className="pv-head-actions">
          <button
            type="button"
            className={`btn-icon ${visuals ? "on" : ""}`}
            aria-label="Toggle visualiser"
            aria-pressed={visuals}
            onClick={() => {
              setVisuals((value) => {
                try {
                  localStorage.setItem("vyron:visuals", value ? "0" : "1");
                } catch {
                  /* private mode */
                }
                return !value;
              });
            }}
          >
            <Wand2 size={17} />
          </button>
          <button
            type="button"
            className={`btn-icon ${showLyrics ? "on" : ""}`}
            aria-label="Toggle lyrics"
            aria-busy={busy}
            onClick={() => void loadLyrics()}
          >
            <Mic2 size={18} />
          </button>
          <button
            type="button"
            className={`btn-icon ${showQueue ? "on" : ""}`}
            aria-label="Toggle queue"
            onClick={() => {
              setShowQueue((value) => !value);
              setShowLyrics(false);
            }}
          >
            <ListMusic size={18} />
          </button>
        </div>
      </header>

      <div className="pv-body" ref={body}>
        <div className="pv-left">
          <div className="pv-art" ref={art}>
            <Cover track={track} className="pv-cover" monogram />
            {audio.loading && <span className="pv-spinner" aria-hidden="true" />}
          </div>

          <div className="pv-titles">
            <h1>{track.title}</h1>
            <p>
              {audio.playing ? <Equalizer playing bars={4} /> : null}
              {track.uploader || "unknown artist"}
            </p>
          </div>

          {audio.error && (
            <div className="pv-alert" role="status">
              <AlertTriangle size={15} />
              <span>{audio.error}</span>
              <button type="button" className="btn btn-primary sm" onClick={() => void audio.play(track)}>
                <Play size={13} fill="currentColor" /> Retry
              </button>
            </div>
          )}

          <div className="pv-seek">
            <Seek
              seed={String(track.id ?? track.title ?? "")}
              position={audio.position}
              duration={total}
              playing={audio.playing}
              onSeek={(seconds) => audio.seek(seconds)}
            />
          </div>

          <div className="pv-controls">
            <button
              type="button"
              className={`btn-icon ${audio.shuffle ? "on" : ""}`}
              aria-label="Shuffle"
              aria-pressed={audio.shuffle}
              onClick={audio.toggleShuffle}
            >
              <Shuffle size={19} />
            </button>
            <button type="button" className="btn-icon" aria-label="Previous" onClick={audio.prev}>
              <SkipBack size={22} fill="currentColor" />
            </button>
            <button
              type="button"
              className="play-fab"
              aria-label={audio.playing ? "Pause" : "Play"}
              onClick={audio.toggle}
            >
              {audio.playing ? <Pause size={26} fill="currentColor" /> : <Play size={26} fill="currentColor" />}
            </button>
            <button type="button" className="btn-icon" aria-label="Next" onClick={() => audio.next()}>
              <SkipForward size={22} fill="currentColor" />
            </button>
            <button
              type="button"
              className={`btn-icon ${audio.repeat !== "off" ? "on" : ""}`}
              aria-label={`Repeat ${audio.repeat}`}
              onClick={audio.cycleRepeat}
            >
              {audio.repeat === "one" ? <Repeat1 size={19} /> : <Repeat size={19} />}
            </button>
          </div>

          <div className="pv-extra">
            <button
              type="button"
              className={`btn-icon ${liked ? "on liked" : ""}`}
              aria-label="Like"
              onClick={() => void act(liked ? "unfavorite" : "favorite_track", track)}
            >
              <Heart size={18} fill={liked ? "currentColor" : "none"} />
            </button>
            <button type="button" className="btn-icon" aria-label="Download" onClick={() => openModal({ type: "download", query: track.query ?? track.title })}>
              <Download size={18} />
            </button>
            <button
              type="button"
              className="btn-icon"
              aria-label="Play in the voice chat"
              onClick={() => {
                toast("Sending to the call…");
                void cast(track, "play_now");
              }}
            >
              <Radio size={18} />
            </button>
            <div className="volume">
              <button
                type="button"
                className="btn-icon"
                aria-label="Mute"
                onClick={audio.toggleMute}
              >
                <VolumeIcon size={18} />
              </button>
              <input
                type="range"
                min={0}
                max={1}
                step={0.01}
                value={audio.muted ? 0 : audio.volume}
                aria-label="Volume"
                onChange={(event) => audio.setVolume(Number(event.target.value))}
              />
            </div>
          </div>

          <div className="sleep">
            <Moon size={14} />
            <span>sleep</span>
            {SLEEP_STEPS.map((step) => (
              <button
                key={step}
                type="button"
                className={`chip tiny ${sleepMinutes === step ? "active" : ""}`}
                onClick={() => setSleepMinutes(step)}
              >
                {step === 0 ? "off" : `${step}m`}
              </button>
            ))}
            {sleepLeft > 0 && <b className="sleep-left">{fmtDuration(sleepLeft)}</b>}
          </div>

          <div className="sleep">
            <Gauge size={14} />
            <span>speed</span>
            {SPEEDS.map((speed) => (
              <button
                key={speed}
                type="button"
                className={`chip tiny ${Math.abs(audio.rate - speed) < 0.01 ? "active" : ""}`}
                onClick={() => audio.setRate(speed)}
              >
                {speed}×
              </button>
            ))}
          </div>
        </div>

        {(showLyrics || showQueue) && (
          <aside className="pv-side">
            {showLyrics && (
              <div
                className="lyrics"
                ref={lyricsBox}
                onScroll={() => {
                  followedAt.current = Date.now();
                }}
              >
                {lyrics?.lines.length ? (
                  lyrics.lines.map((line, index) => (
                    <button
                      type="button"
                      key={`${line.time}-${index}`}
                      data-line={index}
                      className={`lyric-line ${index === activeLine ? "on" : ""} ${
                        activeLine !== undefined && index < activeLine ? "past" : ""
                      }`}
                      aria-current={index === activeLine ? "true" : undefined}
                      onClick={() => seekToLine(line.time)}
                      title={`Jump to ${Math.floor(line.time / 60)}:${String(Math.floor(line.time % 60)).padStart(2, "0")}`}
                    >
                      {line.text}
                    </button>
                  ))
                ) : (
                  <pre className="lyrics-plain">{lyrics?.text || "No lyrics for this one."}</pre>
                )}
              </div>
            )}
            {showQueue && (
              <>
                <header className="section-head">
                  <h2>Up next</h2>
                  <span className="fine">{audio.queue.length} tracks</span>
                </header>
                <ul className="rows">
                  {audio.queue.map((item, index) => (
                    <TrackRow
                      key={`${item.id ?? item.title}-${index}`}
                      track={item}
                      index={index + 1}
                      full={false}
                      onRemove={() => audio.removeAt(index)}
                    />
                  ))}
                  {audio.queue.length === 0 && <li className="fine">Queue is empty — add something from Search.</li>}
                </ul>
              </>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}
