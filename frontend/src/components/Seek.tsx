import { useCallback, useEffect, useRef, useState } from "react";
import { fmtDuration, hashOf } from "../lib/format";

interface Props {
  seed: string;
  position: number;
  duration: number;
  onSeek: (seconds: number) => void;
  playing?: boolean;
}

const BARS = 84;

/** Deterministic waveform: the same track always draws the same shape. */
function peaksFor(seed: string): number[] {
  const hash = hashOf(seed);
  return Array.from({ length: BARS }, (_, index) => {
    const wave = Math.sin((index + (hash % 17)) * 0.42) * 0.34;
    const noise = ((hash >> (index % 24)) & 0xff) / 255 - 0.5;
    const envelope = 0.45 + 0.55 * Math.sin((index / BARS) * Math.PI);
    return Math.max(0.14, Math.min(1, 0.52 + wave + noise * 0.5) * envelope + 0.12);
  });
}

/**
 * Scrub bar drawn as a waveform. Drag, click or use the arrow keys; the played
 * portion is painted and the rest stays dim, so the position reads at a glance.
 */
export function Seek({ seed, position, duration, onSeek, playing = false }: Props) {
  const track = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<number | null>(null);
  const [hover, setHover] = useState<{ x: number; seconds: number } | null>(null);
  const [peaks] = useState(() => peaksFor(seed));
  const value = preview ?? position;
  const percent = duration > 0 ? Math.min(100, Math.max(0, (value / duration) * 100)) : 0;

  const secondsAt = useCallback(
    (clientX: number): number => {
      const node = track.current;
      if (!node || duration <= 0) return 0;
      const rect = node.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
      return ratio * duration;
    },
    [duration]
  );

  /* While dragging we only move the preview: seeking the element on every
     pointermove turns a scrub into a stutter. The commit happens on release. */
  useEffect(() => {
    if (!dragging) return;
    const move = (event: PointerEvent) => {
      const seconds = secondsAt(event.clientX);
      setPreview(seconds);
      setHover({ x: event.clientX, seconds });
    };
    const finish = () => {
      setDragging(false);
      setPreview((current) => {
        if (current !== null) onSeek(current);
        return null;
      });
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", finish);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
    };
  }, [dragging, onSeek, secondsAt]);

  const playedIndex = Math.round((percent / 100) * BARS);

  return (
    <div className="seek">
      <div
        ref={track}
        className={`seek-track ${dragging ? "dragging" : ""}`}
        role="slider"
        tabIndex={0}
        aria-label="Seek"
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(value)}
        aria-valuetext={`${fmtDuration(value)} of ${fmtDuration(duration)}`}
        onPointerDown={(event) => {
          event.preventDefault();
          setDragging(true);
          setPreview(secondsAt(event.clientX));
        }}
        onPointerMove={(event) => {
          const rect = track.current?.getBoundingClientRect();
          if (!rect) return;
          setHover({ x: event.clientX, seconds: secondsAt(event.clientX) });
        }}
        onPointerLeave={() => setHover(null)}
        onKeyDown={(event) => {
          if (event.key === "ArrowRight") onSeek(Math.min(duration, position + 5));
          if (event.key === "ArrowLeft") onSeek(Math.max(0, position - 5));
        }}
      >
        {peaks.map((peak, index) => (
          <span
            key={index}
            className={`seek-bar ${index <= playedIndex ? "on" : ""} ${playing ? "live" : ""}`}
            style={{ height: `${Math.round(peak * 100)}%`, animationDelay: `${(index % 12) * 90}ms` }}
          />
        ))}
        <span className="seek-head" style={{ left: `${percent}%` }} />
      </div>
      <div className="seek-times">
        <span>{fmtDuration(value)}</span>
        {hover && <span className="seek-hover">{fmtDuration(hover.seconds)}</span>}
        <span>{duration > 0 ? fmtDuration(duration) : "live"}</span>
      </div>
    </div>
  );
}
