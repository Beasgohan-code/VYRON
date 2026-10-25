/**
 * Your face, in the app.
 *
 * Telegram gives the Mini App a name but not the picture: `initData.user`
 * carries a signed `photo_url`, and a browser session (owner token) has no
 * picture at all. So the picture comes from `/api/avatar`, fetched with the
 * same headers as every other call — never a credential in an `<img src>`,
 * never a third-party request from the webview.
 *
 * A Mini App is killed every time the user leaves the chat, so the last
 * picture is kept as a data URL. Reopening paints the real face immediately
 * instead of a grey circle that fills in a second later — and it still works
 * with no network at all.
 */
import { ownerToken, telegram, token } from "./api";

export const AVATAR_KEY = "vyron:avatar";
/** How long a stored picture is trusted before the app insists on a fresh one. */
const KEEP_MS = 30 * 24 * 60 * 60 * 1000;
/** Do not ask the server twice in a row for the same face. */
const REFRESH_MS = 5 * 60 * 1000;
/** base64 is a third larger than the bytes; a userpic never needs to be. */
const MAX_STORED = 400_000;

interface Stored {
  seed: string;
  data: string;
  at: number;
}

const memory = new Map<string, string>();
const asked = new Map<string, number>();
const inFlight = new Map<string, Promise<string | null>>();

/**
 * What identifies this picture.
 *
 * The Telegram `photo_url` changes whenever the user changes their picture, so
 * it belongs in the seed: a new face is a new cache entry, not a stale one.
 */
export function avatarSeed(user?: { id?: number; photo?: string } | null): string {
  if (!user?.id) return "";
  const photo = user.photo ?? "";
  const mark = photo ? photo.split("/").filter(Boolean).slice(-2).join("/") : "";
  return mark ? `${user.id}·${mark}` : String(user.id);
}

function readStore(): Stored | null {
  try {
    const raw = window.localStorage.getItem(AVATAR_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Stored;
    if (!parsed || typeof parsed.data !== "string" || typeof parsed.seed !== "string") return null;
    if (!Number.isFinite(parsed.at) || Date.now() - parsed.at > KEEP_MS) return null;
    return parsed;
  } catch {
    return null; // private mode, a full quota, or somebody else's key
  }
}

function writeStore(entry: Stored): void {
  try {
    window.localStorage.setItem(AVATAR_KEY, JSON.stringify(entry));
  } catch {
    /* a full quota must never break the app */
  }
}

/** The picture already on this device, for an instant first paint. */
export function cachedAvatar(seed: string): string | null {
  if (!seed) return null;
  const remembered = memory.get(seed);
  if (remembered) return remembered;
  const stored = readStore();
  if (!stored || stored.seed !== seed) return null;
  memory.set(seed, stored.data);
  return stored.data;
}

function credentials(): Record<string, string> {
  const headers: Record<string, string> = {};
  const init = telegram()?.initData ?? "";
  if (init) headers["X-Init-Data"] = init;
  const signed = token();
  if (signed) headers["X-Vyron-Token"] = signed;
  const owner = ownerToken();
  if (owner) headers["X-Owner-Token"] = owner;
  return headers;
}

async function toDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the picture"));
    reader.readAsDataURL(blob);
  });
}

/**
 * Fetch the picture for *seed* (or return the one we already have).
 *
 * Resolves to `null` when the user has no picture, when the server cannot reach
 * Telegram, or when the app is offline — the caller draws the initials instead.
 * Never throws: a missing face is not an error the user should see.
 */
export function loadAvatar(seed: string): Promise<string | null> {
  if (!seed) return Promise.resolve(null);
  const known = memory.get(seed);
  const last = asked.get(seed) ?? 0;
  if (known && Date.now() - last < REFRESH_MS) return Promise.resolve(known);

  const pending = inFlight.get(seed);
  if (pending) return pending;

  const request = (async () => {
    try {
      const response = await fetch("/api/avatar", {
        method: "GET",
        headers: credentials(),
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) {
        asked.set(seed, Date.now());
        return known ?? null;
      }
      const data = await toDataUrl(await response.blob());
      if (!data.startsWith("data:image/")) return known ?? null;
      asked.set(seed, Date.now());
      if (data === known) return data;
      memory.set(seed, data);
      if (data.length <= MAX_STORED) writeStore({ seed, data, at: Date.now() });
      return data;
    } catch {
      return known ?? null; // offline: whatever we already have is good enough
    } finally {
      inFlight.delete(seed);
    }
  })();

  inFlight.set(seed, request);
  return request;
}

/** Warm the cache as soon as the state arrives, before anything renders it. */
export function primeAvatar(user?: { id?: number; photo?: string } | null): void {
  const seed = avatarSeed(user);
  if (seed) void loadAvatar(seed);
}

/** Forget everything — used when a different account signs in. */
export function forgetAvatar(): void {
  memory.clear();
  asked.clear();
  try {
    window.localStorage.removeItem(AVATAR_KEY);
  } catch {
    /* nothing to forget */
  }
}
