/**
 * "Where was I?" — the playback session, saved locally.
 *
 * A Mini App is killed every time the user leaves the chat, so without this the
 * queue dies with the tab: you come back, and the song you were three minutes
 * into is simply gone. The session is written a few seconds apart (never on
 * every tick) and restored *paused* — resuming audio without a tap is exactly
 * the sort of thing mobile browsers block, and being blocked looks broken.
 */
import type { Track } from "./types";
import type { Repeat } from "./queueops";

export const SESSION_KEY = "vyron:session";
export const SESSION_VERSION = 2;
/** A month-old session is a stranger; do not offer to continue it. */
const MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;

export interface SavedSession {
  version: number;
  queue: Track[];
  /** Index of the track that was playing. */
  index: number;
  /** Seconds into that track. */
  position: number;
  rate: number;
  volume: number;
  muted: boolean;
  repeat: Repeat;
  shuffle: boolean;
  /** When it was written, ms since epoch. */
  savedAt: number;
}

export interface SessionInput {
  queue: Track[];
  track?: Track | null;
  position?: number;
  rate?: number;
  volume?: number;
  muted?: boolean;
  repeat?: Repeat;
  shuffle?: boolean;
}

const clean = (value: unknown): Track | null => {
  if (!value || typeof value !== "object") return null;
  const track = value as Track;
  const id = typeof track.id === "string" || typeof track.id === "number" ? String(track.id) : "";
  const title = typeof track.title === "string" ? track.title : "";
  if (!id || !title) return null;
  return {
    ...track,
    id,
    title,
    duration: Number.isFinite(Number(track.duration)) ? Math.max(0, Number(track.duration)) : 0,
    uploader: typeof track.uploader === "string" ? track.uploader : "",
    thumbnail: typeof track.thumbnail === "string" ? track.thumbnail : null,
  };
};

/** Build a session document from live engine state. */
export function buildSession(input: SessionInput, now: number = Date.now()): SavedSession | null {
  const queue = (input.queue ?? []).map(clean).filter((track): track is Track => Boolean(track));
  if (!queue.length) return null;
  const identity = String(input.track?.id ?? input.track?.title ?? "");
  const found = identity ? queue.findIndex((track) => String(track.id ?? track.title) === identity) : -1;
  const index = found >= 0 ? found : 0;
  const duration = Number(queue[index]?.duration) || 0;
  const position = Math.max(0, Math.min(Number(input.position) || 0, duration || Number.MAX_SAFE_INTEGER));
  const rate = Number(input.rate);
  return {
    version: SESSION_VERSION,
    queue,
    index,
    position,
    rate: Number.isFinite(rate) && rate >= 0.5 && rate <= 2 ? rate : 1,
    volume: Math.min(1, Math.max(0, Number.isFinite(Number(input.volume)) ? Number(input.volume) : 0.9)),
    muted: Boolean(input.muted),
    repeat: input.repeat === "one" || input.repeat === "all" ? input.repeat : "off",
    shuffle: Boolean(input.shuffle),
    savedAt: now,
  };
}

/** Validate and repair whatever is in storage. Anything suspicious is dropped. */
export function parseSession(raw: string | null, now: number = Date.now()): SavedSession | null {
  if (!raw) return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!data || typeof data !== "object") return null;
  const record = data as Partial<SavedSession>;
  if (record.version !== SESSION_VERSION) return null;
  const queue = Array.isArray(record.queue)
    ? record.queue.map(clean).filter((track): track is Track => Boolean(track))
    : [];
  if (!queue.length) return null;
  const savedAt = Number(record.savedAt) || 0;
  if (!savedAt || now - savedAt > MAX_AGE_MS) return null;

  const index = Math.min(queue.length - 1, Math.max(0, Math.floor(Number(record.index) || 0)));
  const duration = Number(queue[index]?.duration) || 0;
  const position = Math.max(0, Math.min(Number(record.position) || 0, duration || Number.MAX_SAFE_INTEGER));
  const rate = Number(record.rate);
  return {
    version: SESSION_VERSION,
    queue,
    index,
    position,
    rate: Number.isFinite(rate) && rate >= 0.5 && rate <= 2 ? rate : 1,
    volume: Math.min(1, Math.max(0, Number.isFinite(Number(record.volume)) ? Number(record.volume) : 0.9)),
    muted: Boolean(record.muted),
    repeat: record.repeat === "one" || record.repeat === "all" ? record.repeat : "off",
    shuffle: Boolean(record.shuffle),
    savedAt,
  };
}

export function readSession(storage?: Pick<Storage, "getItem"> | null): SavedSession | null {
  try {
    const store = storage ?? (typeof localStorage === "undefined" ? null : localStorage);
    if (!store) return null;
    return parseSession(store.getItem(SESSION_KEY));
  } catch {
    return null;
  }
}

export function writeSession(session: SavedSession, storage?: Pick<Storage, "setItem"> | null): void {
  try {
    const store = storage ?? (typeof localStorage === "undefined" ? null : localStorage);
    store?.setItem(SESSION_KEY, JSON.stringify(session));
  } catch {
    /* private mode, quota — a lost session is not worth an error dialog */
  }
}

export function clearSession(storage?: Pick<Storage, "removeItem"> | null): void {
  try {
    const store = storage ?? (typeof localStorage === "undefined" ? null : localStorage);
    store?.removeItem(SESSION_KEY);
  } catch {
    /* ignore */
  }
}

/** "3 of 12 · 2:31" — the one line the Continue card needs. */
export function describeSession(session: SavedSession): string {
  const position = Math.max(0, Math.floor(session.position));
  const minutes = Math.floor(position / 60);
  const seconds = position % 60;
  const clock = `${minutes}:${String(seconds).padStart(2, "0")}`;
  return `${session.index + 1} of ${session.queue.length} · ${clock} in`;
}

/** The next track after the saved one, or `undefined` at the end of the queue. */
export function upNext(session: SavedSession): Track | undefined {
  return session.queue[session.index + 1];
}
