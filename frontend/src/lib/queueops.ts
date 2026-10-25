/**
 * Queue arithmetic — the small, boring, testable half of playback.
 *
 * The audio engine used to do all of this inline: find the current index, pick
 * the next one, splice a "play next" in. Every one of those is a pure function
 * of a list, so they live here where they can be tested without an <audio>
 * element, a DOM or a React render.
 */
import type { Track } from "./types";

export type Repeat = "off" | "one" | "all";

/** The identity of a track inside a queue. */
export function keyOf(track?: Track | null): string {
  if (!track) return "";
  return String(track.id ?? track.title ?? "");
}

export function indexOf(queue: Track[], track?: Track | null): number {
  const key = keyOf(track);
  if (!key) return -1;
  return queue.findIndex((item) => keyOf(item) === key);
}

/** Add a track unless it is already queued, optionally right after the current one. */
export function enqueue(queue: Track[], track: Track, options: { next?: boolean; current?: Track | null } = {}): Track[] {
  if (!keyOf(track)) return queue;
  if (indexOf(queue, track) >= 0) return queue;
  if (!options.next) return [...queue, track];
  const current = indexOf(queue, options.current);
  const copy = [...queue];
  copy.splice(current < 0 ? copy.length : current + 1, 0, track);
  return copy;
}

export function removeAt(queue: Track[], index: number): Track[] {
  if (index < 0 || index >= queue.length) return queue;
  return queue.filter((_, position) => position !== index);
}

/** Move the item at `from` so that it sits at `to`. Out-of-range moves are a no-op. */
export function move(queue: Track[], from: number, to: number): Track[] {
  if (from === to) return queue;
  if (from < 0 || to < 0 || from >= queue.length || to >= queue.length) return queue;
  const copy = [...queue];
  const [item] = copy.splice(from, 1);
  copy.splice(to, 0, item);
  return copy;
}

/**
 * Which track plays next.
 *
 * Returns `"repeat"` when the current track should simply start again, the
 * index to jump to, or `null` when the queue is finished — the caller decides
 * what "finished" means for the UI.
 */
export function nextIndex(
  queue: Track[],
  current: Track | null | undefined,
  options: { repeat?: Repeat; shuffle?: boolean; rng?: () => number } = {}
): number | "repeat" | null {
  if (!queue.length) return null;
  const { repeat = "off", shuffle = false, rng = Math.random } = options;

  if (repeat === "one" && current) return "repeat";

  const index = indexOf(queue, current);
  if (shuffle) {
    const pool = queue.map((_, position) => position).filter((position) => position !== index);
    if (!pool.length) return index;
    return pool[Math.min(pool.length - 1, Math.floor(rng() * pool.length))];
  }

  const following = index + 1;
  if (following < queue.length) return following;
  if (repeat === "all") return 0;
  return null;
}

/** Shuffle in place for a "shuffle" button: current track stays first. */
export function shuffled(queue: Track[], current?: Track | null, rng: () => number = Math.random): Track[] {
  const rest = queue.filter((item) => keyOf(item) !== keyOf(current));
  for (let index = rest.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(rng() * (index + 1));
    [rest[index], rest[swap]] = [rest[swap], rest[index]];
  }
  const head = queue.find((item) => keyOf(item) === keyOf(current));
  return head ? [head, ...rest] : rest;
}

/** Total runtime of a queue, in seconds. */
export function totalDuration(queue: Track[]): number {
  return queue.reduce((sum, track) => sum + Math.max(0, Number(track.duration) || 0), 0);
}
