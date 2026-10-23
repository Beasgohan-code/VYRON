import { Music2 } from "lucide-react";
import { useMemo, useState } from "react";
import { hashOf, thumbFor } from "../lib/format";

interface Props {
  track?: { id?: string; title?: string; uploader?: string; thumbnail?: string | null } | null;
  className?: string;
  rounded?: number;
}

/**
 * Artwork, drawn twice over.
 *
 * The thumbnail is the real thing when the network has it. When it does not —
 * Telegram's CDN blocked, an offline phone, a track that has no cover — we draw
 * one instead of shipping a folder of placeholder photos: a deterministic mesh
 * gradient derived from the track, with a soft grain and the artist's initial.
 * Same track always yields the same artwork, and it costs one inline <svg>.
 */
export function Cover({ track, className = "", rounded }: Props) {
  const [source, setSource] = useState<string | null>(() => thumbFor(track));
  const [broken, setBroken] = useState(false);
  const style = rounded === undefined ? undefined : { borderRadius: rounded };

  const art = useMemo(() => procedural(track), [track?.id, track?.title, track?.uploader]);

  if (broken || !source) {
    return (
      <div className={`cover-fallback generated ${className}`} style={{ ...style, ...art.css }} aria-hidden="true">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" className="cover-svg">
          <defs>
            <radialGradient id={art.idA} cx="26%" cy="18%" r="78%">
              <stop offset="0%" stopColor={art.a} stopOpacity="0.95" />
              <stop offset="100%" stopColor={art.a} stopOpacity="0" />
            </radialGradient>
            <radialGradient id={art.idB} cx="82%" cy="78%" r="72%">
              <stop offset="0%" stopColor={art.b} stopOpacity="0.9" />
              <stop offset="100%" stopColor={art.b} stopOpacity="0" />
            </radialGradient>
            <linearGradient id={art.idC} x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#05050a" stopOpacity="0.05" />
              <stop offset="100%" stopColor="#05050a" stopOpacity="0.55" />
            </linearGradient>
          </defs>
          <rect width="100" height="100" fill={art.base} />
          <rect width="100" height="100" fill={`url(#${art.idA})`} />
          <rect width="100" height="100" fill={`url(#${art.idB})`} />
          <path d={art.stroke} fill="none" stroke="rgba(255,255,255,.34)" strokeWidth="0.9" strokeLinecap="round" />
          <rect width="100" height="100" fill={`url(#${art.idC})`} />
        </svg>
        <span className="cover-initial">{art.initial || <Music2 size={16} />}</span>
      </div>
    );
  }

  return (
    <img
      className={className}
      style={style}
      src={source}
      alt=""
      loading="lazy"
      decoding="async"
      draggable={false}
      onError={() => {
        // A broken remote image must not also break the layout: fall back to art.
        setSource(null);
        setBroken(true);
      }}
    />
  );
}

/* ── procedural artwork ───────────────────────────────────────────────────── */
const PALETTES: [string, string, string][] = [
  ["#3b0764", "#7c3aed", "#22d3ee"],
  ["#0c4a6e", "#0891b2", "#a78bfa"],
  ["#4c0519", "#e11d48", "#fb923c"],
  ["#052e16", "#059669", "#a3e635"],
  ["#451a03", "#d97706", "#f472b6"],
  ["#1e1b4b", "#4f46e5", "#38bdf8"],
];

function procedural(track?: Props["track"]) {
  const seed = hashOf(`${track?.id ?? ""}${track?.title ?? ""}${track?.uploader ?? ""}`);
  const [base, a, b] = PALETTES[seed % PALETTES.length];
  const initial = (track?.uploader || track?.title || "?").trim().charAt(0).toUpperCase();
  const id = `c${seed.toString(36)}`;

  // A few smooth arcs, generated from the same seed: looks like a sleeve, is
  // never the same twice, and needs no image request.
  const wobble = (offset: number) => {
    const swing = ((seed >> (offset * 3)) % 40) - 20;
    return `M ${-10 + offset * 6} ${88 - offset * 9}` +
      ` C ${28 + swing} ${44 + offset * 6}, ${64 - swing} ${72 - offset * 5}, ${112} ${12 + offset * 14}`;
  };

  return {
    idA: `${id}-a`,
    idB: `${id}-b`,
    idC: `${id}-c`,
    base,
    a,
    b,
    initial,
    stroke: `${wobble(0)} ${wobble(1)} ${wobble(2)}`,
    css: {
      background: `radial-gradient(120% 90% at 20% 10%, ${a}55, transparent 62%), ${base}`,
    } as React.CSSProperties,
  };
}
