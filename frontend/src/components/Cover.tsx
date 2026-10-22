import { useState } from "react";
import { Music2 } from "lucide-react";
import { coverFor, thumbFor } from "../lib/format";

interface Props {
  track?: { title?: string; uploader?: string; thumbnail?: string | null } | null;
  className?: string;
  rounded?: number;
}

/**
 * Artwork with a graceful two-step fallback: remote thumbnail → procedural
 * cover → icon tile.  Keeps every layout intact offline.
 */
export function Cover({ track, className = "", rounded }: Props) {
  const [source, setSource] = useState(thumbFor(track));
  const [failed, setFailed] = useState(false);
  const style = rounded === undefined ? undefined : { borderRadius: rounded };

  if (failed) {
    return (
      <div className={`cover-fallback ${className}`} style={style} aria-hidden="true">
        <Music2 size={18} />
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
      onError={() => {
        const fallback = coverFor(track);
        if (source !== fallback) {
          setSource(fallback);
        } else {
          setFailed(true);
        }
      }}
    />
  );
}
