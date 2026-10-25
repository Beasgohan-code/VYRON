/** Tiny animated "now playing" bars — purely decorative, pauses when idle. */
export function Equalizer({ playing = true, bars = 4, className = "" }: { playing?: boolean; bars?: number; className?: string }) {
  return (
    <span className={`eq ${playing ? "playing" : "paused"} ${className}`} aria-hidden="true">
      {Array.from({ length: bars }).map((_, index) => (
        <i key={index} style={{ animationDelay: `${index * 0.14}s` }} />
      ))}
    </span>
  );
}
