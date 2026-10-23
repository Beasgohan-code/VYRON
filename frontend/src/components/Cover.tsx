import { useState } from "react";
import { hashOf, initials, thumbFor } from "../lib/format";

interface Props {
  track?: { title?: string; id?: string; thumbnail?: string | null } | null;
  className?: string;
  /** Corner radius in px, or any CSS length. */
  rounded?: number | string;
  /** Show the first letter of the title on top of the artwork. */
  monogram?: boolean;
}

/**
 * Album artwork that never fails.
 *
 * A real thumbnail is used when the API has one, but underneath it every cover
 * is a deterministic SVG: four art directions chosen by the track id, with the
 * palette derived from the same hash. No image requests, no broken tiles, and
 * the same track always looks the same.
 */
export function Cover({ track, className = "", rounded, monogram = false }: Props) {
  const [broken, setBroken] = useState(false);
  const seed = hashOf(String(track?.id ?? track?.title ?? "vyron"));
  const src = thumbFor(track);
  const style = seed % 4;
  const hue = seed % 360;
  const hue2 = (hue + 48 + (seed % 60)) % 360;
  const hue3 = (hue + 168) % 360;
  const name = track?.title ?? "VYRON";

  return (
    <span
      className={`cover ${className}`}
      data-art={style}
      style={rounded !== undefined ? { borderRadius: typeof rounded === "number" ? `${rounded}px` : rounded } : undefined}
      aria-hidden="true"
    >
      <svg className="cover-art" viewBox="0 0 100 100" preserveAspectRatio="none" focusable="false">
        <defs>
          <linearGradient id={`g1-${seed}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={`hsl(${hue} 78% 58%)`} />
            <stop offset="1" stopColor={`hsl(${hue2} 72% 42%)`} />
          </linearGradient>
          <radialGradient id={`g2-${seed}`} cx="0.2" cy="0.15" r="0.9">
            <stop offset="0" stopColor={`hsl(${hue3} 84% 62%)`} stopOpacity="0.95" />
            <stop offset="0.55" stopColor={`hsl(${hue2} 70% 40%)`} stopOpacity="0.55" />
            <stop offset="1" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
          <radialGradient id={`g3-${seed}`} cx="0.85" cy="0.9" r="0.75">
            <stop offset="0" stopColor={`hsl(${hue} 90% 68%)`} stopOpacity="0.75" />
            <stop offset="1" stopColor="transparent" stopOpacity="0" />
          </radialGradient>
        </defs>

        <rect width="100" height="100" fill={`hsl(${hue2} 40% 9%)`} />
        <rect width="100" height="100" fill={`url(#g2-${seed})`} />

        {style === 0 && (
          <>
            <circle cx="24" cy="72" r="34" fill={`url(#g1-${seed})`} opacity="0.85" />
            <circle cx="74" cy="30" r="26" fill={`url(#g3-${seed})`} opacity="0.9" />
            <rect y="54" width="100" height="46" fill="#000" opacity="0.22" />
          </>
        )}

        {style === 1 && (
          <>
            <rect width="100" height="100" fill={`url(#g1-${seed})`} opacity="0.55" />
            {[46, 38, 30, 22, 14, 7].map((r, index) => (
              <circle
                key={r}
                cx="62"
                cy="42"
                r={r}
                fill="none"
                stroke={`hsl(${(hue + index * 24) % 360} 95% 78%)`}
                strokeOpacity={0.16 + index * 0.1}
                strokeWidth={index === 0 ? 1.1 : 0.7}
              />
            ))}
            <circle cx="62" cy="42" r="9" fill={`hsl(${hue3} 92% 70%)`} opacity="0.9" />
            <path d="M0 78 L100 58 L100 100 L0 100 Z" fill="#000" opacity="0.3" />
          </>
        )}

        {style === 2 && (
          <>
            <rect width="100" height="100" fill={`url(#g1-${seed})`} opacity="0.6" />
            <g transform="rotate(-24 50 50)">
              {[8, 26, 44, 62, 80, 98].map((x, index) => (
                <rect
                  key={x}
                  x={x}
                  y="-20"
                  width={index % 2 ? 5 : 11}
                  height="140"
                  fill={`hsl(${(hue + index * 40) % 360} 90% ${index % 2 ? 72 : 52}%)`}
                  opacity={index % 2 ? 0.35 : 0.22}
                />
              ))}
            </g>
            <circle cx="78" cy="22" r="13" fill={`hsl(${hue3} 96% 74%)`} opacity="0.85" />
          </>
        )}

        {style === 3 && (
          <>
            <rect width="100" height="100" fill={`url(#g1-${seed})`} opacity="0.35" />
            <g fill={`hsl(${hue3} 92% 78%)`} opacity="0.5">
              {Array.from({ length: 7 }, (_, row) =>
                Array.from({ length: 7 }, (_, column) => (
                  <circle
                    key={`${row}-${column}`}
                    cx={10 + column * 13.5}
                    cy={10 + row * 13.5}
                    r={((row * 7 + column) % 3) * 0.9 + 0.8}
                  />
                ))
              )}
            </g>
            <circle cx="74" cy="74" r="30" fill={`url(#g3-${seed})`} />
            <rect width="100" height="100" fill={`url(#g2-${seed})`} opacity="0.45" />
          </>
        )}

      </svg>

      {src && !broken && (
        <img
          className="cover-img"
          src={src}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setBroken(true)}
        />
      )}

      {monogram && <span className="cover-mono">{initials(name)}</span>}
      <span className="cover-sheen" />
    </span>
  );
}
