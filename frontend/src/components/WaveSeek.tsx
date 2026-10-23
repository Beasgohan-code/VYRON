import { useEffect, useRef, useState } from "react";
import { fmtDuration, hashOf } from "../lib/format";

interface Props {
  /** Deterministic seed so a track always draws the same waveform. */
  seed: string;
  position: number;
  duration: number;
  playing: boolean;
  onSeek: (seconds: number) => void;
  disabled?: boolean;
}

const BAR_WIDTH = 3;
const GAP = 2;

/**
 * WaveSeek — a real waveform scrubber, drawn on canvas.
 *
 * The peaks are generated from the track id (so the same song always looks the
 * same) and the played part is filled against the live position. Pointer drag,
 * click-to-seek and keyboard seeking all work; the hover cursor shows the time
 * under the pointer before you commit to it.
 */
export function WaveSeek({ seed, position, duration, playing, onSeek, disabled }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ x: number; ratio: number } | null>(null);
  const dragging = useRef(false);
  const peaks = useRef<number[]>([]);

  /* peaks: three octaves of hash noise → a shape that reads as a waveform */
  useEffect(() => {
    const count = 96;
    const base = hashOf(seed || "vyron");
    const values: number[] = [];
    for (let index = 0; index < count; index += 1) {
      const slow = Math.sin((index / count) * Math.PI * 2 + base % 7) * 0.32;
      const mid = Math.sin((index / count) * Math.PI * 9 + (base % 13)) * 0.22;
      const fast = ((Math.sin(index * 12.9898 + base) * 43758.5453) % 1) * 0.5;
      const envelope = Math.sin((index / (count - 1)) * Math.PI) ** 0.55;
      values.push(Math.min(1, Math.max(0.12, (0.55 + Math.abs(slow + mid + fast)) * envelope)));
    }
    peaks.current = values;
  }, [seed]);

  /* draw */
  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return;

    const draw = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = host.clientWidth || 1;
      const height = host.clientHeight || 64;
      if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);

      const values = peaks.current;
      const step = BAR_WIDTH + GAP;
      const bars = Math.max(1, Math.floor(width / step));
      const played = duration > 0 ? Math.min(1, position / duration) : 0;
      const playedBars = Math.floor(bars * played);

      const styles = getComputedStyle(document.documentElement);
      const accent = styles.getPropertyValue("--accent").trim() || "#8b5cf6";
      const accent2 = styles.getPropertyValue("--accent-2").trim() || "#22d3ee";
      const idle = styles.getPropertyValue("--line-hi").trim() || "rgba(255,255,255,.14)";

      for (let index = 0; index < bars; index += 1) {
        const value = values[Math.floor((index / bars) * values.length)] ?? 0.3;
        const barHeight = Math.max(3, value * (height - 10));
        const x = index * step;
        const y = (height - barHeight) / 2;
        const active = index <= playedBars;
        if (active) {
          const gradient = ctx.createLinearGradient(0, y, 0, y + barHeight);
          gradient.addColorStop(0, accent2);
          gradient.addColorStop(1, accent);
          ctx.fillStyle = gradient;
        } else {
          ctx.fillStyle = idle;
        }
        ctx.globalAlpha = active ? 1 : playing ? 0.55 : 0.42;
        ctx.beginPath();
        ctx.roundRect(x, y, BAR_WIDTH, barHeight, BAR_WIDTH / 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // playhead
      if (played > 0 && played < 1) {
        const x = played * width;
        ctx.fillStyle = accent2;
        ctx.fillRect(x - 1, 2, 2, height - 4);
      }
    };

    draw();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(draw) : null;
    observer?.observe(host);
    window.addEventListener("resize", draw);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", draw);
    };
  }, [position, duration, playing]);

  const ratioFrom = (clientX: number): number => {
    const rect = hostRef.current?.getBoundingClientRect();
    if (!rect || !rect.width) return 0;
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  };

  const seekTo = (ratio: number, commit = false) => {
    if (disabled || !duration) return;
    setHover({ x: ratio, ratio });
    if (commit) onSeek(ratio * duration);
  };

  return (
    <div
      ref={hostRef}
      className={`wave-seek ${disabled ? "disabled" : ""}`}
      role="slider"
      tabIndex={0}
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={Math.max(1, Math.round(duration))}
      aria-valuenow={Math.round(position)}
      aria-valuetext={`${fmtDuration(position)} of ${fmtDuration(duration)}`}
      onPointerDown={(event) => {
        dragging.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        const ratio = ratioFrom(event.clientX);
        seekTo(ratio);
        onSeek(ratio * (duration || 0));
      }}
      onPointerMove={(event) => {
        const ratio = ratioFrom(event.clientX);
        seekTo(ratio);
        if (dragging.current) onSeek(ratio * (duration || 0));
      }}
      onPointerUp={(event) => {
        dragging.current = false;
        try {
          event.currentTarget.releasePointerCapture(event.pointerId);
        } catch {
          /* pointer already gone */
        }
      }}
      onPointerLeave={() => {
        dragging.current = false;
        setHover(null);
      }}
      onKeyDown={(event) => {
        if (!duration) return;
        if (event.key === "ArrowRight") onSeek(Math.min(duration, position + 5));
        if (event.key === "ArrowLeft") onSeek(Math.max(0, position - 5));
      }}
    >
      <canvas ref={canvasRef} />
      {hover && (
        <span className="wave-hover" style={{ left: `${hover.ratio * 100}%` }}>
          {fmtDuration(hover.ratio * duration)}
        </span>
      )}
    </div>
  );
}
