/**
 * Offline — the songs you keep on the phone.
 *
 * The Mini App streams every byte through `/api/stream`, which the service
 * worker deliberately never caches: a stale queue is worse than a spinner. So
 * there was no way to hear a track you had just played once the connection
 * went (a metro, a lift, a flight).
 *
 * This module is the exception, and it is explicit: nothing is kept unless the
 * listener asks for it, one track at a time. A "kept" track is a full 200
 * response stored in the Cache API under its *path* — the query carries a
 * short-lived token, and caching that would make the entry rot within the
 * hour. The service worker looks the same path up when the network fails.
 */

const CACHE = "vyron-offline-v1";

/** Names the cache is keyed by: the stream path, never the signed query. */
export function offlineKey(track: { id?: string | number }): string {
  const id = encodeURIComponent(String(track.id ?? "").trim());
  if (!id) return "";
  return `/api/stream/${id}`;
}

export function offlineSupported(): boolean {
  return typeof caches !== "undefined" && typeof fetch === "function";
}

async function open(): Promise<Cache | null> {
  if (!offlineSupported()) return null;
  try {
    return await caches.open(CACHE);
  } catch {
    return null;
  }
}

/** Absolute URL for a cache key — `cache.match` wants one in every browser. */
function absolute(path: string): string {
  try {
    return new URL(path, window.location.origin).toString();
  } catch {
    return path;
  }
}

export interface KeepResult {
  ok: boolean;
  reason?: string;
}

/**
 * Download one track to the device and remember it.
 *
 * Deliberately a plain GET with no `Range` header: a partial response cannot be
 * replayed as a whole file, and the byte ranges the player asks for later are
 * served by the browser from the complete entry.
 */
export async function keepOffline(
  track: { id?: string | number },
  url: string
): Promise<KeepResult> {
  const path = offlineKey(track);
  const cache = await open();
  if (!cache || !path) return { ok: false, reason: "this browser cannot keep music offline" };
  try {
    const response = await fetch(url, { credentials: "same-origin" });
    if (!response.ok) {
      return { ok: false, reason: `the server answered ${response.status}` };
    }
    // A `cache.put` of a partial body throws; this one is a complete answer.
    await cache.put(absolute(path), response.clone());
    return { ok: true };
  } catch (error) {
    return {
      ok: false,
      reason: error instanceof Error ? error.message : "the download failed",
    };
  }
}

export async function isKeptOffline(track: { id?: string | number }): Promise<boolean> {
  const path = offlineKey(track);
  const cache = await open();
  if (!cache || !path) return false;
  try {
    return Boolean(await cache.match(absolute(path)));
  } catch {
    return false;
  }
}

export async function forgetOffline(track: { id?: string | number }): Promise<boolean> {
  const path = offlineKey(track);
  const cache = await open();
  if (!cache || !path) return false;
  try {
    return await cache.delete(absolute(path));
  } catch {
    return false;
  }
}

/** How many tracks this device is keeping, for the profile card. */
export async function keptCount(): Promise<number> {
  const cache = await open();
  if (!cache) return 0;
  try {
    const keys = await cache.keys();
    return keys.filter((request) => request.url.includes("/api/stream/")).length;
  } catch {
    return 0;
  }
}

/** Drop the whole offline store.  takes a request, not a name. */
export async function clearOffline(): Promise<void> {
  if (!offlineSupported()) return;
  try {
    await caches.delete(CACHE);
  } catch {
    /* nothing to clear */
  }
}
