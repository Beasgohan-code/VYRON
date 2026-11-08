import { Loader2, Music4 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../lib/api";
import { activeLyricLine } from "../lib/format";

interface Line {
  time: number;
  text: string;
}

interface Props {
  title: string;
  artist: string;
  duration: number;
  /** The room's current second — never the phone's own audio position. */
  position: number;
  playing: boolean;
  /** Jump the *room* to a lyric, if this listener may drive it. */
  onSeek?: (seconds: number) => void;
}

/** How long following pauses after somebody scrolls by hand. */
const YIELD_MS = 4000;
const LEAD = 0.35;

/**
 * The room's lyrics, sung by whoever is listening to it.
 *
 * The clock here is the room's, not this phone's: these lines move because the
 * bot is at 1:42 in the voice chat, so two people looking at their screens see
 * the same word highlighted at the same moment. That is the whole reason this
 * is a component of its own instead of reusing the app player's panel — there
 * the position comes from the local `<audio>` element, and mixing the two would
 * make the lyrics disagree with the call.
 *
 * The scroll follows only while nobody is reading: a manual scroll buys four
 * seconds of peace, then the highlight takes over again. Blank LRC lines (the
 * instrumental gaps) are drawn as short bars instead of a wall of empty rows,
 * which is how a lyric video breathes.
 */
export function RoomLyrics({ title, artist, duration, position, playing, onSeek }: Props) {
  const [lines, setLines] = useState<Line[] | null>(null);
  const [text, setText] = useState("");
  const [failed, setFailed] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const yieldedAt = useRef(0);

  useEffect(() => {
    let alive = true;
    setLines(null);
    setText("");
    setFailed(false);
    if (!title) return;
    api
      .lyrics(title, artist, duration)
      .then((payload) => {
        if (!alive) return;
        setLines(payload.lines ?? []);
        setText(payload.text ?? "");
        setFailed(!(payload.lines?.length || payload.text));
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
    };
  }, [title, artist, duration]);

  const active = useMemo(() => activeLyricLine(lines ?? undefined, position, LEAD), [lines, position]);

  useEffect(() => {
    const node = box.current;
    if (!node || active < 0) return;
    if (Date.now() - yieldedAt.current < YIELD_MS) return;
    const line = node.querySelector<HTMLElement>(`[data-line="${active}"]`);
    if (!line) return;
    // Scroll the *container*, not the page: `scrollIntoView` on a nested scroll
    // box can also move the deck out from under the thumb.
    const top = Math.max(0, line.offsetTop - node.clientHeight / 2 + line.clientHeight / 2);
    try {
      node.scrollTo({ top, behavior: "smooth" });
    } catch {
      // Older Telegram Android webviews only know the (x, y) form — and some
      // environments (jsdom, a few embedded browsers) have no scrollTo at all.
      node.scrollTop = top;
    }
  }, [active]);

  /* Order matters: a failed lookup leaves `lines` null, so checking for the
     spinner first would leave it spinning forever. */
  if (failed) {
    return (
      <div className="lr-lyrics state">
        <Music4 size={18} />
        <span>No lyrics for this one.</span>
        <p>The room keeps playing — this is only the words.</p>
      </div>
    );
  }

  if (lines === null) {
    return (
      <div className="lr-lyrics state">
        <Loader2 className="spin" size={18} />
        <span>Looking for lyrics…</span>
      </div>
    );
  }

  if (!lines.length) {
    /* Plain text (no timings): readable, honest, and not pretending to follow. */
    return (
      <div className="lr-lyrics plain">
        {text.split(/\n{2,}/).map((verse, index) => (
          <p key={index}>{verse}</p>
        ))}
      </div>
    );
  }

  return (
    <div
      className={`lr-lyrics ${playing ? "live" : ""}`}
      ref={box}
      onWheel={() => {
        yieldedAt.current = Date.now();
      }}
      onTouchMove={() => {
        yieldedAt.current = Date.now();
      }}
    >
      <ol>
        {lines.map((line, index) => {
          const blank = !line.text.trim();
          const distance = Math.abs(index - active);
          return (
            <li
              key={`${line.time}-${index}`}
              data-line={index}
              data-active={index === active ? "true" : undefined}
              data-near={distance === 1 ? "true" : undefined}
              className={blank ? "blank" : ""}
              onClick={() => onSeek?.(line.time)}
              role={onSeek ? "button" : undefined}
              tabIndex={onSeek ? 0 : undefined}
              onKeyDown={(event) => {
                if (onSeek && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                  onSeek(line.time);
                }
              }}
            >
              {blank ? <i aria-hidden="true" /> : line.text}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
